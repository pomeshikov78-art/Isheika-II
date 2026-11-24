"""Событийная модель (ТЗ-05 §11).

События пишутся в БД (воспроизводимость и восстановление после потери
соединения) и рассылаются подписчикам SSE. Клиент может запросить события
начиная с последнего полученного id.
"""
from __future__ import annotations

import queue
import threading
from typing import Iterator

from .. import telemetry
from ..contracts import iso_now, new_id
from ..storage import db

_SUBSCRIBERS: list[queue.Queue] = []
_LOCK = threading.RLock()

EVENT_TYPES = (
    "research.created", "research.started", "research.state_changed", "research.completed",
    "job.queued", "job.started", "job.progress", "job.completed", "job.failed", "job.retrying",
    "search.source_started", "search.source_finished", "search.source_failed",
    "document.discovered", "document.normalized", "document.duplicate", "document.assessed",
    "ai.request_created", "ai.routed", "ai.response", "ai.schema_error", "ai.fallback",
    "ai.policy_blocked", "ai.quota", "consensus.conflict", "evidence.added",
    "analytics.trl", "analytics.feasibility", "forecast.ready", "quality.updated",
    "report.ready", "system.warning", "system.error",
)


def emit(event_type: str, *, research_id: str | None = None, job_id: str | None = None,
         payload: dict | None = None, severity: str = "info") -> dict:
    trace = telemetry.current()
    ev = {"id": new_id("ev-"), "research_id": research_id, "job_id": job_id,
          "event_type": event_type, "severity": severity, "payload": payload or {},
          "correlation_id": trace["correlation_id"], "request_id": trace["request_id"],
          "created_at": iso_now()}
    try:
        db.insert("workflow_events", ev)
        row = db.one("SELECT seq FROM workflow_events WHERE id=?", (ev["id"],))
        ev["seq"] = row["seq"] if row else None
    except Exception:
        pass
    with _LOCK:
        for q in list(_SUBSCRIBERS):
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass
    return ev


def subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=1000)
    with _LOCK:
        _SUBSCRIBERS.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _LOCK:
        if q in _SUBSCRIBERS:
            _SUBSCRIBERS.remove(q)


def history(research_id: str | None = None, after: str | None = None, limit: int = 500) -> list[dict]:
    sql = "SELECT * FROM workflow_events WHERE 1=1"
    params: list = []
    if research_id:
        sql += " AND research_id=?"
        params.append(research_id)
    if after:
        sql += " AND created_at>?"
        params.append(after)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = db.query(sql, params)
    return [db.dec(r, "payload") for r in rows]


def stream(q: queue.Queue) -> Iterator[str]:
    """Генератор SSE."""
    import json
    import time
    last = time.time()
    while True:
        try:
            ev = q.get(timeout=10)
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        except queue.Empty:
            if time.time() - last > 15:
                yield ": keep-alive\n\n"
                last = time.time()
        except GeneratorExit:
            return
