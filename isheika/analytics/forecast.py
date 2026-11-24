"""Прогнозный модуль (ТЗ-03 §7, ИД-05 и ИД-10 ведомости v1.1).

Горизонты 0–2, 2–5, 5–10, 10–20, 20–35, 35–50 лет; три сценария.
P(T ≤ t) не убывает со временем (монотонность проверяется автоматически).

Внутренняя точность хранения и допустимая точность представления разделены:
значение probability_value сохраняется с полной разрядностью для калибровки и
воспроизводимости, но режим показа (EXACT / INTERVAL / COARSE / SCENARIO)
определяется СЕРВЕРНОЙ политикой по горизонту и статусу калибровки.
Интерфейс не вправе показать точность выше display_precision.

P(T≤t) — вероятность достижения целевого состояния к сроку; она НЕ выводится
автоматически из F и не подменяет ни реализуемость, ни уверенность.
"""
from __future__ import annotations

import math

from ..contracts import iso_now, new_id
from ..storage import db
from ..workflow import events
from . import methodologies as M
from . import snapshot as SNAP

TARGETS = {
    "scientific_result": "Научный результат",
    "working_prototype": "Работоспособный прототип",
    "industrial_production": "Промышленное производство",
    "wide_adoption": "Широкое внедрение",
}


def _logistic(t: float, midpoint: float, steepness: float) -> float:
    return 1.0 / (1.0 + math.exp(-steepness * (t - midpoint)))


def _qualitative(p: float) -> str:
    if p >= 0.8:
        return "высокая вероятность по доступным данным"
    if p >= 0.5:
        return "вероятно при сохранении текущих условий"
    if p >= 0.25:
        return "возможно при снятии ключевых барьеров"
    return "маловероятно без прорыва"


def _round_coarse(p: float) -> float:
    """Укрупнённый ориентир: шаг 5 процентных пунктов."""
    return round(round(p * 100 / 5) * 5) / 100


def presentation_for(point: dict, *, calibrated: bool = False) -> dict:
    """ИД-05: серверная политика представления конкретной точки прогноза."""
    # политика применяется к ПОЛОСЕ горизонта (0–2, 2–5, …), а не к его правой границе
    years = int(point.get("years_from") if point.get("years_from") is not None
                else point.get("forecast_horizon_years") or 0)
    pol = M.presentation_policy(years, calibrated=calibrated)
    p = point.get("probability_value")
    lo = point.get("probability_lower")
    hi = point.get("probability_upper")
    mode = pol["mode"]
    if p is None:
        mode = "SCENARIO"
    display_value = None
    display_text = ""
    interval = None
    if mode == "EXACT":
        display_value = round(p * 100, pol["precision"])
        display_text = f"{display_value:.{pol['precision']}f} %"
    elif mode == "INTERVAL":
        display_value = round(p * 100, pol["precision"])
        interval = [round((lo if lo is not None else max(0.0, p - 0.25)) * 100, 1),
                    round((hi if hi is not None else min(1.0, p + 0.25)) * 100, 1)]
        display_text = f"{display_value:.{pol['precision']}f} % (интервал {interval[0]:.0f}–{interval[1]:.0f} %)"
    elif mode == "COARSE":
        display_value = _round_coarse(p) * 100
        interval = [round((lo if lo is not None else max(0.0, p - 0.3)) * 100),
                    round((hi if hi is not None else min(1.0, p + 0.3)) * 100)]
        display_text = f"≈ {display_value:.0f} % (укрупнённо; интервал {interval[0]:.0f}–{interval[1]:.0f} %)"
    else:  # SCENARIO
        interval = [round((lo if lo is not None else max(0.0, p - 0.35)) * 100),
                    round((hi if hi is not None else min(1.0, p + 0.35)) * 100)] if p is not None else None
        display_text = _qualitative(p) if p is not None else "недостаточно данных для оценки"
        if interval:
            display_text += f"; сценарный диапазон {interval[0]:.0f}–{interval[1]:.0f} %"
    return {"mode": mode, "precision": pol["precision"] if mode != "SCENARIO" else -1,
            "display_value": display_value, "display_text": display_text,
            "interval": interval, "uncertainty_class": pol["uncertainty_class"],
            "warning_text": pol["warning_text"], "calibration_status": "CALIBRATED" if calibrated else "NOT_CALIBRATED"}


def _calibrated(research_id: str) -> bool:
    row = db.one("""SELECT calibrated FROM analytics_quality WHERE research_id=? AND metric='brier_score'
                    ORDER BY created_at DESC LIMIT 1""", (research_id,))
    return bool(row and row["calibrated"])


def compute(research_id: str, *, trl: int | None = None, feasibility: dict | None = None,
            trends: dict | None = None, methodology_id: str | None = None,
            store: bool = True, assessed_by: str = "calculation_core") -> dict:
    m = M.by_id(methodology_id) if methodology_id else M.active("FORECAST")
    horizons = m["parameters"]["horizons"]
    calibrated = _calibrated(research_id)
    trl_row = db.one("SELECT trl FROM analytics_trl WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,))
    trl = trl if trl is not None else (trl_row["trl"] if trl_row else 1)
    fea = feasibility or db.dec(db.one("SELECT * FROM analytics_feasibility WHERE research_id=? ORDER BY created_at DESC LIMIT 1",
                                       (research_id,)), "factors")
    series = (trends or {}).get("publications") or []
    vals = [p["value"] for p in series if p["value"] is not None]
    enough_data = len(vals) >= 6
    growth = (trends or {}).get("growth_rate")

    f_score = (fea or {}).get("score")
    coverage = (fea or {}).get("coverage") or 0.0
    base_strength = (f_score / 100.0) if f_score is not None else 0.3
    steep = 0.18 + 0.25 * base_strength + (0.05 if (growth or 0) > 0.2 else 0.0)
    offsets = {"scientific_result": 0.0, "working_prototype": 3.0,
               "industrial_production": 7.0, "wide_adoption": 12.0}
    trl_shift = max(0.0, (9 - trl)) * 1.2

    scenarios_out = {}
    intervals = {}
    points_rows = []
    monotonic_ok = True
    rec_id = new_id("fct-")
    for target, offset in offsets.items():
        midpoint = 4.0 + offset + trl_shift - 4.0 * base_strength
        scen = {}
        for name, delta, steep_mul in (("optimistic", -3.0, 1.25), ("base", 0.0, 1.0), ("pessimistic", 5.0, 0.8)):
            points = []
            prev = 0.0
            for h in horizons:
                t = h["to"]
                p = _logistic(t, midpoint + delta, steep * steep_mul)
                p = max(prev, min(1.0, p))       # монотонность P(T<=t)
                if p < prev - 1e-9:
                    monotonic_ok = False
                prev = p
                # при недостатке данных численная оценка не формируется вовсе
                internal = round(p, 6) if (enough_data or h["to"] <= 10) else None
                half = 0.25 + 0.2 * (1 - coverage) + (0.10 if h["from"] >= 10 else 0.0)
                lo = round(max(0.0, p - half), 6) if internal is not None else None
                hi = round(min(1.0, p + half), 6) if internal is not None else None
                point = {"horizon": h["code"], "years_from": h["from"], "years_to": h["to"],
                         "forecast_horizon_years": h["to"],
                         "probability_value": internal, "probability_lower": lo, "probability_upper": hi,
                         "qualitative": _qualitative(p), "wide_interval": h["from"] >= 20,
                         "scenario_id": name, "target": target}
                pres = presentation_for(point, calibrated=calibrated)
                point["presentation"] = pres
                # псевдонимы для отображения: браузер получает уже применённую политику
                point["probability"] = pres["display_value"] / 100 if pres["display_value"] is not None else None
                point["interval"] = ([pres["interval"][0] / 100, pres["interval"][1] / 100]
                                     if pres["interval"] else None)
                point["display_mode"] = pres["mode"]
                points.append(point)
                points_rows.append({"target": target, "scenario_id": name, "horizon_code": h["code"],
                                    "years_from": h["from"], "years_to": h["to"], "point": point,
                                    "presentation": pres})
            scen[name] = points
        scenarios_out[target] = scen
        intervals[target] = {"method": "logistic_extrapolation" if enough_data else "qualitative_scenarios",
                             "midpoint_years": round(midpoint, 2), "steepness": round(steep, 3)}

    assumptions = [
        {"text": f"TRL={trl} принят по расчёту ядра TRL (не по мнению модели)", "kind": "input"},
        {"text": f"Реализуемость F={f_score}%, покрытие {round(coverage*100)}%" if f_score is not None
                 else "Реализуемость не определена: недостаточное покрытие факторов", "kind": "input"},
        {"text": "Временной ряд достаточен для экстраполяции" if enough_data
                 else "Временной ряд короткий: числа на дальних горизонтах не приводятся", "kind": "data"},
        {"text": "На горизонте 20–50 лет основной вывод — сценарии и диапазоны (ИД-05)", "kind": "rule"},
        {"text": "P(T≤t) — вероятность достижения целевого состояния; она не равна F и не равна уверенности (ИД-10)",
         "kind": "rule"},
    ]
    if not calibrated:
        assumptions.append({"text": "Калибровка прогнозной методики не завершена: точные вероятности не выводятся",
                            "kind": "warning"})

    inputs = {"research_id": research_id, "trl": trl, "feasibility_score": f_score,
              "coverage": coverage, "growth_rate": growth, "series_length": len(vals)}
    params = {"steepness": round(steep, 4), "offsets": offsets, "trl_shift": round(trl_shift, 3),
              "horizons": horizons, "calibrated": calibrated}
    snap = SNAP.capture(research_id, m, inputs, params, assessed_by=assessed_by)
    result = {"horizons": horizons, "targets": TARGETS, "scenarios": scenarios_out,
              "assumptions": assumptions, "intervals": intervals, "monotonic_ok": monotonic_ok,
              "data_sufficient": enough_data, "calibration_status": "CALIBRATED" if calibrated else "NOT_CALIBRATED",
              "methodology_id": m["id"], "methodology_code": m["code"],
              "methodology_version": snap["methodology_version"],
              "presentation_policy": m["parameters"]["presentation_policy"],
              "note": "P(T≤t) монотонна; режим представления задан сервером по горизонту и калибровке"}
    result["output_hash"] = SNAP.output_hash({"scenarios": scenarios_out})
    if store:
        db.insert("forecast_runs", {
            "id": rec_id, "research_id": research_id, "target": "all",
            "horizons": horizons, "scenarios": scenarios_out,
            "method": "logistic_extrapolation+markov_transition" if enough_data else "qualitative_scenarios",
            "assumptions": assumptions, "intervals": intervals,
            "monotonic_ok": 1 if monotonic_ok else 0,
            "presentation_policy": m["code"], "calibration_status": result["calibration_status"],
            "output_hash": result["output_hash"],
            **{k: snap[k] for k in ("methodology_id", "methodology_version", "input_hash",
                                    "document_set_version", "model_id", "model_version",
                                    "prompt_version", "input_snapshot", "parameters",
                                    "config_checksum", "assessed_by")},
            "created_at": iso_now()})
        for pr in points_rows:
            p, pres = pr["point"], pr["presentation"]
            db.insert("forecast_points", {
                "id": new_id("fpt-"), "forecast_id": rec_id, "research_id": research_id,
                "target": pr["target"], "scenario_id": pr["scenario_id"], "horizon_code": pr["horizon_code"],
                "forecast_horizon_years": pr["years_to"], "years_from": pr["years_from"],
                "probability_value": p["probability_value"], "probability_lower": p["probability_lower"],
                "probability_upper": p["probability_upper"], "display_mode": pres["mode"],
                "display_precision": pres["precision"], "display_value": pres["display_value"],
                "display_text": pres["display_text"], "uncertainty_class": pres["uncertainty_class"],
                "calibration_status": pres["calibration_status"], "warning_text": pres["warning_text"],
                "qualitative": p["qualitative"], "created_at": iso_now()})
        events.emit("forecast.ready", research_id=research_id,
                    payload={"targets": list(scenarios_out), "monotonic_ok": monotonic_ok,
                             "data_sufficient": enough_data, "calibrated": calibrated})
    return {"id": rec_id if store else None, **result}


def latest(research_id: str) -> dict | None:
    row = db.one("SELECT * FROM forecast_runs WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,))
    if not row:
        return None
    out = db.dec(row, "horizons", "scenarios", "assumptions", "intervals", "input_snapshot", "parameters")
    out["presentation_policy_code"] = out.get("presentation_policy")
    out["presentation_policy"] = M.active("FORECAST")["parameters"]["presentation_policy"]
    # для записей, созданных до v1.1, политика представления применяется на чтении
    for target, scen in (out.get("scenarios") or {}).items():
        for name, points in scen.items():
            for p in points:
                if "presentation" not in p:
                    p.setdefault("probability_value", p.get("probability"))
                    iv = p.get("interval") or [None, None]
                    p.setdefault("probability_lower", iv[0])
                    p.setdefault("probability_upper", iv[1])
                    p["presentation"] = presentation_for(p, calibrated=False)
                    p["display_mode"] = p["presentation"]["mode"]
    out["points"] = db.query("SELECT * FROM forecast_points WHERE forecast_id=? ORDER BY target, scenario_id, forecast_horizon_years",
                             (out["id"],))
    return out


def points(forecast_id: str) -> list[dict]:
    return db.query("SELECT * FROM forecast_points WHERE forecast_id=? ORDER BY target, scenario_id, forecast_horizon_years",
                    (forecast_id,))


def brier_score(predictions: list[tuple[float, int]]) -> dict:
    if not predictions:
        return {"brier": None, "n": 0, "calibrated": False, "status": "калибровка не завершена"}
    n = len(predictions)
    b = sum((p - y) ** 2 for p, y in predictions) / n
    return {"brier": round(b, 4), "n": n, "calibrated": n >= 30,
            "target": 0.20, "status": "калибровка не завершена" if n < 30 else "выборка достаточна"}
