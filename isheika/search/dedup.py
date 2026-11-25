"""Дедупликация и кластеризация документов (ИД-03, ведомость v1.1).

Четыре независимые сущности:
  * content_blobs        — физическое содержимое (уникальность по SHA-256);
  * content_documents    — логический документ (DOI / устойчивый ID / заголовок+авторы+дата);
  * content_occurrences  — каждое обнаружение в конкретном источнике и по URL;
  * content_clusters     — группы связанных версий, копий и производных материалов.

Алгоритм сопоставления (порядок нормативный):
  1. точное совпадение DOI или другого устойчивого идентификатора;
  2. нормализованный заголовок + авторы + дата;
  3. библиографические идентификаторы;
  4. текстовые хеши и контрольные фрагменты (simhash);
  5. семантическое сопоставление — только КАНДИДАТ, требует подтверждения;
  6. неоднозначность → статус REVIEW (ручное подтверждение).

Объединение не уничтожает сведения об источниках обнаружения: вхождения
сохраняются всегда, версии препринта/публикации остаются отдельными документами.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import unicodedata
from urllib.parse import urlparse

from ..contracts import Document, iso_now, new_id
from ..storage import db
from . import normalize as norm

SEMANTIC_CANDIDATE_HAMMING = 6      # шаг 5: только кандидат, не автоматическое объединение
TEXT_MATCH_HAMMING = 3              # шаг 4: текстовый отпечаток
RELATION_TYPES = ("EXACT_DUPLICATE", "ALTERNATIVE_HOSTING", "PREPRINT_OF", "PUBLISHED_VERSION_OF",
                  "REVISION_OF", "TRANSLATION_OF", "SUMMARY_OF", "CITES")
VERSION_RELATIONS = ("PREPRINT_OF", "PUBLISHED_VERSION_OF", "REVISION_OF", "TRANSLATION_OF")


def normalized_title(title: str) -> str:
    t = unicodedata.normalize("NFKC", title or "").lower()
    t = re.sub(r"[^a-zа-яё0-9]+", " ", t)
    return " ".join(t.split())


def _body_key(abstract: str | None, excerpt: str | None) -> str:
    """Нормализованный текст материала для проверки тождественности содержимого."""
    return " ".join(((abstract or "") + " " + (excerpt or "")).lower().split())


def _author_key(authors: list[str]) -> str:
    surnames = []
    for a in (authors or [])[:4]:
        parts = re.split(r"[\s,]+", (a or "").strip())
        if parts:
            surnames.append(re.sub(r"\W+", "", parts[-1].lower())[:20])
    return "|".join(sorted(s for s in surnames if s))


def logical_key(doc: Document) -> tuple[str, str]:
    """Ключ логической идентичности + основание решения."""
    doi = (doc.doi or "").lower().strip()
    if doi:
        return "doi:" + doi, "doi"
    ids = doc.identifiers or {}
    for k in ("isbn", "patent_number", "report_number", "arxiv_id", "pmid", "handle"):
        if ids.get(k):
            return f"{k}:{str(ids[k]).lower()}", k
    nt = normalized_title(doc.title)
    ak = _author_key(doc.authors)
    year = (doc.published_at or "")[:4]
    if nt and (ak or year):
        raw = f"{nt}|{ak}|{year}"
        return "ttl:" + hashlib.sha256(raw.encode()).hexdigest()[:32], "title_authors_date"
    if doc.external_id:
        return f"ext:{doc.source_code}:{doc.external_id}".lower(), "external_id"
    if doc.content_hash:
        return "hash:" + doc.content_hash, "content_hash"
    return "url:" + norm.normalize_url(doc.url), "url"


def version_key(doc: Document, base: str | None = None) -> str:
    """Ключ связанной версии (препринт/публикация/редакция) одного материала.

    Логические документы глобальны: повторное обнаружение той же версии в другом
    исследовании обязано находить существующий документ, а не создавать дубль.
    """
    base = base if base is not None else logical_key(doc)[0]
    suffix = hashlib.sha256(((doc.url or "") + (doc.published_at or "")).encode()).hexdigest()[:12]
    return base + "|" + suffix


def _insert_idempotent(table: str, data: dict, lookup_sql: str, params: tuple) -> tuple[str, bool]:
    """Вставка, устойчивая к гонке параллельных потоков поиска (ИД-20).

    Проверка «есть ли запись» и вставка не атомарны: две ветви одного источника
    обрабатывают один и тот же материал одновременно. Нарушение UNIQUE означает,
    что запись уже создана соседним потоком, — переиспользуем её, а не роняем
    весь источник в failed (что делало этап partial и тянуло пересчёт по ИД-17).
    """
    try:
        db.insert(table, data)
        return data["id"], True
    except sqlite3.IntegrityError:
        row = db.one(lookup_sql, params)
        if row is None:
            raise
        return row["id"], False


def blob_of(doc: Document) -> tuple[str, str]:
    """Физическое содержимое: SHA-256 текста представления документа."""
    text = "\n".join([doc.title or "", doc.abstract or "", doc.text_excerpt or ""])
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    row = db.one("SELECT id FROM content_blobs WHERE content_sha256=?", (sha,))
    if row:
        return row["id"], sha
    bid = new_id("blb-")
    bid, _ = _insert_idempotent("content_blobs", {
        "id": bid, "content_sha256": sha, "hash_algorithm": "sha256",
        "size_bytes": len(text.encode("utf-8")), "format": "text/plain",
        "text_ref": doc.raw_ref, "storage_ref": None, "created_at": iso_now()},
        "SELECT id FROM content_blobs WHERE content_sha256=?", (sha,))
    return bid, sha


def classify_relation(old: dict, doc: Document) -> tuple[str, float, str]:
    """Тип связи между уже сохранённым документом и новым материалом."""
    old_type = (old.get("doc_type") or "").lower()
    new_type = (doc.doc_type or "").lower()
    old_lang = (old.get("language") or "").lower()
    new_lang = (doc.language or "").lower()
    same_title = normalized_title(old.get("title") or "") == normalized_title(doc.title)
    if old_lang and new_lang and old_lang != new_lang and same_title:
        return "TRANSLATION_OF", 0.8, "разные языки при совпадении заголовка"
    if old_type == "preprint" and new_type in ("article", "journal-article", "proceedings-article"):
        return "PUBLISHED_VERSION_OF", 0.85, "препринт → опубликованная версия"
    if new_type == "preprint" and old_type in ("article", "journal-article", "proceedings-article"):
        return "PREPRINT_OF", 0.85, "опубликованная версия → препринт"
    if new_type in ("news", "press_release", "forum") and old_type not in ("news", "press_release", "forum"):
        return "SUMMARY_OF", 0.7, "новостной пересказ первичного материала"
    if same_title and (old.get("published_at") or "")[:10] != (doc.published_at or "")[:10]:
        return "REVISION_OF", 0.65, "иная дата редакции при совпадении заголовка"
    old_host = urlparse(old.get("url") or "").netloc.lower()
    new_host = urlparse(doc.url or "").netloc.lower()
    if old_host and new_host and old_host != new_host:
        return "ALTERNATIVE_HOSTING", 0.9, "то же содержимое на другом ресурсе"
    return "EXACT_DUPLICATE", 0.95, "совпадение идентификатора или текстового отпечатка"


def find_candidate(doc: Document) -> tuple[dict | None, str, float]:
    """Поиск существующего логического документа по нормативным шагам 1–5."""
    doi = (doc.doi or "").lower().strip()
    if doi:
        row = db.one("SELECT * FROM content_documents WHERE lower(doi)=?", (doi,))
        if row:
            return db.dec(row, "identifiers", "authors", "organizations"), "doi", 1.0
    key, basis = logical_key(doc)
    vrow = db.one("SELECT * FROM content_documents WHERE logical_key=?", (version_key(doc, key),))
    if vrow:
        return db.dec(vrow, "identifiers", "authors", "organizations"), "version_key", 0.99
    row = db.one("SELECT * FROM content_documents WHERE logical_key=?", (key,))
    if row:
        return db.dec(row, "identifiers", "authors", "organizations"), basis, 0.98
    nt = normalized_title(doc.title)
    if nt:
        row = db.one("""SELECT * FROM content_documents WHERE normalized_title=?
                        AND ifnull(publication_year,0)=ifnull(?,0) LIMIT 1""",
                     (nt, int((doc.published_at or "0")[:4]) if (doc.published_at or "")[:4].isdigit() else 0))
        if row:
            return db.dec(row, "identifiers", "authors", "organizations"), "title_year", 0.9
    if doc.content_hash:
        row = db.one("SELECT * FROM content_documents WHERE content_hash=?", (doc.content_hash,))
        if row:
            return db.dec(row, "identifiers", "authors", "organizations"), "content_hash", 0.9
    if doc.simhash:
        nt_doc = normalized_title(doc.title)
        body_doc = _body_key(doc.abstract, doc.text_excerpt)
        for r in db.query("SELECT * FROM content_documents WHERE simhash IS NOT NULL ORDER BY created_at DESC LIMIT 2000"):
            h = norm.hamming(r["simhash"], doc.simhash)
            if h > TEXT_MATCH_HAMMING:
                continue
            # Шаг 4 — ТЕКСТОВЫЙ ОТПЕЧАТОК. Simhash теряет короткие токены, поэтому
            # его совпадение само по себе не доказывает тождественность: требуется
            # совпадение нормализованного заголовка либо полного текста. Иначе
            # разные материалы об одном событии схлопывались бы в один документ;
            # их связь устанавливается группой независимости (ИД-11), а не дедупликацией.
            same_title = bool(nt_doc) and normalized_title(r["title"] or "") == nt_doc
            same_body = bool(body_doc) and h == 0 and _body_key(r.get("abstract"), r.get("text_excerpt")) == body_doc
            if same_title or same_body:
                return db.dec(r, "identifiers", "authors", "organizations"), "simhash", 0.85
    return None, "", 0.0


def semantic_candidates(doc: Document, limit: int = 5) -> list[dict]:
    """Шаг 5: кандидаты по близости отпечатка. Автоматически НЕ объединяются."""
    out = []
    if not doc.simhash:
        return out
    for r in db.query("SELECT id, title, simhash, doi FROM content_documents WHERE simhash IS NOT NULL LIMIT 2000"):
        h = norm.hamming(r["simhash"], doc.simhash)
        if 0 < h <= SEMANTIC_CANDIDATE_HAMMING and normalized_title(r["title"] or "") != normalized_title(doc.title):
            out.append({"document_id": r["id"], "title": r["title"], "hamming": h,
                        "status": "REVIEW", "note": "Требуется подтверждение аналитика"})
            if len(out) >= limit:
                break
    return out


def _ensure_cluster(doc_id: str, other_id: str, relation: str, confidence: float,
                    basis: str, *, decided_by: str = "algorithm") -> str:
    row = db.one("SELECT cluster_id FROM content_documents WHERE id=?", (other_id,))
    cid = (row or {}).get("cluster_id")
    if not cid:
        cid = new_id("cls-")
        title = db.one("SELECT title FROM content_documents WHERE id=?", (other_id,))["title"]
        db.insert("content_clusters", {
            "id": cid, "cluster_key": "cluster:" + other_id, "title": title[:200],
            "cluster_type": relation, "primary_document_id": other_id, "created_at": iso_now()})
        db.update("content_documents", "id", other_id, {"cluster_id": cid, "updated_at": iso_now()})
        db.upsert("content_cluster_members", {
            "cluster_id": cid, "document_id": other_id, "relation": "EXACT_DUPLICATE",
            "role": "primary", "confidence": 1.0, "decided_by": decided_by, "created_at": iso_now()},
            key=("cluster_id", "document_id"))
    db.upsert("content_cluster_members", {
        "cluster_id": cid, "document_id": doc_id, "relation": relation, "role": "member",
        "confidence": confidence, "decided_by": decided_by, "created_at": iso_now()},
        key=("cluster_id", "document_id"))
    db.update("content_documents", "id", doc_id, {"cluster_id": cid, "updated_at": iso_now()})
    db.insert("content_relations", {
        "id": new_id("rel-"), "from_document_id": doc_id, "to_document_id": other_id,
        "relation_type": relation, "confidence": confidence, "basis": basis,
        "decided_by": decided_by, "created_at": iso_now()})
    return cid


def store(research_id: str, doc: Document, *, search_job_id: str | None = None,
          branch: str | None = None, expression: str | None = None) -> dict:
    """Сохранение обнаружения: blob → логический документ → вхождение → связь.

    Возвращает сведения о дедупликации. Вхождение сохраняется ВСЕГДА, даже если
    логический документ уже существует: происхождение не теряется.
    """
    doc = norm.normalize(doc)
    blob_id, sha = blob_of(doc)
    key, basis = logical_key(doc)
    existing, match_basis, conf = find_candidate(doc)
    # ИД-25: вхождение проверяется ДО решения о статусе документа. Повторное
    # обнаружение того же URL тем же исследованием — не новый дубль: иначе
    # документ помечался дубликатом самого себя, и сводка этапа показывала
    # «уникальных 0, дублей 15» для собственного корпуса исследования.
    cu = norm.normalize_url(doc.url)
    occ = db.one("""SELECT id FROM content_occurrences
                    WHERE research_id=? AND source_code=? AND canonical_url=?""",
                 (research_id, doc.source_code, cu))
    now = iso_now()
    relation = None
    cluster_id = None
    is_new = existing is None

    if existing is None:
        doc_id = doc.document_id or new_id("doc-")
        doc_id, _inserted = _insert_idempotent("content_documents", {
            "id": doc_id, "logical_key": key, "blob_id": blob_id, "cluster_id": None,
            "title": doc.title, "normalized_title": normalized_title(doc.title),
            "doc_type": doc.doc_type, "authors": doc.authors, "organizations": doc.organizations,
            "country_code": doc.country_iso2, "language": doc.language, "published_at": doc.published_at,
            "publication_year": int(doc.published_at[:4]) if doc.published_at and doc.published_at[:4].isdigit() else None,
            "abstract": doc.abstract, "text_excerpt": doc.text_excerpt, "license": doc.license,
            "oa_status": doc.oa_status, "doi": doc.doi, "external_id": doc.external_id,
            "identifiers": doc.identifiers, "content_hash": doc.content_hash, "simhash": doc.simhash,
            "extraction_status": "NORMALIZED", "deduplication_status": "UNIQUE",
            "duplicate_of_document_id": None, "evidence_class": doc.evidence_class,
            "independence_group": doc.independence_group,
            "origin_class": origin_class_of(doc), "marker": doc.marker,
            "first_research_id": research_id, "created_at": now, "updated_at": now},
            "SELECT id FROM content_documents WHERE logical_key=?", (key,))
        dedup_status = "UNIQUE"
        if not _inserted:
            is_new = False
            dedup_status = "DUPLICATE"
            db.update("content_documents", "id", doc_id,
                      {"deduplication_status": "DUPLICATE", "updated_at": now})
    else:
        doc_id = existing["id"]
        old_view = db.one("""SELECT d.*, o.url FROM content_documents d
                             LEFT JOIN content_occurrences o ON o.document_id=d.id
                             WHERE d.id=? LIMIT 1""", (doc_id,))
        relation, rel_conf, rel_basis = classify_relation(old_view, doc)
        same_blob = old_view.get("blob_id") == blob_id
        # Точный дубль и альтернативное размещение НЕ создают новый логический
        # документ: добавляется только вхождение (происхождение сохраняется).
        # Связи версий (препринт/публикация/редакция/перевод) НЕ схлопываются
        # даже при одинаковом извлечённом тексте: это разные логические документы.
        version_relation = relation in VERSION_RELATIONS
        if relation in ("EXACT_DUPLICATE", "ALTERNATIVE_HOSTING") or (same_blob and not version_relation):
            if occ is None:
                dedup_status = "DUPLICATE"
                db.update("content_documents", "id", doc_id,
                          {"deduplication_status": "DUPLICATE", "updated_at": now})
            else:
                # то же самое вхождение: прежний статус документа сохраняется
                dedup_status = existing.get("deduplication_status") or "UNIQUE"
            cluster_id = db.one("SELECT cluster_id FROM content_documents WHERE id=?", (doc_id,))["cluster_id"]
            if relation == "ALTERNATIVE_HOSTING" and not cluster_id:
                cluster_id = new_id("cls-")
                cluster_id, _ = _insert_idempotent("content_clusters", {
                    "id": cluster_id, "cluster_key": "cluster:" + doc_id,
                    "title": (old_view.get("title") or "")[:200], "cluster_type": "ALTERNATIVE_HOSTING",
                    "primary_document_id": doc_id, "created_at": now},
                    "SELECT id FROM content_clusters WHERE cluster_key=?", ("cluster:" + doc_id,))
                db.upsert("content_cluster_members", {
                    "cluster_id": cluster_id, "document_id": doc_id, "relation": "ALTERNATIVE_HOSTING",
                    "role": "primary", "confidence": rel_conf, "decided_by": "algorithm",
                    "created_at": now}, key=("cluster_id", "document_id"))
                db.update("content_documents", "id", doc_id, {"cluster_id": cluster_id})
        else:
            # связанная версия: отдельный логический документ + связь + кластер
            doc_id = doc.document_id or new_id("doc-")
            doc_id, _inserted = _insert_idempotent("content_documents", {
                "id": doc_id, "logical_key": version_key(doc, key),
                "blob_id": blob_id, "cluster_id": None, "title": doc.title,
                "normalized_title": normalized_title(doc.title), "doc_type": doc.doc_type,
                "authors": doc.authors, "organizations": doc.organizations,
                "country_code": doc.country_iso2, "language": doc.language,
                "published_at": doc.published_at,
                "publication_year": int(doc.published_at[:4]) if doc.published_at and doc.published_at[:4].isdigit() else None,
                "abstract": doc.abstract, "text_excerpt": doc.text_excerpt, "license": doc.license,
                "oa_status": doc.oa_status, "doi": doc.doi, "external_id": doc.external_id,
                "identifiers": doc.identifiers, "content_hash": doc.content_hash, "simhash": doc.simhash,
                "extraction_status": "NORMALIZED", "deduplication_status": "CLUSTERED",
                "duplicate_of_document_id": existing["id"], "evidence_class": doc.evidence_class,
                "independence_group": doc.independence_group, "origin_class": origin_class_of(doc),
                "marker": doc.marker, "first_research_id": research_id,
                "created_at": now, "updated_at": now},
                "SELECT id FROM content_documents WHERE logical_key=?", (version_key(doc, key),))
            cluster_id = _ensure_cluster(doc_id, existing["id"], relation, rel_conf, rel_basis)
            dedup_status = "CLUSTERED"
            is_new = _inserted

    if occ:
        occ_id = occ["id"]
        db.update("content_occurrences", "id", occ_id,
                  {"accessed_at": doc.accessed_at, "fetch_http_status": 200, "blob_id": blob_id})
        new_occurrence = False
    else:
        occ_id = new_id("occ-")
        occ_id, new_occurrence = _insert_idempotent("content_occurrences", {
            "id": occ_id, "document_id": doc_id, "research_id": research_id,
            "source_code": doc.source_code, "connector_code": doc.connector_code,
            "search_job_id": search_job_id, "branch": branch, "expression": expression,
            "url": doc.url, "canonical_url": cu, "accessed_at": doc.accessed_at,
            "fetch_http_status": 200, "raw_ref": doc.raw_ref, "blob_id": blob_id, "created_at": now},
            """SELECT id FROM content_occurrences
               WHERE research_id=? AND source_code=? AND canonical_url=?""",
            (research_id, doc.source_code, cu))
        if not new_occurrence:
            db.update("content_occurrences", "id", occ_id,
                      {"accessed_at": doc.accessed_at, "fetch_http_status": 200, "blob_id": blob_id})
    return {"document_id": doc_id, "occurrence_id": occ_id, "new_document": is_new,
            "new_occurrence": new_occurrence, "deduplication_status": dedup_status,
            "relation": relation, "cluster_id": cluster_id, "match_basis": match_basis or basis,
            "content_sha256": sha, "candidates": semantic_candidates(doc) if is_new else []}


def origin_class_of(doc: Document) -> str:
    """Происхождение материала (ИД-11): первичный / перепечатка / пересказ."""
    ec = doc.evidence_class
    if ec in ("media",):
        return "REPRINT"
    if ec in ("forum", "encyclopedia"):
        return "SUMMARY"
    if ec == "unknown":
        return "DERIVATIVE"
    return "PRIMARY"


def confirm_relation(from_document_id: str, to_document_id: str, relation_type: str,
                     user_id: str) -> dict:
    """Ручное подтверждение связи (шаг 6) — при неоднозначности."""
    if relation_type not in RELATION_TYPES:
        raise ValueError(f"Неизвестный тип связи: {relation_type}")
    cid = _ensure_cluster(from_document_id, to_document_id, relation_type, 1.0,
                          "подтверждено аналитиком", decided_by=user_id)
    db.update("content_documents", "id", from_document_id,
              {"deduplication_status": "CLUSTERED", "updated_at": iso_now()})
    return {"cluster_id": cid, "relation": relation_type, "decided_by": user_id}


def summary(research_id: str) -> dict:
    docs = db.count("research_documents", "research_id=?", (research_id,))
    occ = db.count("content_occurrences", "research_id=?", (research_id,))
    clusters = db.one("""SELECT COUNT(DISTINCT d.cluster_id) AS n FROM research_documents d
                         WHERE d.research_id=? AND d.cluster_id IS NOT NULL""", (research_id,))
    rel = db.query("""SELECT relation_type, COUNT(*) AS n FROM content_relations r
                      JOIN content_occurrences o ON o.document_id=r.from_document_id
                      WHERE o.research_id=? GROUP BY relation_type""", (research_id,))
    return {"logical_documents": docs, "occurrences": occ,
            "merged": max(0, occ - docs), "clusters": (clusters or {}).get("n", 0),
            "relations": {r["relation_type"]: r["n"] for r in rel}}


def clusters(research_id: str) -> list[dict]:
    rows = db.query("""SELECT DISTINCT c.* FROM content_clusters c
                       JOIN content_cluster_members m ON m.cluster_id=c.id
                       JOIN content_occurrences o ON o.document_id=m.document_id
                       WHERE o.research_id=? ORDER BY c.created_at DESC LIMIT 200""", (research_id,))
    out = []
    for c in rows:
        members = db.query("""SELECT m.document_id, m.relation, m.role, m.confidence, m.decided_by,
                                     d.title, d.doc_type, d.published_at, d.doi
                              FROM content_cluster_members m JOIN content_documents d ON d.id=m.document_id
                              WHERE m.cluster_id=?""", (c["id"],))
        for m in members:
            m["occurrences"] = db.query("""SELECT source_code, url, accessed_at, research_id
                                           FROM content_occurrences WHERE document_id=?""", (m["document_id"],))
        out.append({**c, "members": members})
    return out
