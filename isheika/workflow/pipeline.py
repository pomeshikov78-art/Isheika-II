"""Обработчики 12 этапов информационно-вычислительного процесса (ТЗ-05 §4).

Модуль связывает поисковый контур, мульти-ИИ, доказательную модель, расчётное
ядро, прогноз и отчётность с графом выполнения. Ядро workflow остаётся
независимым от предметной логики.
"""
from __future__ import annotations

import hashlib
import json

from ..config import SETTINGS
from ..contracts import CoreError, iso_now, new_id
from ..storage import db
from ..analytics import barriers, confidence, evidence, feasibility, forecast, passport, quality, trends, trl
from ..analytics import snapshot as SNAP
from ..ai import agents as A, collective as C
from ..reports import builder as RB
from ..search import expansion as EX, manager as SM, query_parser as QP
from ..workflow import engine as W
from ..workflow import events


def _research(job: dict) -> dict:
    return db.dec(db.one("SELECT * FROM core_researches WHERE id=?", (job["research_id"],)),
                  "settings", "country_codes", "language_codes")


def _profile(research: dict) -> dict:
    s = research.get("settings") or {}
    p = db.dec(db.one("SELECT * FROM search_profiles WHERE research_id=? ORDER BY created_at DESC LIMIT 1",
                      (research["id"],)), "country_codes", "source_codes", "categories", "languages", "settings")
    prof = {"categories": (p or {}).get("categories") or s.get("categories"),
            "languages": (p or {}).get("languages") or research.get("language_codes") or ["ru", "en"],
            "access_max": (p or {}).get("access_max") or s.get("access_max", "A1"),
            "connector_codes": s.get("connector_codes"),
            "include_simulation": s.get("include_simulation", SETTINGS.profile == "DEV"),
            "max_docs_per_source": s.get("max_docs_per_source", SETTINGS.max_docs_per_source),
            "doc_types": s.get("doc_types")}
    return prof


@W.stage_handler("task_setup")
def stage_task_setup(job: dict, ctx: dict) -> dict:
    r = _research(job)
    qrow = db.one("SELECT * FROM search_queries WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (r["id"],))
    if not qrow:
        raise CoreError("E_VALIDATION", "Отсутствует поисковый запрос исследования")
    q = QP.parse(qrow["raw_text"])
    if r.get("period_from"):
        q.period_from = r["period_from"]
    if r.get("period_to"):
        q.period_to = r["period_to"]
    if r.get("country_codes"):
        q.countries = list(dict.fromkeys(q.countries + r["country_codes"]))
    db.update("search_queries", "id", qrow["id"], {"parsed": q.to_dict()})
    snapshot = {"research": {k: r[k] for k in ("id", "title", "goal", "period_from", "period_to",
                                               "country_codes", "language_codes", "settings")},
                "query": q.to_dict(), "methodology": SETTINGS.methodology_version}
    h = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32]
    db.update("core_researches", "id", r["id"], {"snapshot_hash": h, "updated_at": iso_now()})
    ctx["run_id"] = SNAP.start_run(r["id"], job_id=job["id"], query_snapshot=q.to_dict(),
                                   parameters={"profile": SETTINGS.profile},
                                   initiated_by=r.get("created_by") or "system")
    ctx["parsed_query"] = q
    W.progress(job["id"], 1, 1, "Постановка задачи зафиксирована")
    return {"entities": q.entities, "purpose": q.purpose, "context": q.context,
            "period": [q.period_from, q.period_to], "snapshot_hash": h}


@W.stage_handler("search_model")
def stage_search_model(job: dict, ctx: dict) -> dict:
    r = _research(job)
    q: QP.ParsedQuery = ctx.get("parsed_query")
    if q is None:
        qrow = db.dec(db.one("SELECT * FROM search_queries WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (r["id"],)), "parsed")
        q = QP.ParsedQuery(**{k: v for k, v in qrow["parsed"].items() if k in QP.ParsedQuery.__dataclass_fields__})
    ex = EX.build(q, languages=r.get("language_codes") or ["ru", "en"])
    qrow = db.one("SELECT id FROM search_queries WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (r["id"],))
    db.update("search_queries", "id", qrow["id"],
              {"expansions": ex.to_dict(), "branches": [b.to_dict() for b in ex.branches],
               "exclusions": ex.exclusions})
    ctx["expansion"] = ex
    ctx["parsed_query"] = q
    W.progress(job["id"], 1, 1, "Поисковая модель построена")
    return {"branches": len(ex.branches), "core_terms": ex.core_terms[:8],
            "exclusions": ex.exclusions, "expression": EX.primary_expression(ex, q)}


@W.stage_handler("source_search")
def stage_source_search(job: dict, ctx: dict) -> dict:
    r = _research(job)
    prof = _profile(r)
    q = ctx["parsed_query"]
    ex = ctx["expansion"]
    conns = SM.select_connectors(prof)
    if not conns:
        raise CoreError("E_POLICY", "Нет доступных коннекторов по профилю исследования. "
                                    "Проверьте ключи, класс доступа и включённые категории.")
    jobs = SM.create_search_jobs(r["id"], conns, ex, q)
    W.progress(job["id"], 0, len(jobs), f"Запланировано источников: {len(jobs)}")
    res = SM.run_all(r["id"], jobs, q, ex, prof,
                     progress_cb=lambda p, t, m: W.progress(job["id"], p, t, m))
    ctx["search_profile"] = prof
    return res


@W.stage_handler("document_processing")
def stage_document_processing(job: dict, ctx: dict) -> dict:
    rid = job["research_id"]
    from ..search import dedup as DD
    total = db.count("research_documents", "research_id=?", (rid,))
    uniq = db.count("research_documents", "research_id=? AND deduplication_status='UNIQUE'", (rid,))
    dup = db.count("research_documents", "research_id=? AND deduplication_status IN ('DUPLICATE','CLUSTERED')", (rid,))
    langs = db.query("SELECT language, COUNT(*) AS n FROM research_documents WHERE research_id=? GROUP BY language", (rid,))
    dd = DD.summary(rid)
    W.progress(job["id"], total, total, "Нормализация и дедупликация выполнены в поисковом контуре")
    return {"documents_total": total, "unique": uniq, "duplicates": dup,
            "occurrences": dd["occurrences"], "clusters": dd["clusters"], "relations": dd["relations"],
            "languages": {r["language"] or "unknown": r["n"] for r in langs},
            "_state": "completed" if total else "partial"}


@W.stage_handler("relevance_filter")
def stage_relevance_filter(job: dict, ctx: dict) -> dict:
    rid = job["research_id"]
    prof = ctx.get("search_profile") or _profile(_research(job))
    res = SM.assess_documents(rid, ctx["parsed_query"], ctx["expansion"], prof,
                              progress_cb=lambda p, t, m: W.progress(job["id"], p, t, m))
    if not res["assessed"]:
        return {**res, "_state": "partial", "reason": "Нет документов для оценки"}
    return res


@W.stage_handler("ai_tasks")
def stage_ai_tasks(job: dict, ctx: dict) -> dict:
    rid = job["research_id"]
    res = A.run_agents(rid, progress_cb=lambda p, t, m: W.progress(job["id"], p, t, m))
    ctx["ai_results"] = res
    return res


@W.stage_handler("collective_analysis")
def stage_collective_analysis(job: dict, ctx: dict) -> dict:
    rid = job["research_id"]
    deep = bool((_research(job).get("settings") or {}).get("deep_collective"))
    res = C.run_collective(rid, deep=deep)
    W.progress(job["id"], 1, 1, "Коллективный анализ завершён")
    return res


@W.stage_handler("evidence_base")
def stage_evidence_base(job: dict, ctx: dict) -> dict:
    rid = job["research_id"]
    res = evidence.build_evidence(rid, progress_cb=lambda p, t, m: W.progress(job["id"], p, t, m))
    return res


@W.stage_handler("math_core")
def stage_math_core(job: dict, ctx: dict) -> dict:
    rid = job["research_id"]
    t = trl.compute(rid)
    W.progress(job["id"], 1, 3, "TRL рассчитан")
    f = feasibility.compute(rid)
    W.progress(job["id"], 2, 3, "Реализуемость рассчитана")
    b = barriers.compute(rid)
    a = None
    from ..analytics import alternatives as ALT
    a = ALT.compute(rid)
    pp = passport.build(rid)
    W.progress(job["id"], 3, 3, "Паспорт технологии сформирован")
    conf = confidence.compute_all(rid)
    ctx["trl"] = t
    ctx["feasibility"] = f
    ctx["confidence"] = conf
    return {"trl": t["trl"], "trl_confidence": t["confidence"], "feasibility": f["score"],
            "coverage": f["coverage"], "range": f["range"], "barriers": len(b["barriers"]),
            "alternatives": len(a["alternatives"]), "technology_id": pp["technology_id"],
            "interpretation_allowed": f["interpretation_allowed"],
            "confidence": {k: v["confidence"] for k, v in conf.items()},
            "independent_groups": {k: v["independent_groups"] for k, v in conf.items()}}


@W.stage_handler("forecast")
def stage_forecast(job: dict, ctx: dict) -> dict:
    rid = job["research_id"]
    tr = trends.compute(rid)
    fc = forecast.compute(rid, trends=tr)
    conf = confidence.compute(rid, "forecast", subject_id=fc["id"], coverage=0.5)
    W.progress(job["id"], 1, 1, "Прогноз построен")
    return {"targets": list(fc["scenarios"]), "monotonic_ok": fc["monotonic_ok"],
            "data_sufficient": fc["data_sufficient"], "growth_rate": tr.get("growth_rate"),
            "forecast_id": fc["id"], "calibration_status": fc["calibration_status"],
            "confidence": conf["confidence"]}


@W.stage_handler("quality_control")
def stage_quality_control(job: dict, ctx: dict) -> dict:
    rid = job["research_id"]
    q = quality.compute(rid)
    W.progress(job["id"], 1, 1, "Контроль качества выполнен")
    return {"integrity_ok": q["integrity_ok"], "distribution": q["distribution"],
            "calibration_status": q["calibration_status"],
            "checks": q["integrity_checks"]}


@W.stage_handler("report")
def stage_report(job: dict, ctx: dict) -> dict:
    rid = job["research_id"]
    res = RB.generate(rid)
    if ctx.get("run_id"):
        SNAP.finish_run(ctx["run_id"], status="completed", output=res)
    events.emit("report.ready", research_id=rid, payload={"report_id": res["report_id"],
                                                          "formats": list(res["files"])})
    W.progress(job["id"], 1, 1, "Отчёт сформирован")
    return {"report_id": res["report_id"], "formats": list(res["files"]),
            "warnings": res["warnings"], "_state": "completed" if res["status"] == "ready" else "partial"}
