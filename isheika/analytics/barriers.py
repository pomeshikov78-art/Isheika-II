"""Анализ барьеров (ТЗ-03 §6). Классификация, критичность, доказательность."""
from __future__ import annotations

from ..contracts import iso_now, new_id
from ..registry.loader import methodology
from ..storage import db
from ..workflow import events

STRONG = {"primary_peer_reviewed", "primary_report", "dataset", "official_register", "standard"}


def compute(research_id: str) -> dict:
    from ..ai.simulation import BARRIER_MARKERS, _blob, _hits
    docs = [db.dec(r, "identifiers") for r in
            db.query("SELECT * FROM research_documents WHERE research_id=? AND relevance_class IN ('DIRECT','ADJACENT')", (research_id,))]
    out = []
    for btype, markers in BARRIER_MARKERS.items():
        matched = [d for d in docs if _hits(_blob(d), markers)]
        if not matched:
            continue
        strong = [d for d in matched if d["evidence_class"] in STRONG and not (d.get("identifiers") or {}).get("simulated")]
        criticality = round(min(1.0, 0.35 + 0.12 * len(matched)), 3)
        probability = round(min(1.0, 0.3 + 0.15 * len(strong)), 3)
        ev_ids = [r["id"] for r in db.query(
            "SELECT id FROM evidence_items WHERE research_id=? AND document_id IN (%s) LIMIT 5" %
            ",".join("?" * min(5, len(matched))), [research_id] + [d["id"] for d in matched[:5]])] if matched else []
        rec = {"id": new_id("bar-"), "research_id": research_id, "barrier_type": btype,
               "title": f"Барьер: {btype}", "criticality": criticality, "probability": probability,
               "evidence_ids": ev_ids,
               "dependencies": [], "workarounds": [], "created_at": iso_now()}
        db.insert("analytics_barriers", rec)
        out.append({**rec, "documents": len(matched), "strong_evidence": len(strong),
                    "document_ids": [d["id"] for d in matched[:6]],
                    "note": "Критичность и вероятность — стартовые эвристики, требуют экспертного подтверждения"})
    # пробелы TRL тоже являются барьерами (нормативные/производственные и т.п.)
    events.emit("system.warning" if not out else "job.progress", research_id=research_id,
                payload={"barriers": len(out)})
    return {"barriers": out, "types_total": len(methodology()["barriers"]["types"]),
            "types_detected": len(out),
            "note": "Отсутствие найденных барьеров не означает их отсутствия: это пробел поиска"}


def list_barriers(research_id: str) -> list[dict]:
    return [db.dec(r, "evidence_ids", "dependencies", "workarounds")
            for r in db.query("SELECT * FROM analytics_barriers WHERE research_id=? ORDER BY criticality DESC", (research_id,))]
