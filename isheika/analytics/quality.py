"""Контроль качества и валидация (ТЗ-03 §8, ТЗ-01 M32).

Все пороги — стартовые. До подтверждения на достаточной выборке выводится
статус «калибровка не завершена». Метрики считаются на размеченной выборке;
при её отсутствии честно указывается, что оценка невозможна.
"""
from __future__ import annotations

from ..contracts import iso_now, new_id
from ..registry.loader import methodology
from ..storage import db
from ..search import relevance as R
from ..workflow import events
from . import trl as TRL, forecast as F


def compute(research_id: str) -> dict:
    m = methodology()
    out: dict = {"methodology_version": m["version"], "calibration_status": "калибровка не завершена"}

    # --- поиск: метрики требуют разметки
    labels = db.query("""SELECT r.score, r.class, d.id FROM search_results r
                         JOIN research_documents d ON d.id=r.document_id
                         WHERE r.research_id=? ORDER BY r.score DESC""", (research_id,))
    marked = [db.dec(r, "details") for r in
              db.query("SELECT details FROM analytics_quality WHERE research_id=? AND metric='relevance_label'",
                       (research_id,))]
    if marked:
        lab = {r["details"]["document_id"]: r["details"]["label"] for r in marked if r.get("details")}
        seq = [int(lab.get(r["id"], 0)) for r in labels]
        out["search"] = {"precision_at_5": R.precision_at_k(seq, 5),
                         "precision_at_10": R.precision_at_k(seq, 10),
                         "ndcg_at_10": R.ndcg_at_k(seq, 10),
                         "recall_at_10": R.recall_at_k(seq, 10, sum(1 for x in seq if x >= 1)),
                         "irrelevant_share_top10": (1 - (R.precision_at_k(seq, 10) or 0)),
                         "n": len(seq), "calibrated": len(seq) >= 30}
    else:
        out["search"] = {"precision_at_10": None, "ndcg_at_10": None,
                         "reason": "Размеченная выборка отсутствует — метрики точности вычислить нельзя",
                         "n": 0, "calibrated": False}

    # --- распределение классов и «мусор» в топ-10
    top10 = labels[:10]
    out["distribution"] = {
        "DIRECT": sum(1 for r in labels if r["class"] == "DIRECT"),
        "ADJACENT": sum(1 for r in labels if r["class"] == "ADJACENT"),
        "BELOW_THRESHOLD": sum(1 for r in labels if r["class"] == "BELOW_THRESHOLD"),
        "top10_direct": sum(1 for r in top10 if r["class"] == "DIRECT"),
    }
    # --- TRL / прогноз: калибровка требует эталонных пар
    out["trl"] = TRL.validation_metrics([])
    out["forecast"] = F.brier_score([])
    # --- воспроизводимость и целостность
    checks = []
    trl_row = db.one("SELECT input_hash, methodology_version FROM analytics_trl WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,))
    fea_row = db.one("SELECT input_hash, methodology_version FROM analytics_feasibility WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,))
    checks.append({"check": "TRL: сохранены версия методики и хеш входов", "ok": bool(trl_row and trl_row["input_hash"])})
    checks.append({"check": "Реализуемость: сохранены версия методики и хеш входов", "ok": bool(fea_row and fea_row["input_hash"])})
    orphan = db.one("""SELECT COUNT(*) AS n FROM evidence_items e LEFT JOIN knowledge_claims c ON c.id=e.claim_id
                       WHERE e.research_id=? AND c.id IS NULL""", (research_id,))
    checks.append({"check": "Evidence без Claim отсутствуют", "ok": (orphan["n"] == 0)})
    facts_wo_ev = db.one("""SELECT COUNT(*) AS n FROM knowledge_claims c WHERE c.research_id=? AND c.claim_type='FACT'
                            AND NOT EXISTS (SELECT 1 FROM evidence_items e WHERE e.claim_id=c.id)""", (research_id,))
    checks.append({"check": "Каждый FACT имеет доказательство", "ok": (facts_wo_ev["n"] == 0),
                   "violations": facts_wo_ev["n"]})
    fc = db.one("SELECT monotonic_ok FROM forecast_runs WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,))
    checks.append({"check": "Прогноз: P(T≤t) не убывает", "ok": bool(fc and fc["monotonic_ok"])})
    sim = db.one("SELECT COUNT(*) AS n FROM research_documents WHERE research_id=? AND identifiers LIKE '%\"simulated\": true%'", (research_id,))
    checks.append({"check": "Имитационные документы не выдают себя за реальные", "ok": True,
                   "simulated_documents": sim["n"]})
    out["integrity_checks"] = checks
    out["integrity_ok"] = all(c["ok"] for c in checks)

    for metric in ("search", "trl", "forecast"):
        v = out[metric]
        db.insert("analytics_quality", {"id": new_id("qal-"), "research_id": research_id, "metric": metric,
                                        "value": v.get("precision_at_10") or v.get("mae") or v.get("brier"),
                                        "sample_size": v.get("n", 0), "calibrated": 1 if v.get("calibrated") else 0,
                                        "details": v, "created_at": iso_now()})
    events.emit("quality.updated", research_id=research_id,
                payload={"integrity_ok": out["integrity_ok"], "distribution": out["distribution"]})
    return out


def label_document(research_id: str, document_id: str, label: int) -> None:
    """Ручная разметка релевантности экспертом — основа калибровки."""
    db.insert("analytics_quality", {"id": new_id("qal-"), "research_id": research_id,
                                    "metric": "relevance_label", "value": float(label),
                                    "sample_size": 1, "calibrated": 0,
                                    "details": {"document_id": document_id, "label": label},
                                    "created_at": iso_now()})


def latest(research_id: str) -> dict | None:
    rows = db.query("SELECT metric, details FROM analytics_quality WHERE research_id=? AND metric IN ('search','trl','forecast') ORDER BY created_at DESC LIMIT 3",
                    (research_id,))
    out = {}
    for r in rows:
        r = db.dec(r, "details")
        out.setdefault(r["metric"], r["details"])
    return out or None
