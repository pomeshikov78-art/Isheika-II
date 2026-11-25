"""Менеджер поиска (ТЗ-05 §3.3, §4.4–4.6).

Отвечает за: выбор источников по профилю, создание поисковых заданий,
обращения к коннекторам, нормализацию, дедупликацию и сохранение документов.
Ошибка одного источника не останавливает исследование (частичные результаты).
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..config import SETTINGS
from ..contracts import CoreError, Document, iso_now, new_id
from ..storage import db
from ..workflow import events
from . import dedup as DD
from . import normalize as norm
from .connectors import build_connector, mark_source_status
from .expansion import Expansion, primary_expression
from .query_parser import ParsedQuery

# Какие категории источников обслуживаются реализованными коннекторами
CATEGORY_HINTS = {
    "C01": ["CON-OPENALEX", "CON-CROSSREF", "CON-DOAJ", "CON-EUROPEPMC", "CON-OPENAIRE", "CON-CORE", "CON-S2AG", "CON-ARXIV"],
    "C02": ["CON-EPO-OPS", "CON-USPTO-ODP", "CON-KIPRIS"],
    "C03": ["CON-HAL", "CON-CORE", "CON-OPENAIRE"],
    "C04": ["CON-DATACITE", "CON-ZENODO", "CON-OPENALEX"],
    "C05": ["CON-ROR", "CON-OPENALEX"],
    "C06": ["CON-OPENAIRE", "CON-DATACITE"],
    "C07": ["CON-GITHUB", "CON-ZENODO"],
    "C08": [],
    "C09": ["CON-STACKEXCHANGE"],
    "C10": [],
    "C11": ["CON-OSTI", "CON-NTRS"],
    "C12": ["CON-OSTI", "CON-NTRS"],
}

ACCESS_ORDER = {"A0": 0, "A1": 1, "A2": 2, "A4": 3, "UNKNOWN": 4, "A3": 5}


def select_connectors(profile: dict) -> list[dict]:
    """Отбор коннекторов по профилю исследования и политике доступа."""
    cats = profile.get("categories") or list(CATEGORY_HINTS.keys())
    wanted: list[str] = []
    for c in cats:
        wanted += CATEGORY_HINTS.get(c, [])
    if profile.get("connector_codes"):
        wanted = list(profile["connector_codes"])
    wanted = list(dict.fromkeys(wanted))
    access_max = profile.get("access_max", "A1")
    max_rank = ACCESS_ORDER.get(access_max, 1)
    rows = db.query("SELECT * FROM registry_connectors WHERE enabled=1")
    out = []
    for r in rows:
        r = db.dec(r, "capabilities", "limits", "quota_policy")
        if r["code"] not in wanted:
            continue
        if r["implementation"] in ("stub", "manual"):
            continue
        if r["paid"] and not SETTINGS.allow_paid_ai:
            continue
        src = db.one("SELECT access_class, evidence_marker, country_code FROM registry_sources WHERE code=?",
                     (r["source_code"],)) or {}
        rank = ACCESS_ORDER.get(src.get("access_class", "UNKNOWN"), 4)
        if rank > max_rank and r["requires_key"]:
            continue
        r["source_access_class"] = src.get("access_class")
        r["source_marker"] = src.get("evidence_marker")
        out.append(r)
    # free-first: сначала открытые без ключа, затем требующие ключ
    out.sort(key=lambda r: (1 if r["requires_key"] else 0, r["code"]))
    if profile.get("include_simulation"):
        sim = db.one("SELECT * FROM registry_connectors WHERE code='CON-SIM'")
        if sim:
            out.append(db.dec(sim, "capabilities", "limits", "quota_policy"))
    return out


def create_search_jobs(research_id: str, connectors: list[dict], ex: Expansion, q: ParsedQuery) -> list[dict]:
    jobs = []
    expr = primary_expression(ex, q)
    for c in connectors:
        jid = new_id("sj-")
        db.insert("search_jobs", {
            "id": jid, "research_id": research_id, "connector_code": c["code"],
            "source_code": c["source_code"], "branch": "core", "expression": expr,
            "status": "queued", "attempts": 0, "found_count": 0, "created_at": iso_now()})
        jobs.append(db.one("SELECT * FROM search_jobs WHERE id=?", (jid,)))
    return jobs


def _store_document(research_id: str, doc: Document, dedup=None, *,
                    search_job_id: str | None = None, branch: str | None = None,
                    expression: str | None = None) -> str:
    """Сохранение через четырёхуровневую модель дедупликации (ИД-03).

    Возвращает document_id нового логического документа либо "duplicate:<id>",
    если материал уже известен. Вхождение в источнике сохраняется в любом случае.
    """
    res = DD.store(research_id, doc, search_job_id=search_job_id, branch=branch, expression=expression)
    if not res["new_document"]:
        events.emit("document.duplicate", research_id=research_id,
                    payload={"document_id": res["document_id"], "occurrence_id": res["occurrence_id"],
                             "reason": res["match_basis"], "relation": res["relation"]})
        return "duplicate:" + res["document_id"]
    if res["relation"]:
        events.emit("document.clustered", research_id=research_id,
                    payload={"document_id": res["document_id"], "cluster_id": res["cluster_id"],
                             "relation": res["relation"]})
    return res["document_id"]


def run_search_job(job: dict, research_id: str, q: ParsedQuery, ex: Expansion,
                   dedup, profile: dict) -> dict:
    meta = db.one("SELECT * FROM registry_connectors WHERE code=?", (job["connector_code"],))
    meta = db.dec(meta, "capabilities", "limits", "quota_policy")
    conn = build_connector(meta)
    if conn is None:
        raise CoreError("E_POLICY", f'Коннектор {job["connector_code"]} не реализован')
    ok, reason = conn.available()
    if not ok:
        mark_source_status(meta["source_code"], "RESTRICTED")
        db.update("search_jobs", "id", job["id"],
                  {"status": "failed", "error_code": "E_POLICY", "error_message": reason,
                   "finished_at": iso_now()})
        events.emit("search.source_failed", research_id=research_id,
                    payload={"connector": meta["code"], "reason": reason, "code": "E_POLICY"}, severity="warning")
        return {"connector": meta["code"], "found": 0, "status": "restricted", "reason": reason}

    db.update("search_jobs", "id", job["id"], {"status": "running", "started_at": iso_now(),
                                              "attempts": job["attempts"] + 1})
    events.emit("search.source_started", research_id=research_id,
                payload={"connector": meta["code"], "source": meta["source_code"],
                         "expression": job["expression"]})
    limit = int(profile.get("max_docs_per_source") or SETTINGS.max_docs_per_source)
    try:
        docs = conn.search(job["expression"], limit=limit,
                           year_from=q.period_from, year_to=q.period_to,
                           languages=profile.get("languages"), research_id=research_id)
    except CoreError as e:
        db.update("search_jobs", "id", job["id"],
                  {"status": "failed", "error_code": e.error.code, "error_message": e.error.message,
                   "finished_at": iso_now()})
        mark_source_status(meta["source_code"], "UNAVAILABLE")
        events.emit("search.source_failed", research_id=research_id, severity="warning",
                    payload={"connector": meta["code"], **e.error.to_dict()})
        return {"connector": meta["code"], "found": 0, "status": "failed", "reason": e.error.message}

    stored, dups = 0, 0
    for d in docs:
        res = _store_document(research_id, d, dedup, search_job_id=job["id"],
                              branch=job.get("branch"), expression=job.get("expression"))
        if res.startswith("duplicate:"):
            dups += 1
        else:
            stored += 1
    db.update("search_jobs", "id", job["id"],
              {"status": "completed", "found_count": len(docs), "finished_at": iso_now()})
    mark_source_status(meta["source_code"], "CONNECTED", 200)
    db.execute("UPDATE registry_sources SET last_success_at=? WHERE code=?", (iso_now(), meta["source_code"]))
    db.execute("UPDATE registry_connectors SET health_status='active', last_checked_at=?, last_error=NULL WHERE code=?",
               (iso_now(), meta["code"]))
    events.emit("search.source_finished", research_id=research_id,
                payload={"connector": meta["code"], "found": len(docs), "stored": stored, "duplicates": dups})
    return {"connector": meta["code"], "found": len(docs), "stored": stored,
            "duplicates": dups, "status": "completed"}


def run_all(research_id: str, jobs: list[dict], q: ParsedQuery, ex: Expansion, profile: dict,
            progress_cb=None) -> dict:
    # ИД-03: идентичность документа глобальная (реестр content_documents),
    # поэтому предзагрузка «в рамках исследования» не требуется.
    dedup = None
    results = []
    done = 0
    max_workers = max(1, min(SETTINGS.max_parallel_fetch, len(jobs) or 1))
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run_search_job, j, research_id, q, ex, dedup, profile): j for j in jobs}
        for fut in as_completed(futures):
            j = futures[fut]
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001
                results.append({"connector": j["connector_code"], "found": 0, "status": "failed",
                                "reason": str(e)[:200]})
            done += 1
            if progress_cb:
                progress_cb(done, len(jobs), f"Обработано источников: {done}/{len(jobs)}")
    total_found = sum(r.get("found", 0) for r in results)
    ok = sum(1 for r in results if r["status"] == "completed")
    return {"sources_planned": len(jobs), "sources_ok": ok, "documents_found": total_found,
            "per_source": results,
            "_state": "completed" if ok == len(jobs) and ok else ("partial" if ok else "failed")}


def assess_documents(research_id: str, q: ParsedQuery, ex: Expansion, profile: dict,
                     progress_cb=None) -> dict:
    """Оценка соответствия запросу. Результат пишется в search_results (ИД-06).

    Статус обработки документа (extraction_status) не изменяется: класс
    релевантности — самостоятельная сущность, а не этап жизненного цикла.
    """
    from .relevance import assess, build_df
    rows = db.query("""SELECT * FROM research_documents
                       WHERE research_id=? AND extraction_status IN ('EXTRACTED','NORMALIZED')""",
                    (research_id,))
    docs = []
    for r in rows:
        r = db.dec(r, "authors", "organizations", "identifiers")
        d = Document(document_id=r["id"], source_code=r["source_code"], connector_code=r["connector_code"],
                     external_id=r["external_id"], title=r["title"], url=r["url"], doc_type=r["doc_type"],
                     authors=r["authors"], organizations=r["organizations"], country_iso2=r["country_code"],
                     language=r["language"], published_at=r["published_at"], abstract=r["abstract"] or "",
                     text_excerpt=r["text_excerpt"] or "", doi=r["doi"], identifiers=r["identifiers"],
                     evidence_class=r["evidence_class"], marker=r["marker"])
        docs.append(d)
    df, n = build_df(docs)
    counts = {"DIRECT": 0, "ADJACENT": 0, "BELOW_THRESHOLD": 0}
    created = updated = 0
    search_task = db.one("SELECT id FROM search_jobs WHERE research_id=? ORDER BY created_at LIMIT 1", (research_id,))
    for i, d in enumerate(docs, 1):
        res = assess(d, q, ex, required_types=profile.get("doc_types") or q.doc_types,
                     corpus_df=df, corpus_n=n)
        row = {
            "document_id": d.document_id, "research_id": research_id,
            "search_task_id": (search_task or {}).get("id"),
            "relevance_score": res.score, "relevance_class": res.cls, "decision": res.decision,
            "score_s": res.components["S"], "score_t": res.components["T"], "score_c": res.components["C"],
            "score_e": res.components["E"], "score_k": res.components["K"], "score_f": res.components["F"],
            "components": res.components, "weights": res.weights, "gate": res.gate,
            "reason": res.reason, "reason_codes": res.reason_codes or [],
            "methodology_id": res.methodology_id, "methodology_version": res.methodology_version,
            "input_hash": hashlib.sha256(json.dumps(
                {"doc": d.document_id, "q": q.raw, "m": res.methodology_id},
                sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:32],
            "created_at": iso_now()}
        # ИД-32: оценка — сущность пары «исследование × документ». Повторный прогон
        # пересчитывает её, а не добавляет вторую запись (иначе распределение классов
        # и список результатов удваивались). Решение аналитика не сбрасывается.
        prev = db.one("""SELECT id, decision, reason FROM search_results
                         WHERE research_id=? AND document_id=?
                         ORDER BY created_at DESC, rowid DESC LIMIT 1""",
                      (research_id, d.document_id))
        if prev:
            if prev["decision"] in ("MANUAL_INCLUDE", "MANUAL_EXCLUDE"):
                row["decision"] = prev["decision"]
                row["reason"] = prev["reason"] or res.reason
            db.update("search_results", "id", prev["id"], row)
            updated += 1
        else:
            db.insert("search_results", {"id": new_id("rel-"), **row})
            created += 1
        counts[res.cls] += 1
        if progress_cb and i % 10 == 0:
            progress_cb(i, len(docs), f"Оценено документов: {i}/{len(docs)}")
    events.emit("document.assessed", research_id=research_id, payload=counts)
    return {"assessed": len(docs), **counts, "created": created, "updated": updated}


def coverage_by_country(research_id: str) -> list[dict]:
    """Контроль покрытия К2: страна с нулём попадает в «Карту пробелов»."""
    rows = db.query("""SELECT d.country_code AS iso, c.name_ru AS name,
                              COUNT(*) AS documents,
                              SUM(CASE WHEN d.marker='П' THEN 1 ELSE 0 END) AS class_p
                       FROM research_documents d LEFT JOIN dict_countries c ON c.code=d.country_code
                       WHERE d.research_id=? AND d.relevance_class IN ('DIRECT','ADJACENT')
                         AND d.decision IN ('INCLUDE','MANUAL_INCLUDE')
                       GROUP BY d.country_code""", (research_id,))
    have = {r["iso"]: r for r in rows}
    out = []
    for c in db.query("SELECT code, name_ru FROM dict_countries WHERE is_enabled=1 ORDER BY name_ru"):
        r = have.get(c["code"])
        out.append({"iso2": c["code"], "name_ru": c["name_ru"],
                    "documents": r["documents"] if r else 0,
                    "class_P": (r["class_p"] or 0) if r else 0,
                    "gap": not bool(r)})
    return out
