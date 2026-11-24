"""Коллективный анализ моделей (ТЗ-02 §6, ТЗ-05 §8.9).

Режим 1 — независимые оценки: одинаковый пакет данных, разные модели.
Режим 2 — перекрёстная проверка: модели проверяют аргументы друг друга.
Режим 3 — арбитраж: Critic разбирает противоречия по первоисточникам.
Режим 4 — синтез: Report объединяет подтверждённые факты и маркированные оценки.

Голосование моделей НЕ является доказательством. Совпадение ответов не
повышает достоверность без независимых источников. Противоречия сохраняются.
"""
from __future__ import annotations

import json

from ..contracts import iso_now, new_id
from ..storage import db
from ..workflow import events
from . import agents, orchestrator


def independent_estimates(research_id: str, agent_code: str, task_class: str,
                          max_models: int = 3) -> list[dict]:
    """Режим 1: несколько моделей получают одинаковый пакет независимо."""
    docs = agents.document_package(research_id)
    payload = {"documents": docs, "mode": "independent"}
    route = None
    try:
        route = orchestrator.select_route(task_class)
    except Exception:
        return []
    entries = [route["entry"]] + route.get("alternatives", [])
    seen, out = set(), []
    for e in entries:
        pid = e["provider"]["id"]
        if pid in seen:
            continue
        seen.add(pid)
        res = orchestrator.execute(research_id, agent_code, task_class, payload,
                                   mode="independent", force_provider=pid)
        if res["ok"]:
            out.append(res)
        if len(out) >= max_models:
            break
    return out


def cross_check(research_id: str, positions: list[dict]) -> dict:
    """Режим 2: перекрёстная проверка. Исходные ответы сохраняются."""
    payload = {"documents": agents.document_package(research_id, limit=20),
               "positions": [{"agent": p["agent"], "provider": p.get("provider"),
                              "structured": p.get("structured")} for p in positions]}
    res = orchestrator.execute(research_id, "A11", "critique", payload, mode="cross_check")
    return res


def arbitrate(research_id: str, conflicts: list[dict]) -> dict:
    """Режим 3: арбитраж по первоисточникам и логике."""
    payload = {"documents": agents.document_package(research_id, limit=25), "conflicts": conflicts}
    return orchestrator.execute(research_id, "A11", "arbitration", payload, mode="arbitration")


def synthesize(research_id: str) -> dict:
    """Режим 4: синтез только подтверждённых фактов и маркированных оценок."""
    claims = db.query("SELECT id, claim_text, claim_type, status FROM knowledge_claims WHERE research_id=? LIMIT 200",
                      (research_id,))
    payload = {"documents": agents.document_package(research_id, limit=15), "claims": claims}
    return orchestrator.execute(research_id, "A12", "synthesis", payload, mode="synthesis")


def detect_conflicts(positions: list[dict]) -> list[dict]:
    """Формальное выявление расхождений между позициями моделей."""
    conflicts: list[dict] = []
    by_topic: dict[str, list[dict]] = {}
    for p in positions:
        s = p.get("structured") or {}
        for f in s.get("findings", []) or []:
            key = (f.get("claim") or "")[:60].lower()
            by_topic.setdefault(key, []).append({"provider": p.get("provider"),
                                                 "claim_type": f.get("claim_type"),
                                                 "document_ids": f.get("document_ids") or []})
        for sig in s.get("signals", []) or []:
            key = "trl:" + str(sig.get("criterion_id"))
            by_topic.setdefault(key, []).append({"provider": p.get("provider"),
                                                 "observed": sig.get("observed"),
                                                 "document_ids": sig.get("document_ids") or []})
    for topic, items in by_topic.items():
        if len(items) < 2:
            continue
        values = {json.dumps({k: v for k, v in i.items() if k != "provider"}, sort_keys=True, ensure_ascii=False)
                  for i in items}
        if len(values) > 1:
            conflicts.append({"topic": topic, "positions": items, "resolved": False,
                              "note": "Расхождение позиций; голосование не является доказательством"})
    return conflicts


def run_collective(research_id: str, *, deep: bool = False, progress_cb=None) -> dict:
    positions: list[dict] = []
    if deep:
        for agent_code, task_class in (("A07", "trl_signals"), ("A08", "feasibility_signals")):
            positions += independent_estimates(research_id, agent_code, task_class, max_models=3)
    else:
        for code in ("A07", "A08", "A11"):
            s = agents.signals(research_id, code)
            if s:
                row = db.one("""SELECT provider_id FROM ai_requests r JOIN ai_results res ON res.request_id=r.id
                                WHERE res.research_id=? AND res.agent_code=? ORDER BY res.created_at DESC LIMIT 1""",
                             (research_id, code))
                positions.append({"agent": code, "provider": (row or {}).get("provider_id"), "structured": s})
    conflicts = detect_conflicts(positions)
    cross = cross_check(research_id, positions) if positions else {"ok": False}
    arb = arbitrate(research_id, conflicts) if conflicts else {"ok": False}
    syn = synthesize(research_id)

    cid = new_id("cons-")
    db.insert("ai_consensus", {
        "id": cid, "research_id": research_id, "topic": "TRL/реализуемость/критика",
        "mode": "independent+cross_check+arbitration+synthesis" if deep else "cross_check+arbitration+synthesis",
        "positions": [{"agent": p["agent"], "provider": p.get("provider")} for p in positions],
        "conflicts": conflicts,
        "resolution": (arb.get("structured") if arb.get("ok") else None),
        "synthesis": (syn.get("structured") if syn.get("ok") else None),
        "created_at": iso_now()})
    for c in conflicts:
        events.emit("consensus.conflict", research_id=research_id, severity="warning", payload=c)
    return {"positions": len(positions), "conflicts": len(conflicts),
            "cross_check_ok": bool(cross.get("ok")), "arbitration_ok": bool(arb.get("ok")),
            "synthesis_ok": bool(syn.get("ok")), "consensus_id": cid,
            "_state": "completed" if syn.get("ok") else "partial"}
