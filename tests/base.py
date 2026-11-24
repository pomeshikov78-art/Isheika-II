"""Общая оснастка тестов: изолированная БД, посев реестров, фабрики объектов."""
from __future__ import annotations

import unittest

from isheika.config import SETTINGS
from isheika.contracts import Document, iso_now, new_id
from isheika.registry import loader
from isheika.storage import db

_SEEDED = False


def ensure_seed() -> None:
    global _SEEDED
    if not _SEEDED:
        SETTINGS.ensure_dirs()
        db.init_db()
        loader.seed_all()
        _SEEDED = True


class BaseCase(unittest.TestCase):
    def setUp(self) -> None:
        ensure_seed()

    # ---------------- фабрики
    def make_research(self, query: str = "тропосферная связь за горизонтом", **kw) -> str:
        from isheika.api import service as S
        body = {"query": query, "title": kw.pop("title", "Тестовое исследование"),
                "countries": kw.pop("countries", ["RU", "US", "CN"])}
        body.update(kw)
        return S.create_research(body, actor="tester")["id"]

    def add_doc(self, rid: str, title: str, *, abstract: str = "", doc_type: str = "article",
                evidence_class: str = "primary_peer_reviewed", group: str = "g1",
                extraction_status: str = "NORMALIZED", year: str = "2021", country: str = "RU",
                score: float = 0.9, cls: str = "DIRECT", url: str | None = None,
                doi: str | None = None, **kw) -> str:
        """Фабрика документа в модели v1.1: blob → логический документ → вхождение → оценка."""
        from isheika.search import dedup as DD
        from isheika.search import normalize as norm
        did = new_id("doc-")
        doc = Document(document_id=did, source_code=kw.get("source_code", "SRC-0451"),
                       connector_code="CON-TEST", external_id=kw.get("external_id", did),
                       title=title, url=url or ("https://example.org/" + did),
                       doc_type=doc_type, authors=kw.get("authors", ["Иванов И.И."]),
                       organizations=[kw.get("org", "НИИ Радио")], country_iso2=country,
                       language=kw.get("language", "ru"), published_at=f"{year}-05-01",
                       abstract=abstract or title, text_excerpt=kw.get("text", ""),
                       doi=doi, identifiers=kw.get("identifiers", {}),
                       evidence_class=evidence_class, marker=kw.get("marker", "П"))
        doc = norm.normalize(doc)
        res = DD.store(rid, doc)
        did = res["document_id"]
        db.update("content_documents", "id", did,
                  {"extraction_status": extraction_status, "independence_group": group,
                   "origin_class": kw.get("origin_class", "PRIMARY")})
        db.insert("search_results", {
            "id": new_id("rel-"), "document_id": did, "research_id": rid,
            "relevance_score": score, "relevance_class": cls,
            "decision": kw.get("decision", "EXCLUDE" if cls == "BELOW_THRESHOLD" else "INCLUDE"),
            "score_s": 0.9, "score_t": 0.9, "score_c": 0.8, "score_e": 0.9, "score_k": 0.8, "score_f": 0.7,
            "components": {"S": 0.9, "T": 0.9, "C": 0.8, "E": 0.9, "K": 0.8, "F": 0.7},
            "weights": {"S": 0.30, "T": 0.25, "C": 0.15, "E": 0.15, "K": 0.10, "F": 0.05},
            "reason": "тестовая оценка", "reason_codes": ["TEST"],
            "methodology_version": SETTINGS.methodology_version, "created_at": iso_now()})
        return did

    def add_claim(self, rid: str, text: str = "Тестовое утверждение", ctype: str = "FACT",
                  status: str = "UNVERIFIED", section: str = "A02") -> str:
        cid = new_id("clm-")
        db.insert("knowledge_claims", {
            "id": cid, "research_id": rid, "claim_text": text, "claim_type": ctype,
            "section": section, "status": status, "confidence": 0.5,
            "produced_by": "test", "created_at": iso_now()})
        return cid

    def add_evidence(self, rid: str, cid: str, did: str | None = None, **kw) -> str:
        eid = new_id("evd-")
        db.insert("evidence_items", {
            "id": eid, "claim_id": cid, "document_id": did, "research_id": rid,
            "source_code": "SRC-0451", "url": "https://example.org/x", "locator": "с. 1",
            "quote": kw.get("quote", "цитата из источника"), "published_at": "2021-05-01",
            "accessed_at": iso_now(), "evidence_class": kw.get("evidence_class", "primary_peer_reviewed"),
            "independence_group": kw.get("group", "g1"), "quality": kw.get("quality", 0.9),
            "status": kw.get("status", "SUPPORTED"), "marker": "П", "created_at": iso_now()})
        return eid

    def document(self, title: str, abstract: str = "", **kw) -> Document:
        return Document(document_id=new_id("doc-"), source_code="SRC-0451", connector_code="CON-TEST",
                        external_id="x", title=title, url="https://example.org/x",
                        abstract=abstract or title, **kw)
