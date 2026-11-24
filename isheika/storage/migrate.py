"""Миграции схемы данных (ведомость корректирующих изменений v1.1).

0002_tz_v11 — переход с редакции 1.0 на 1.1:
  * ИД-03: content_documents разделяется на blobs / documents / occurrences / clusters;
  * ИД-06: статус обработки (extraction_status) отделяется от класса релевантности;
  * ИД-07: классы приводятся к DIRECT / ADJACENT / BELOW_THRESHOLD;
  * ИД-02: F допускает NULL, добавляются покрытие и предупреждения;
  * ИД-05/08/09/10/11/12: новые таблицы методик, критериев TRL, уверенности,
    групп независимости, точек прогноза и снимков воспроизводимости.

Исходные таблицы не удаляются: они переименовываются в *_v10 и остаются
доступны для аудита и отката. Данные переносятся без потери происхождения.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlparse

from ..contracts import iso_now, new_id

CLASS_MAP = {"direct": "DIRECT", "adjacent": "ADJACENT", "contextual": "BELOW_THRESHOLD",
             "excluded": "BELOW_THRESHOLD"}
EXTRACTION_MAP = {
    "discovered": "DISCOVERED", "queued": "DISCOVERED", "fetching": "DISCOVERED",
    "fetched": "FETCHED", "extracting": "FETCHED", "extracted": "EXTRACTED",
    "normalizing": "EXTRACTED", "normalized": "NORMALIZED", "deduplication": "NORMALIZED",
    "unique": "NORMALIZED", "duplicate": "NORMALIZED", "relevance_check": "NORMALIZED",
    "direct": "NORMALIZED", "adjacent": "NORMALIZED", "excluded": "NORMALIZED",
    "failed": "FAILED", "unsupported": "UNSUPPORTED",
}
ORIGIN_BY_CLASS = {"primary_peer_reviewed": "PRIMARY", "primary_report": "PRIMARY",
                   "dataset": "PRIMARY", "official_register": "PRIMARY", "standard": "PRIMARY",
                   "patent": "PRIMARY", "preprint": "PRIMARY",
                   "press_release": "PRIMARY", "media": "REPRINT", "forum": "SUMMARY",
                   "encyclopedia": "SUMMARY", "unknown": "DERIVATIVE"}

RENAMES = ["content_documents", "content_relevance", "analytics_feasibility",
           "analytics_trl", "forecast_runs", "evidence_items"]


def _tables(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _cols(conn, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def is_legacy(conn) -> bool:
    t = _tables(conn)
    return "content_documents" in t and "state" in _cols(conn, "content_documents")


def _canon_url(url: str) -> str:
    try:
        p = urlparse((url or "").strip())
        host = (p.netloc or "").lower().replace("www.", "")
        return f"https://{host}{re.sub(r'/+$', '', p.path or '')}"
    except Exception:
        return url or ""


def _logical_key(row: dict) -> str:
    doi = (row.get("doi") or "").lower().strip()
    if doi:
        return "doi:" + doi
    if row.get("content_hash"):
        return "hash:" + row["content_hash"]
    if row.get("external_id"):
        return f"ext:{row.get('source_code')}:{row['external_id']}"
    return "url:" + _canon_url(row.get("url") or "")


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _j(v, default):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return default
    return v if v is not None else default


def migrate_0002(conn) -> dict:
    """Перенос данных редакции 1.0 в модель v1.1. Идемпотентна."""
    if not is_legacy(conn):
        return {"skipped": True}
    stats = {"documents": 0, "logical_documents": 0, "occurrences": 0, "blobs": 0,
             "search_results": 0, "feasibility": 0, "trl": 0, "forecasts": 0, "evidence": 0,
             "clusters": 0}
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    for t in RENAMES:
        if t in _tables(conn):
            conn.execute(f"ALTER TABLE {t} RENAME TO {t}_v10")
    with open(__file__.replace("migrate.py", "schema.sql"), encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.execute("PRAGMA legacy_alter_table = OFF")

    now = iso_now()
    legacy_docs = [dict(r) for r in conn.execute("SELECT * FROM content_documents_v10 ORDER BY created_at")]
    by_key: dict[str, str] = {}
    id_map: dict[str, str] = {}
    blobs: dict[str, str] = {}
    hosts: dict[str, set] = {}

    for row in legacy_docs:
        key = _logical_key(row)
        text = " | ".join([row.get("title") or "", row.get("abstract") or "", row.get("text_excerpt") or ""])
        sha = _sha(text)
        blob_id = blobs.get(sha)
        if not blob_id:
            blob_id = new_id("blb-")
            blobs[sha] = blob_id
            conn.execute("""INSERT OR IGNORE INTO content_blobs
                            (id, content_sha256, hash_algorithm, size_bytes, format, text_ref, created_at)
                            VALUES (?,?,?,?,?,?,?)""",
                         (blob_id, sha, "sha256", len(text.encode("utf-8")), "text/plain",
                          row.get("raw_ref"), now))
            stats["blobs"] += 1
        doc_id = by_key.get(key)
        if not doc_id:
            doc_id = row["id"]
            by_key[key] = doc_id
            conn.execute("""INSERT INTO content_documents
                (id, logical_key, blob_id, title, normalized_title, doc_type, authors, organizations,
                 country_code, language, published_at, publication_year, abstract, text_excerpt,
                 license, oa_status, doi, external_id, identifiers, content_hash, simhash,
                 extraction_status, deduplication_status, evidence_class, independence_group,
                 origin_class, marker, first_research_id, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (doc_id, key, blob_id, row["title"],
                          re.sub(r"\W+", " ", (row["title"] or "").lower()).strip(),
                          row["doc_type"], row["authors"], row["organizations"], row["country_code"],
                          row["language"], row["published_at"], row["publication_year"], row["abstract"],
                          row["text_excerpt"], row["license"], row["oa_status"], row["doi"],
                          row["external_id"], row["identifiers"], row["content_hash"], row["simhash"],
                          EXTRACTION_MAP.get(row["state"], "NORMALIZED"),
                          "DUPLICATE" if row.get("duplicate_of") else "UNIQUE",
                          row["evidence_class"], row["independence_group"],
                          ORIGIN_BY_CLASS.get(row["evidence_class"], "PRIMARY"),
                          row["marker"], row["research_id"], row["created_at"], row["updated_at"]))
            stats["logical_documents"] += 1
        id_map[row["id"]] = doc_id
        hosts.setdefault(doc_id, set()).add(urlparse(row.get("url") or "").netloc.lower())
        cu = _canon_url(row.get("url") or "")
        exists = conn.execute("""SELECT id FROM content_occurrences
                                 WHERE research_id=? AND source_code=? AND canonical_url=?""",
                              (row["research_id"], row["source_code"], cu)).fetchone()
        if not exists:
            conn.execute("""INSERT INTO content_occurrences
                (id, document_id, research_id, source_code, connector_code, url, canonical_url,
                 accessed_at, fetch_http_status, raw_ref, blob_id, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (new_id("occ-"), doc_id, row["research_id"], row["source_code"],
                          row["connector_code"], row["url"], cu, row["accessed_at"],
                          row["fetch_http_status"], row["raw_ref"], blob_id, row["created_at"]))
            stats["occurrences"] += 1
        stats["documents"] += 1

    # связи «дубликат → канонический документ» и кластеры версий
    for row in legacy_docs:
        dup_of = row.get("duplicate_of")
        target = id_map.get(dup_of) if dup_of else None
        src = id_map.get(row["id"])
        if target and src and target != src:
            conn.execute("UPDATE content_documents SET duplicate_of_document_id=? WHERE id=?", (target, src))
            conn.execute("""INSERT INTO content_relations
                            (id, from_document_id, to_document_id, relation_type, confidence, basis,
                             decided_by, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                         (new_id("rel-"), src, target, "EXACT_DUPLICATE", 0.95,
                          "миграция v1.0→v1.1", "migration", now))
    for doc_id, hs in hosts.items():
        if len(hs) < 2:
            continue
        ck = "host-group:" + doc_id
        cid = new_id("cls-")
        conn.execute("""INSERT OR IGNORE INTO content_clusters
                        (id, cluster_key, title, cluster_type, primary_document_id, created_at)
                        VALUES (?,?,?,?,?,?)""",
                     (cid, ck, "Разные размещения одного материала", "ALTERNATIVE_HOSTING", doc_id, now))
        got = conn.execute("SELECT id FROM content_clusters WHERE cluster_key=?", (ck,)).fetchone()[0]
        conn.execute("""INSERT OR IGNORE INTO content_cluster_members
                        (cluster_id, document_id, relation, role, confidence, decided_by, created_at)
                        VALUES (?,?,?,?,?,?,?)""",
                     (got, doc_id, "ALTERNATIVE_HOSTING", "primary", 0.9, "migration", now))
        conn.execute("UPDATE content_documents SET cluster_id=? WHERE id=?", (got, doc_id))
        stats["clusters"] += 1

    # --- результаты оценки → search_results
    if "content_relevance_v10" in _tables(conn):
        for r in conn.execute("SELECT * FROM content_relevance_v10"):
            r = dict(r)
            comp = _j(r.get("components"), {})
            cls = CLASS_MAP.get(r["class"], "BELOW_THRESHOLD")
            did = id_map.get(r["document_id"], r["document_id"])
            conn.execute("""INSERT INTO search_results
                (id, research_id, document_id, relevance_score, relevance_class, decision,
                 score_s, score_t, score_c, score_e, score_k, score_f, components, weights, gate,
                 reason, reason_codes, methodology_version, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (r["id"], r["research_id"], did, r["score"], cls,
                          "EXCLUDE" if cls == "BELOW_THRESHOLD" else "INCLUDE",
                          comp.get("S"), comp.get("T"), comp.get("C"), comp.get("E"),
                          comp.get("K"), comp.get("F"), r["components"], r["weights"], "{}",
                          r["reason"], json.dumps(["MIGRATED_V10"], ensure_ascii=False),
                          r["methodology_version"], r["created_at"]))
            stats["search_results"] += 1

    # --- реализуемость: F = NULL, если все факторы неизвестны (ИД-02)
    if "analytics_feasibility_v10" in _tables(conn):
        for r in conn.execute("SELECT * FROM analytics_feasibility_v10"):
            r = dict(r)
            factors = _j(r.get("factors"), [])
            known = [f for f in factors if f.get("x") is not None and f.get("assessment") != "unknown"]
            for f in factors:
                f["is_available"] = bool(f.get("x") is not None and f.get("assessment") != "unknown")
            score = r["score"] if known else None
            coverage = r["coverage"] or 0.0
            allowed = 1 if (score is not None and coverage >= 0.6) else 0
            warn = None if allowed else (
                "Недостаточное покрытие факторов: интерпретация итоговой оценки ограничена"
                if score is not None else "Все факторы неизвестны: итоговая оценка не рассчитывается")
            conn.execute("""INSERT INTO analytics_feasibility
                (id, research_id, technology_id, score, coverage, interpretation_allowed, coverage_warning,
                 unknown_factors, range_low, range_high, conservative, factors, weights, sensitivity,
                 interpretation, methodology_version, input_hash, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (r["id"], r["research_id"], r["technology_id"], score, coverage, allowed, warn,
                          json.dumps([f["code"] for f in factors if not f["is_available"]]),
                          r["range_low"], r["range_high"], r["conservative"], json.dumps(factors, ensure_ascii=False),
                          r["weights"], r["sensitivity"], r["interpretation"], r["methodology_version"],
                          r["input_hash"], r["created_at"]))
            stats["feasibility"] += 1

    if "analytics_trl_v10" in _tables(conn):
        for r in conn.execute("SELECT * FROM analytics_trl_v10"):
            r = dict(r)
            conn.execute("""INSERT INTO analytics_trl
                (id, research_id, technology_id, trl, criteria, gaps, confidence, methodology_version,
                 input_hash, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                         (r["id"], r["research_id"], r["technology_id"], r["trl"], r["criteria"],
                          r["gaps"], r["confidence"], r["methodology_version"], r["input_hash"], r["created_at"]))
            stats["trl"] += 1

    if "forecast_runs_v10" in _tables(conn):
        for r in conn.execute("SELECT * FROM forecast_runs_v10"):
            r = dict(r)
            conn.execute("""INSERT INTO forecast_runs
                (id, research_id, target, horizons, scenarios, method, assumptions, intervals,
                 monotonic_ok, methodology_version, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                         (r["id"], r["research_id"], r["target"], r["horizons"], r["scenarios"],
                          r["method"], r["assumptions"], r["intervals"], r["monotonic_ok"],
                          r["methodology_version"], r["created_at"]))
            stats["forecasts"] += 1

    if "evidence_items_v10" in _tables(conn):
        for r in conn.execute("SELECT * FROM evidence_items_v10"):
            r = dict(r)
            conn.execute("""INSERT INTO evidence_items
                (id, claim_id, document_id, research_id, source_code, url, locator, quote, published_at,
                 accessed_at, evidence_class, independence_group, origin_class, quality, status, marker,
                 archive_url, contradiction_of, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                         (r["id"], r["claim_id"], id_map.get(r["document_id"], r["document_id"]),
                          r["research_id"], r["source_code"], r["url"], r["locator"], r["quote"],
                          r["published_at"], r["accessed_at"], r["evidence_class"], r["independence_group"],
                          ORIGIN_BY_CLASS.get(r["evidence_class"], "PRIMARY"), r["quality"], r["status"],
                          r["marker"], r["archive_url"], r["contradiction_of"], r["created_at"]))
            stats["evidence"] += 1

    conn.execute("PRAGMA foreign_keys = ON")
    return stats


def migrate_0003_observability(conn) -> dict:
    """ROADMAP P6: трассировка запросов и длительности этапов.

    Колонки добавляются идемпотентно: свежая схема уже содержит их,
    ранее созданные базы получают их без пересоздания таблиц.
    """
    added = []
    plan = {
        "workflow_events": [("correlation_id", "TEXT"), ("request_id", "TEXT")],
        "audit_api_calls": [("correlation_id", "TEXT"), ("request_id", "TEXT")],
        "workflow_jobs": [("correlation_id", "TEXT"), ("duration_ms", "INTEGER")],
        "audit_log": [("correlation_id", "TEXT")],
    }
    for table, cols in plan.items():
        if table not in _tables(conn):
            continue
        have = _cols(conn, table)
        for name, decl in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
                added.append(f"{table}.{name}")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_events_correlation ON workflow_events(correlation_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_api_calls_correlation ON audit_api_calls(correlation_id)")
    return {"columns_added": added}


MIGRATIONS = [("0002_tz_v11", migrate_0002), ("0003_observability", migrate_0003_observability)]


def apply_all(conn) -> list[dict]:
    applied = {r[0] for r in conn.execute("SELECT version FROM meta_migrations")}
    out = []
    for version, fn in MIGRATIONS:
        if version in applied:
            continue
        res = fn(conn)
        conn.execute("INSERT OR IGNORE INTO meta_migrations(version, applied_at) VALUES (?,?)",
                     (version, iso_now()))
        out.append({"version": version, "result": res})
    return out
