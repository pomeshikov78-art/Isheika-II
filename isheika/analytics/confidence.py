"""Уверенность аналитического вывода (ИД-10, ведомость v1.1).

Три показателя физически разделены и не подменяют друг друга:
  * F  — интегральная экспертно-аналитическая оценка реализуемости (0–100);
  * P(T≤t) — вероятность достижения целевого состояния к сроку (0–1);
  * Уверенность — степень обоснованности конкретной оценки доказательствами (0–1).

Уверенность рассчитывается по ЧИСЛУ НЕЗАВИСИМЫХ групп доказательств (ИД-11),
полноте покрытия, наличию противоречий и качеству источников. Она не является
ни вероятностью успеха, ни оценкой реализуемости.
"""
from __future__ import annotations

from ..contracts import iso_now, new_id
from ..storage import db
from ..workflow import events
from . import methodologies as M
from . import snapshot as SNAP

SUBJECTS = ("trl", "feasibility", "forecast", "claim")


def _evidence_stats(research_id: str) -> dict:
    groups = db.one("""SELECT COUNT(DISTINCT ifnull(independence_group_id, independence_group)) AS n
                       FROM evidence_items WHERE research_id=?""", (research_id,)) or {"n": 0}
    total = db.count("evidence_items", "research_id=?", (research_id,))
    supported = db.count("evidence_items", "research_id=? AND status='SUPPORTED'", (research_id,))
    contradictions = db.count("evidence_items", "research_id=? AND status='CONTRADICTED'", (research_id,))
    derived = db.count("evidence_items",
                       "research_id=? AND origin_class IN ('REPRINT','SUMMARY','DERIVATIVE')", (research_id,))
    quality = db.one("SELECT AVG(quality) AS q FROM evidence_items WHERE research_id=?", (research_id,)) or {}
    return {"independent_groups": int(groups["n"] or 0), "evidence_count": total,
            "supported": supported, "contradictions": contradictions, "derived": derived,
            "mean_quality": round(quality.get("q") or 0.0, 4)}


def compute(research_id: str, subject_kind: str, *, subject_id: str | None = None,
            coverage: float | None = None, technology_id: str | None = None,
            store: bool = True) -> dict:
    if subject_kind not in SUBJECTS:
        raise ValueError(f"Неизвестный subject_kind: {subject_kind}")
    m = M.active("EVIDENCE_QUALITY")
    st = _evidence_stats(research_id)
    g = st["independent_groups"]
    # насыщение по независимым группам: 1 группа ≤ 0.45, 2 → 0.65, 3+ → 0.8, 5+ → 0.9
    base = min(0.9, 0.25 + 0.20 * min(g, 4))
    quality_factor = 0.6 + 0.4 * st["mean_quality"]
    contradiction_penalty = min(0.35, 0.12 * st["contradictions"])
    cov = coverage if coverage is not None else 1.0
    coverage_factor = 0.5 + 0.5 * max(0.0, min(1.0, cov))
    value = max(0.0, min(0.95, base * quality_factor * coverage_factor - contradiction_penalty))
    value = round(value, 4) if st["evidence_count"] else None

    limitations = []
    if g <= 1:
        limitations.append("Подтверждение опирается на одну группу независимости: "
                           "перепечатки одного сообщения не увеличивают уверенность")
    if st["derived"]:
        limitations.append(f"Производных публикаций: {st['derived']} — учтены как зависимые")
    if st["contradictions"]:
        limitations.append(f"Противоречий: {st['contradictions']} — уверенность снижена")
    if coverage is not None and coverage < 0.6:
        limitations.append(f"Покрытие факторов {round(coverage * 100)} % — интерпретация ограничена")
    if not st["evidence_count"]:
        limitations.append("Доказательства отсутствуют: уверенность не определена")

    inputs = {"research_id": research_id, "subject_kind": subject_kind, "subject_id": subject_id, **st}
    params = {"saturation": "0.25 + 0.20·min(groups,4)", "contradiction_penalty": 0.12,
              "coverage_factor": "0.5 + 0.5·C"}
    snap = SNAP.capture(research_id, m, inputs, params)
    rec_id = new_id("cnf-")
    result = {"confidence": value, "subject_kind": subject_kind, "subject_id": subject_id,
              "independent_groups": g, "evidence_count": st["evidence_count"],
              "contradictions": st["contradictions"], "coverage": coverage,
              "basis": st, "limitations": limitations,
              "methodology_id": m["id"], "methodology_version": snap["methodology_version"],
              "note": "Уверенность ≠ реализуемость F и ≠ вероятность P(T≤t) (ИД-10)"}
    if store:
        db.insert("analytics_confidence", {
            "id": rec_id, "research_id": research_id, "technology_id": technology_id,
            "subject_kind": subject_kind, "subject_id": subject_id, "confidence": value,
            "independent_groups": g, "evidence_count": st["evidence_count"],
            "contradictions": st["contradictions"], "coverage": coverage,
            "basis": st, "limitations": limitations,
            **{k: snap[k] for k in ("methodology_id", "methodology_version", "input_hash",
                                    "document_set_version", "model_id", "model_version",
                                    "prompt_version", "input_snapshot", "parameters",
                                    "config_checksum", "assessed_by")},
            "created_at": iso_now()})
        events.emit("analytics.confidence", research_id=research_id,
                    payload={"subject": subject_kind, "confidence": value, "independent_groups": g})
    return {"id": rec_id if store else None, **result}


def compute_all(research_id: str) -> dict:
    """Уверенность по каждому показателю отдельно (запрет подмены, ИД-10)."""
    fea = db.one("SELECT id, coverage FROM analytics_feasibility WHERE research_id=? ORDER BY created_at DESC LIMIT 1",
                 (research_id,))
    trl = db.one("SELECT id FROM analytics_trl WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,))
    fct = db.one("SELECT id FROM forecast_runs WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,))
    out = {}
    if trl:
        out["trl"] = compute(research_id, "trl", subject_id=trl["id"])
    if fea:
        out["feasibility"] = compute(research_id, "feasibility", subject_id=fea["id"], coverage=fea["coverage"])
    if fct:
        out["forecast"] = compute(research_id, "forecast", subject_id=fct["id"], coverage=0.5)
    return out


def latest(research_id: str, subject_kind: str | None = None) -> dict | list | None:
    if subject_kind:
        row = db.one("""SELECT * FROM analytics_confidence WHERE research_id=? AND subject_kind=?
                        ORDER BY created_at DESC LIMIT 1""", (research_id, subject_kind))
        return db.dec(row, "basis", "limitations", "input_snapshot", "parameters")
    rows = db.query("""SELECT * FROM analytics_confidence c WHERE research_id=? AND created_at=(
                          SELECT MAX(created_at) FROM analytics_confidence c2
                          WHERE c2.research_id=c.research_id AND c2.subject_kind=c.subject_kind)
                       ORDER BY subject_kind""", (research_id,))
    return [db.dec(r, "basis", "limitations", "input_snapshot", "parameters") for r in rows]
