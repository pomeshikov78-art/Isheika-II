"""Снимки расчётов и воспроизводимость (ИД-12, ведомость v1.1).

Каждый аналитический результат обязан содержать: research_id, версию набора
документов, идентификатор и версию методики, версию модели и промпта (если
использовались), параметры, входной снимок, контрольные суммы, дату и автора.

Повторный расчёт на сохранённом снимке с той же версией методики обязан давать
идентичный результат. Изменение методики не переписывает исторический результат.
"""
from __future__ import annotations

import hashlib
import json

from ..contracts import iso_now, new_id
from ..storage import db


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                     default=str).encode("utf-8")).hexdigest()


def document_set_version(research_id: str) -> str:
    """Версия набора документов: состав логических документов и их вхождений."""
    rows = db.query("""SELECT id, content_hash, updated_at FROM research_documents
                       WHERE research_id=? ORDER BY id""", (research_id,))
    occ = db.one("SELECT COUNT(*) AS n FROM content_occurrences WHERE research_id=?", (research_id,))
    return _hash({"docs": rows, "occurrences": (occ or {}).get("n", 0)})[:32]


def model_versions(research_id: str) -> dict:
    rows = db.query("""SELECT DISTINCT m.model_id AS code, m.display_name AS name,
                              p.name AS provider, r.prompt_version
                       FROM ai_requests r
                       LEFT JOIN ai_models m ON m.id=r.model_id
                       LEFT JOIN ai_providers p ON p.id=r.provider_id
                       WHERE r.research_id=?""", (research_id,))
    return {"models": [{"code": r["code"], "provider": r["provider"], "version": r["prompt_version"]}
                       for r in rows if r["code"]]}


def prompt_versions(research_id: str) -> dict:
    rows = db.query("""SELECT DISTINCT agent_code, prompt_version FROM ai_requests
                       WHERE research_id=?""", (research_id,))
    return {r["agent_code"]: r["prompt_version"] for r in rows}


def capture(research_id: str, methodology: dict, inputs: dict, parameters: dict,
            *, assessed_by: str = "calculation_core") -> dict:
    """Поля снимка, добавляемые в каждую запись результата расчёта."""
    mv = model_versions(research_id)
    pv = prompt_versions(research_id)
    models = mv.get("models") or []
    return {
        "document_set_version": document_set_version(research_id),
        "methodology_id": methodology.get("id"),
        "methodology_version": f'{methodology.get("code")} {methodology.get("version")}',
        "model_id": models[0]["code"] if models else None,
        "model_version": (models[0]["provider"] or "") + "/" + (models[0]["code"] or "") if models else None,
        "prompt_version": json.dumps(pv, ensure_ascii=False) if pv else None,
        "input_snapshot": inputs,
        "parameters": parameters,
        "config_checksum": methodology.get("config_checksum"),
        "input_hash": _hash(inputs)[:32],
        "assessed_by": assessed_by,
    }


def output_hash(result: dict) -> str:
    return _hash(result)[:32]


def start_run(research_id: str, *, job_id: str | None = None, query_snapshot: dict | None = None,
              parameters: dict | None = None, initiated_by: str = "system") -> str:
    from . import methodologies as M
    rid = new_id("run-")
    db.insert("research_runs", {
        "id": rid, "research_id": research_id, "job_id": job_id,
        "document_set_version": document_set_version(research_id),
        "query_snapshot": query_snapshot or {},
        "search_strategy_version": "SEARCH_V1",
        "methodology_versions": {m["family"]: m["code"] + " " + m["version"]
                                 for m in (M.active(f) for f in
                                           ("RELEVANCE", "FEASIBILITY", "TRL_CRITERIA", "FORECAST",
                                            "SOURCE_QUALITY", "EVIDENCE_QUALITY"))},
        "model_versions": model_versions(research_id),
        "prompt_versions": prompt_versions(research_id),
        "parameters": parameters or {}, "input_checksum": None, "output_checksum": None,
        "started_at": iso_now(), "finished_at": None, "initiated_by": initiated_by,
        "status": "running"})
    return rid


def finish_run(run_id: str, *, status: str = "completed", output: dict | None = None) -> None:
    db.update("research_runs", "id", run_id, {
        "finished_at": iso_now(), "status": status,
        "output_checksum": _hash(output or {})[:32]})


def runs(research_id: str) -> list[dict]:
    return [db.dec(r, "query_snapshot", "methodology_versions", "model_versions",
                   "prompt_versions", "parameters")
            for r in db.query("SELECT * FROM research_runs WHERE research_id=? ORDER BY started_at DESC",
                              (research_id,))]


ASSESSMENT_TABLES = {
    "trl": ("analytics_trl", ("criteria", "gaps", "input_snapshot", "parameters")),
    "feasibility": ("analytics_feasibility", ("factors", "weights", "sensitivity", "unknown_factors",
                                              "input_snapshot", "parameters")),
    "forecast": ("forecast_runs", ("horizons", "scenarios", "assumptions", "intervals",
                                   "input_snapshot", "parameters")),
    "confidence": ("analytics_confidence", ("basis", "limitations", "input_snapshot", "parameters")),
}


def assessment(kind: str, assessment_id: str) -> dict | None:
    """Запись расчёта в каноническом виде (те же ключи, что и результат compute).

    Хранилище разворачивает интервал в две колонки (range_low/range_high);
    при чтении они собираются обратно в `range`, иначе сравнение исходного
    и повторного результата (ИД-12) давало бы ложное расхождение.
    """
    table, jsons = ASSESSMENT_TABLES[kind]
    row = db.dec(db.one(f"SELECT * FROM {table} WHERE id=?", (assessment_id,)), *jsons)
    if row and kind == "feasibility":
        lo, hi = row.get("range_low"), row.get("range_high")
        row["range"] = [lo, hi] if lo is not None and hi is not None else None
    return row


def replay(kind: str, assessment_id: str) -> dict:
    """Повторный расчёт по сохранённому снимку и исходной версии методики.

    Возвращает исходный и повторный результаты и признак идентичности.
    Историческая запись не изменяется (ИД-09/ИД-12).
    """
    from . import feasibility as F, trl as T
    rec = assessment(kind, assessment_id)
    if not rec:
        return {"identical": False, "reason": "Запись не найдена"}
    meth_id = rec.get("methodology_id")
    inputs = rec.get("input_snapshot") or {}
    if kind == "feasibility":
        factors = inputs.get("factors") or rec.get("factors") or []
        again = F.compute(rec["research_id"], factors=[dict(f) for f in factors],
                          methodology_id=meth_id, store=False)
        keys = ("score", "coverage", "range")
    elif kind == "trl":
        again = T.compute(rec["research_id"], signals=inputs.get("signals"),
                          methodology_id=meth_id, store=False)
        keys = ("trl", "confidence")
    else:
        return {"identical": False, "reason": f"Повторный расчёт для {kind} не поддерживается"}
    before = {k: rec.get(k) for k in keys}
    after = {k: again.get(k) for k in keys}
    return {"kind": kind, "assessment_id": assessment_id, "methodology_id": meth_id,
            "original": before, "recomputed": after, "identical": before == after,
            "replayed_at": iso_now()}
