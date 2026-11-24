"""Альтернативные решения (ТЗ-03 §6): сравнение по единым критериям."""
from __future__ import annotations

from ..contracts import iso_now, new_id
from ..registry.loader import methodology
from ..storage import db

CRITERIA = methodology()["alternatives"]["criteria"]


def compute(research_id: str) -> dict:
    from ..ai import agents as A
    sig = A.signals(research_id, "A09") or {}
    items = sig.get("alternatives") or []
    if not items:
        from ..ai.simulation import _agent_a09
        docs = A.document_package(research_id, limit=40)
        items = _agent_a09({}, docs).get("alternatives", [])
    out = []
    for a in items[:15]:
        crit = {c: None for c in CRITERIA}
        crit["функция"] = (a.get("principle") or "")[:160] or None
        crit["принцип действия"] = (a.get("principle") or "")[:160] or None
        rec = {"id": new_id("alt-"), "research_id": research_id, "name": a.get("name", "")[:300],
               "criteria": crit, "evidence_ids": [], "created_at": iso_now()}
        db.insert("analytics_alternatives", rec)
        out.append({**rec, "document_ids": a.get("document_ids") or []})
    return {"alternatives": out, "criteria": CRITERIA,
            "note": "Незаполненные критерии = «неизвестно», а не ноль. Сравнение требует данных испытаний."}


def list_alternatives(research_id: str) -> list[dict]:
    return [db.dec(r, "criteria", "evidence_ids")
            for r in db.query("SELECT * FROM analytics_alternatives WHERE research_id=?", (research_id,))]
