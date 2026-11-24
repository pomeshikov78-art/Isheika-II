"""Feasibility Engine (ТЗ-03 §5).

F = 100 · Σ(wᵢ·xᵢ) / Σ(wᵢ·aᵢ),  C = Σ(wᵢ·aᵢ) / Σwᵢ

xᵢ — нормированная оценка фактора [0;1], aᵢ — индикатор наличия оценки.
Неизвестный фактор ИСКЛЮЧАЕТСЯ из расчёта со снижением покрытия (не ноль!).
Показываются покрытие, диапазон, чувствительность и консервативная оценка.
F — экспертно-аналитическая оценка возможности достижения заданного
технического состояния, а НЕ вероятность успеха.
"""
from __future__ import annotations

import hashlib
import json

from ..contracts import iso_now, new_id
from ..storage import db
from ..workflow import events
from . import methodologies as M
from . import snapshot as SNAP


def collect_factors(research_id: str) -> list[dict]:
    from ..ai import agents as A
    from ..ai.simulation import FACTOR_MARKERS, _blob, _hits
    m = M.active("FEASIBILITY")
    weights = {f["code"]: f["weight"] for f in m["parameters"]["factors"]}
    names = {f["code"]: f["name"] for f in m["parameters"]["factors"]}
    sig = A.signals(research_id, "A08")
    docs = [db.dec(r, "identifiers") for r in
            db.query("SELECT * FROM research_documents WHERE research_id=? AND relevance_class IN ('DIRECT','ADJACENT')", (research_id,))]
    out = []
    if sig and sig.get("factors"):
        for f in sig["factors"]:
            code = f["code"]
            x = f.get("value")
            assessment = f.get("assessment", "unknown")
            out.append({"code": code, "name": names.get(code, code), "weight": weights.get(code, 0),
                        "assessment": assessment, "x": x,
                        "is_available": bool(x is not None and assessment != "unknown"),
                        "document_ids": f.get("document_ids") or [],
                        "rationale": f.get("rationale", ""), "producer": "agent:A08"})
        return out
    for code, markers in FACTOR_MARKERS.items():
        matched = [d for d in docs if _hits(_blob(d), markers)]
        strong = [d for d in matched if d["evidence_class"] in
                  ("primary_peer_reviewed", "primary_report", "dataset", "official_register", "standard", "patent")]
        real = [d for d in strong if not (d.get("identifiers") or {}).get("simulated")]
        if not matched:
            assessment, x = "unknown", None
        elif len(real) >= 3:
            assessment, x = "confirmed", 0.8
        elif real:
            assessment, x = "partial", 0.55
        else:
            assessment, x = "unknown", None
        out.append({"code": code, "name": names.get(code, code), "weight": weights.get(code, 0),
                    "assessment": assessment, "x": x,
                    "is_available": bool(x is not None and assessment != "unknown"),
                    "document_ids": [d["id"] for d in matched[:6]],
                    "rationale": f"Документов: {len(matched)}, приемлемых неимитационных: {len(real)}",
                    "producer": "deterministic_extractor"})
    return out


def _interpret(value: float, classes: list[dict]) -> str:
    for c in classes:
        if value <= c["max"]:
            return c["label"]
    return "очень высокая по доступным данным"


def compute(research_id: str, technology_id: str | None = None, *,
            factors: list[dict] | None = None, weight_overrides: dict | None = None,
            methodology_id: str | None = None, store: bool = True,
            assessed_by: str = "calculation_core") -> dict:
    """F = 100·Σ(w·x·a)/Σ(w·a); C = Σ(w·a)/Σw  (ИД-02, нормативная формула ТЗ-03).

    Неизвестный фактор исключается из числителя и знаменателя и снижает покрытие.
    Если неизвестны все факторы — F = NULL (не ноль), C = 0.
    """
    m = M.by_id(methodology_id) if methodology_id else M.active("FEASIBILITY")
    fs = [dict(f) for f in (factors if factors is not None else collect_factors(research_id))]
    if weight_overrides:
        for f in fs:
            if f["code"] in weight_overrides:
                f["weight"] = float(weight_overrides[f["code"]])
    for f in fs:
        f["is_available"] = bool(f.get("x") is not None and f.get("assessment") != "unknown")
    total_w = sum(f["weight"] for f in fs)
    known = [f for f in fs if f["is_available"]]
    denom = sum(f["weight"] for f in known)
    numer = sum(f["weight"] * float(f["x"]) for f in known)
    score = round(100.0 * numer / denom, 2) if denom else None
    coverage = round(denom / total_w, 4) if total_w else 0.0

    min_cov = float(m["thresholds"].get("min_coverage_for_interpretation", 0.6))
    interpretation_allowed = bool(score is not None and coverage >= min_cov)
    if score is None:
        coverage_warning = ("Все факторы неизвестны: итоговая оценка не рассчитывается (F = NULL), "
                            "покрытие C = 0.")
    elif not interpretation_allowed:
        coverage_warning = (f"Покрытие факторов {round(coverage * 100)} % ниже порога "
                            f"{round(min_cov * 100)} %: оценка выдаётся с ограничением интерпретации. "
                            "Порог имеет статус PROVISIONAL (калибровка не завершена).")
    else:
        coverage_warning = None

    # --- диапазон: неопределённость оценок + штраф за неполное покрытие
    if score is not None:
        spread = 0.0
        for f in known:
            u = 0.25 if f["assessment"] == "partial" else 0.12
            spread += f["weight"] * u
        rel = spread / denom if denom else 0.0
        half = 100.0 * rel + (1 - coverage) * 35.0
        low = max(0.0, round(score - half, 2))
        high = min(100.0, round(score + half, 2))
        conservative = low
    else:
        low = high = conservative = None

    # --- чувствительность: исключение фактора и вариация веса ±30 %
    sensitivity = []
    for f in known:
        rest = [g for g in known if g["code"] != f["code"]]
        d = sum(g["weight"] for g in rest)
        alt = round(100.0 * sum(g["weight"] * float(g["x"]) for g in rest) / d, 2) if d else None
        w_up = dict(f)
        w_up["weight"] = f["weight"] * 1.3
        mod = [w_up if g["code"] == f["code"] else g for g in known]
        d2 = sum(g["weight"] for g in mod)
        alt2 = round(100.0 * sum(g["weight"] * float(g["x"]) for g in mod) / d2, 2) if d2 else None
        sensitivity.append({"code": f["code"], "name": f["name"],
                            "without_factor": alt, "delta_without": round(alt - score, 2) if alt is not None else None,
                            "weight_plus30": alt2, "delta_weight": round(alt2 - score, 2) if alt2 is not None else None})

    unknown = [f["code"] for f in fs if not f["is_available"]]
    interpretation = _interpret(score, m["parameters"]["classes"]) if score is not None \
        else "недостаточно данных для оценки"
    inputs = {"research_id": research_id, "factors": fs}
    params = {"weights": {f["code"]: f["weight"] for f in fs},
              "min_coverage_for_interpretation": min_cov}
    snap = SNAP.capture(research_id, m, inputs, params, assessed_by=assessed_by)
    result = {"score": score, "coverage": coverage, "range": [low, high],
              "conservative": conservative, "factors": fs, "sensitivity": sensitivity,
              "unknown_factors": unknown, "interpretation": interpretation,
              "interpretation_allowed": interpretation_allowed, "coverage_warning": coverage_warning,
              "methodology_id": m["id"], "methodology_code": m["code"],
              "methodology_version": snap["methodology_version"], "input_hash": snap["input_hash"],
              "note": "F — оценка возможности достижения технического состояния, не вероятность успеха. "
                      "Неизвестные факторы исключены из расчёта, покрытие снижено."}
    result["output_hash"] = SNAP.output_hash({k: result[k] for k in ("score", "coverage", "range")})
    rec_id = new_id("fea-")
    if store:
        db.insert("analytics_feasibility", {
            "id": rec_id, "research_id": research_id, "technology_id": technology_id,
            "score": score, "coverage": coverage,
            "interpretation_allowed": 1 if interpretation_allowed else 0,
            "coverage_warning": coverage_warning, "unknown_factors": unknown,
            "range_low": low, "range_high": high, "conservative": conservative,
            "factors": fs, "weights": params["weights"], "sensitivity": sensitivity,
            "interpretation": interpretation, "output_hash": result["output_hash"],
            **{k: snap[k] for k in ("methodology_id", "methodology_version", "input_hash",
                                    "document_set_version", "model_id", "model_version",
                                    "prompt_version", "input_snapshot", "parameters",
                                    "config_checksum", "assessed_by")},
            "created_at": iso_now()})
        if technology_id:
            db.update("knowledge_technologies", "id", technology_id,
                      {"feasibility": score, "coverage": coverage, "updated_at": iso_now()})
        events.emit("analytics.feasibility", research_id=research_id,
                    payload={"score": score, "coverage": coverage, "range": [low, high],
                             "interpretation_allowed": interpretation_allowed,
                             "unknown_factors": unknown})
    return {"id": rec_id if store else None, **result}


def latest(research_id: str) -> dict | None:
    row = db.one("SELECT * FROM analytics_feasibility WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,))
    return db.dec(row, "factors", "weights", "sensitivity", "unknown_factors", "input_snapshot", "parameters")


def history(research_id: str) -> list[dict]:
    return db.query("""SELECT id, score, coverage, interpretation_allowed, methodology_version,
                              input_hash, output_hash, created_at
                       FROM analytics_feasibility WHERE research_id=? ORDER BY created_at""", (research_id,))
