"""Единый реестр версионируемых методик (ИД-09, ведомость v1.1).

Каждая методика — самостоятельный объект с формулой, параметрами, порогами,
статусом утверждения, контрольной суммой конфигурации и контрольными примерами.

Правила:
  * изменение весов/порогов создаёт НОВУЮ версию (RELEVANCE_V1 → RELEVANCE_V2),
    старая запись не переписывается;
  * ранее рассчитанные результаты сохраняют ссылку на исходную версию;
  * пересчёт выполняется явной операцией и создаёт новую запись результата;
  * расчётное ядро берёт активную версию из реестра, а не из констант кода.
"""
from __future__ import annotations

import hashlib
import json
import re

from ..contracts import CoreError, iso_now, new_id
from ..registry.loader import methodology
from ..storage import db

_CACHE: dict[str, dict] = {}

FAMILIES = {
    "RELEVANCE": "Оценка релевантности документа запросу",
    "FEASIBILITY": "Интегральная оценка реализуемости",
    "TRL_CRITERIA": "Критерии уровней технологической готовности",
    "FORECAST": "Прогнозирование и политика представления",
    "SOURCE_QUALITY": "Качество источника",
    "EVIDENCE_QUALITY": "Качество доказательства",
}

# ИД-05: серверная политика представления прогнозов по горизонту.
PRESENTATION_POLICY = [
    {"from": 0, "to": 2, "mode": "EXACT", "precision": 2, "uncertainty": "LOW",
     "requires_calibration": True,
     "warning": "Численное значение допустимо только при подтверждённой калибровке методики."},
    {"from": 2, "to": 5, "mode": "INTERVAL", "precision": 2, "uncertainty": "MODERATE",
     "requires_calibration": False,
     "warning": "Значение приводится вместе с интервалом неопределённости."},
    {"from": 5, "to": 10, "mode": "INTERVAL", "precision": 2, "uncertainty": "HIGH",
     "requires_calibration": False,
     "warning": "Интервал неопределённости обязателен; точечное значение не является выводом."},
    {"from": 10, "to": 20, "mode": "COARSE", "precision": 0, "uncertainty": "VERY_HIGH",
     "requires_calibration": False,
     "warning": "Укрупнённая оценка с широкими интервалами и сценариями."},
    {"from": 20, "to": 35, "mode": "SCENARIO", "precision": 0, "uncertainty": "SCENARIO_ONLY",
     "requires_calibration": False,
     "warning": "Горизонт 20–35 лет: основной вывод — сценарии и диапазоны, точечный процент не выводится."},
    {"from": 35, "to": 50, "mode": "SCENARIO", "precision": 0, "uncertainty": "SCENARIO_ONLY",
     "requires_calibration": False,
     "warning": "Горизонт 35–50 лет: качественный сценарий; численная вероятность не является выводом."},
]


def family_of(code: str) -> str:
    return re.sub(r"_V\d+$", "", code.upper())


def checksum(formula: dict, parameters: dict, thresholds: dict) -> str:
    blob = json.dumps({"formula": formula, "parameters": parameters, "thresholds": thresholds},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def criterion_code(level: int, index: int) -> str:
    """Стабильный идентификатор критерия TRL<n>-C<nn> (ИД-08)."""
    return f"TRL{level}-C{index:02d}"


def _levels_with_codes(levels: list[dict]) -> list[dict]:
    out = []
    for lv in levels:
        crits = []
        for i, c in enumerate(lv["criteria"], 1):
            cc = dict(c)
            cc["legacy_id"] = c["id"]
            cc["id"] = criterion_code(lv["level"], i)
            cc["criterion_code"] = cc["id"]
            cc["is_mandatory"] = bool(c.get("required", True))
            crits.append(cc)
        out.append({**lv, "criteria": crits})
    return out


def _definitions() -> dict[str, dict]:
    m = methodology()
    rel = m["relevance"]
    fea = m["feasibility"]
    trl = m["trl"]
    fc = m["forecast"]
    return {
        "RELEVANCE_V1": {
            "name": FAMILIES["RELEVANCE"],
            "formula": {"expression": rel["formula"], "components": rel["components"],
                        "normalisation": "каждый фактор в [0;1], результат в [0;1]",
                        "normative_source": "ТЗ-03 §2 (ИД-01)"},
            "parameters": {"weights": rel["weights"],
                           "freshness_half_life_years": rel["freshness_half_life_years"],
                           "s_method": "lexical_semantic_approximation",
                           "metrics": rel["metrics"]},
            "thresholds": {"DIRECT": rel["thresholds"]["direct"], "ADJACENT": rel["thresholds"]["adjacent"],
                           "BELOW_THRESHOLD": 0.0},
            "examples": [{"name": "REL-02a", "score": 0.82, "expected_class": "DIRECT"},
                         {"name": "REL-02b", "score": 0.59, "expected_class": "BELOW_THRESHOLD"}],
        },
        "FEASIBILITY_V1": {
            "name": FAMILIES["FEASIBILITY"],
            "formula": {"expression": "F = 100 * sum(w_i*x_i*a_i) / sum(w_i*a_i)",
                        "coverage": "C = sum(w_i*a_i) / sum(w_i)",
                        "unknown_factor_policy": fea["unknown_factor_policy"],
                        "normative_source": "ТЗ-03 §5 (ИД-02)"},
            "parameters": {"factors": fea["factors"], "classes": fea["classes"],
                           "range_policy": fea["range_policy"], "sensitivity": fea["sensitivity"]},
            "thresholds": {"min_coverage_for_interpretation": 0.60,
                           "coverage_threshold_status": "PROVISIONAL",
                           "note": "Порог покрытия подлежит утверждению на контрольных примерах (открытый вопрос №1)"},
            "examples": [{"name": "FEAS-01", "factors": 9, "unknown": 4, "expected": "F по доступным, C<1"},
                         {"name": "FEAS-03", "factors": 9, "unknown": 9, "expected": "F=NULL, C=0"}],
        },
        "TRL_CRITERIA_V1": {
            "name": FAMILIES["TRL_CRITERIA"],
            "formula": {"expression": "TRL = max{L : все обязательные критерии L подтверждены}",
                        "aggregation": trl["aggregation"], "averaging_forbidden": True,
                        "normative_source": "ТЗ-03 §4 (ИД-08)"},
            "parameters": {"levels": _levels_with_codes(trl["levels"]),
                           "min_evidence_per_level": trl["min_evidence_per_level"],
                           "min_independent_groups": trl["min_independent_groups"]},
            "thresholds": {"min_level": 1, "max_level": 9},
            "examples": [{"name": "TRL-01", "case": "нет обязательного критерия TRL5",
                          "expected": "итоговый уровень < 5"}],
        },
        "FORECAST_V1": {
            "name": FAMILIES["FORECAST"],
            "formula": {"expression": "P(T<=t) = logistic(t; midpoint, steepness), монотонно не убывает",
                        "normative_source": "ТЗ-03 §7 (ИД-05, ИД-10)"},
            "parameters": {"horizons": fc["horizons"], "scenarios": fc["scenarios"], "targets": fc["targets"],
                           "presentation_policy": PRESENTATION_POLICY, "rules": fc["rules"]},
            "thresholds": {"false_precision_forbidden_above_years": 20,
                           "calibration_required_for_exact": True},
            "examples": [{"name": "FCST-01", "horizon_years": 40, "internal_value": 0.734821,
                          "expected_display_mode": "SCENARIO"}],
        },
        "SOURCE_QUALITY_V1": {
            "name": FAMILIES["SOURCE_QUALITY"],
            "formula": {"expression": "Q_source = base(class) * marker_factor",
                        "normative_source": "ТЗ-03 §3"},
            "parameters": {"class_quality": m["evidence_class_quality"],
                           "marker_factors": {"П": 1.0, "Р": 0.9, "Д": 0.75}},
            "thresholds": {"min_quality_for_primary": 0.5},
            "examples": [],
        },
        "EVIDENCE_QUALITY_V1": {
            "name": FAMILIES["EVIDENCE_QUALITY"],
            "formula": {"expression": "Q_ev = Q_source * completeness * independence_factor",
                        "independence": "повторные публикации одного сообщения — одна группа (ИД-11)",
                        "normative_source": "ТЗ-03 §3"},
            "parameters": {"rules": m.get("evidence_rules", {}),
                           "completeness": {"base": 0.6, "quote": 0.15, "locator": 0.15, "date": 0.1},
                           "origin_classes": ["PRIMARY", "INDEPENDENT_CONFIRMATION", "REPRINT",
                                              "SUMMARY", "DERIVATIVE", "CONTRADICTORY"]},
            "thresholds": {"independent_group_factor": 1.0, "derived_factor": 0.85},
            "examples": [{"name": "EVID-01", "case": "5 перепечаток одного пресс-релиза",
                          "expected": "1 группа независимости"}],
        },
    }


def bootstrap() -> int:
    """Идемпотентное наполнение реестра методик и справочника критериев TRL."""
    created = 0
    now = iso_now()
    for code, d in _definitions().items():
        if db.one("SELECT id FROM analytics_methodologies WHERE code=? AND version=?", (code, "1.0.0")):
            continue
        mid = new_id("mth-")
        db.insert("analytics_methodologies", {
            "id": mid, "code": code, "version": "1.0.0", "name": d["name"],
            "formula_definition": d["formula"], "parameters": d["parameters"], "thresholds": d["thresholds"],
            "valid_from": now, "valid_to": None, "approval_status": "PROVISIONAL", "is_active": 1,
            "author_user_id": "system", "approver_user_id": None,
            "config_checksum": checksum(d["formula"], d["parameters"], d["thresholds"]),
            "validation_examples": d["examples"],
            "change_description": "Стартовая методика редакции v1.1 (пороги PROVISIONAL, калибровка не завершена)",
            "previous_version_id": None, "created_at": now})
        created += 1
    # справочник критериев TRL
    trl = active("TRL_CRITERIA")
    for lv in trl["parameters"]["levels"]:
        for c in lv["criteria"]:
            db.upsert("analytics_trl_criteria", {
                "criterion_code": c["criterion_code"], "trl_level": lv["level"],
                "is_mandatory": 1 if c["is_mandatory"] else 0, "description": c["text"],
                "evidence_classes": c.get("evidence_classes") or [], "legacy_code": c.get("legacy_id"),
                "methodology_id": trl["id"], "created_at": now}, key="criterion_code")
    _CACHE.clear()
    return created


def _row_to_dict(row: dict) -> dict:
    r = db.dec(row, "formula_definition", "parameters", "thresholds", "validation_examples")
    r["family"] = family_of(r["code"])
    return r


def active(code_or_family: str) -> dict:
    """Активная версия методики семейства (RELEVANCE / RELEVANCE_V1 / RELEVANCE_V2)."""
    fam = family_of(code_or_family)
    if fam in _CACHE:
        return _CACHE[fam]
    row = db.one("""SELECT * FROM analytics_methodologies
                    WHERE code LIKE ? AND is_active=1 ORDER BY created_at DESC LIMIT 1""", (fam + "_V%",))
    if row is None:
        bootstrap()
        row = db.one("""SELECT * FROM analytics_methodologies
                        WHERE code LIKE ? AND is_active=1 ORDER BY created_at DESC LIMIT 1""", (fam + "_V%",))
    if row is None:
        raise CoreError("E_NOT_FOUND", f"Методика {code_or_family} отсутствует в реестре")
    d = _row_to_dict(row)
    _CACHE[fam] = d
    return d


def by_id(methodology_id: str) -> dict | None:
    row = db.one("SELECT * FROM analytics_methodologies WHERE id=?", (methodology_id,))
    return _row_to_dict(row) if row else None


def by_code(code: str, version: str | None = None) -> dict | None:
    if version:
        row = db.one("SELECT * FROM analytics_methodologies WHERE code=? AND version=?", (code, version))
    else:
        row = db.one("SELECT * FROM analytics_methodologies WHERE code=? ORDER BY created_at DESC", (code,))
    return _row_to_dict(row) if row else None


def listing() -> list[dict]:
    return [_row_to_dict(r) for r in db.query(
        "SELECT * FROM analytics_methodologies ORDER BY code, created_at")]


def history(code_or_family: str) -> list[dict]:
    fam = family_of(code_or_family)
    return [_row_to_dict(r) for r in db.query(
        "SELECT * FROM analytics_methodologies WHERE code LIKE ? ORDER BY created_at", (fam + "_V%",))]


def used_in_research(research_id: str) -> dict:
    """Методики, ФАКТИЧЕСКИ применённые в исследовании (ИД-09/ИД-12).

    Отчёт и API обязаны показывать версию, связанную с сохранённым результатом,
    а не текущую активную и не значения seed-файла: после выпуска новой версии
    методики исторический результат остаётся привязан к прежней.
    Возвращает словарь по семействам; `source` = result | active.
    """
    probes = {
        "RELEVANCE": ("SELECT methodology_id FROM search_results WHERE research_id=? "
                      "AND methodology_id IS NOT NULL ORDER BY created_at DESC LIMIT 1"),
        "TRL_CRITERIA": ("SELECT methodology_id FROM analytics_trl WHERE research_id=? "
                         "ORDER BY created_at DESC LIMIT 1"),
        "FEASIBILITY": ("SELECT methodology_id FROM analytics_feasibility WHERE research_id=? "
                        "ORDER BY created_at DESC LIMIT 1"),
        "FORECAST": ("SELECT methodology_id FROM forecast_runs WHERE research_id=? "
                     "ORDER BY created_at DESC LIMIT 1"),
        "EVIDENCE_QUALITY": ("SELECT methodology_id FROM analytics_confidence WHERE research_id=? "
                             "ORDER BY created_at DESC LIMIT 1"),
        # метрики качества поиска не привязаны к отдельной записи методики —
        # используется активная версия SOURCE_QUALITY
        "SOURCE_QUALITY": None,
    }
    out = {}
    for fam, sql in probes.items():
        row = db.one(sql, (research_id,)) if sql else None
        m = by_id(row["methodology_id"]) if row and row.get("methodology_id") else None
        out[fam] = {**(m or active(fam)), "source": "result" if m else "active"}
    return out


def create_version(code_or_family: str, *, parameters: dict | None = None,
                   thresholds: dict | None = None, formula: dict | None = None,
                   author: str = "system", approver: str | None = None,
                   description: str = "", activate: bool = True,
                   approval_status: str = "PROVISIONAL") -> dict:
    """Новая версия методики. Старая версия и связанные с ней результаты не меняются."""
    cur = active(code_or_family)
    fam = cur["family"]
    nums = [int(m.group(1)) for m in (re.search(r"_V(\d+)$", r["code"]) for r in history(fam)) if m]
    next_n = max(nums or [1]) + 1
    code = f"{fam}_V{next_n}"
    params = {**cur["parameters"], **(parameters or {})}
    ths = {**cur["thresholds"], **(thresholds or {})}
    frm = {**cur["formula_definition"], **(formula or {})}
    now = iso_now()
    mid = new_id("mth-")
    db.insert("analytics_methodologies", {
        "id": mid, "code": code, "version": f"{next_n}.0.0", "name": cur["name"],
        "formula_definition": frm, "parameters": params, "thresholds": ths,
        "valid_from": now, "valid_to": None, "approval_status": approval_status,
        "is_active": 1 if activate else 0, "author_user_id": author, "approver_user_id": approver,
        "config_checksum": checksum(frm, params, ths), "validation_examples": cur["validation_examples"],
        "change_description": description or f"Изменение параметров методики {cur['code']}",
        "previous_version_id": cur["id"], "created_at": now})
    if activate:
        db.execute("UPDATE analytics_methodologies SET is_active=0, valid_to=? WHERE code LIKE ? AND id<>?",
                   (now, fam + "_V%", mid))
    _CACHE.pop(fam, None)
    return by_id(mid)


def set_approval(methodology_id: str, status: str, approver: str) -> dict:
    if status not in ("PROVISIONAL", "VALIDATED", "DEPRECATED"):
        raise CoreError("E_VALIDATION", f"Недопустимый статус утверждения: {status}")
    row = by_id(methodology_id)
    if not row:
        raise CoreError("E_NOT_FOUND", "Методика не найдена")
    db.update("analytics_methodologies", "id", methodology_id,
              {"approval_status": status, "approver_user_id": approver})
    _CACHE.clear()
    return by_id(methodology_id)


def presentation_policy(horizon_years: int, *, calibrated: bool = False) -> dict:
    """ИД-05: режим представления определяется сервером, а не браузером."""
    for p in PRESENTATION_POLICY:
        if p["from"] <= horizon_years < p["to"] or (p["to"] == 50 and horizon_years <= 50):
            mode = p["mode"]
            precision = p["precision"]
            warning = p["warning"]
            if mode == "EXACT" and not calibrated:
                mode, precision = "INTERVAL", 2
                warning = ("Калибровка не завершена: численное значение приводится только "
                           "с интервалом неопределённости.")
            return {"mode": mode, "precision": precision, "uncertainty_class": p["uncertainty"],
                    "warning_text": warning, "horizon_years": horizon_years,
                    "calibrated": bool(calibrated)}
    return {"mode": "SCENARIO", "precision": 0, "uncertainty_class": "SCENARIO_ONLY",
            "warning_text": "Горизонт вне нормативной шкалы: только сценарная оценка.",
            "horizon_years": horizon_years, "calibrated": bool(calibrated)}
