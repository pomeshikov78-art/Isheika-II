"""Испытания повторного обнаружения связей документов (ИД-33, ред. 1.5.3).

Основание — собственный живой прогон темы «технологии цифровых двойников в системах
связи»: каждый повторный прогон добавлял по копии связи «редакция/перевод»
(REVISION_OF 1 → 2 → 3 → 4 в сводке этапа, до 6 копий одной пары в базе),
граф связей и список связей документов двоелись.

RLN-01 — повторное обнаружение той же версии не добавляет вторую связь.
RLN-02 — подтверждение аналитика не понижается до алгоритма при повторе.
RLN-03 — сводка дедупликации считает связи по парам (исторические копии не в счёт).
RLN-04 — список связей и граф исследования не двоится.
"""
from __future__ import annotations

from isheika.api import service as S
from isheika.contracts import iso_now, new_id
from isheika.search import dedup as DD
from isheika.storage import db

from .base import BaseCase


def _legacy_relation(a: str, b: str, relation: str = "REVISION_OF",
                     at: str = "2026-11-01T00:00:00Z") -> str:
    """Копия связи, оставленная редакцией до исправления (≤ 1.5.2)."""
    rid = new_id("rel-")
    db.insert("content_relations", {
        "id": rid, "from_document_id": a, "to_document_id": b, "relation_type": relation,
        "confidence": 0.8, "basis": "прежняя запись", "decided_by": "algorithm", "created_at": at})
    return rid


class RelationRerunTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.rid = self.make_research("технологии цифровых двойников в системах связи")
        # документы глобальны: у каждого испытания своя пара (иначе испытания
        # делили бы одни и те же логические документы и их связи)
        tag = new_id("")[:8]
        self.a = self.add_doc(self.rid, f"Digital twin of a communication network {tag}: preprint",
                              abstract="Digital twin model of a wireless communication system.")
        self.b = self.add_doc(self.rid, f"Digital twin of a communication network {tag}: journal version",
                              abstract="Revised journal version of the digital twin communication study.")

    def test_RLN_01_repeated_detection_keeps_single_relation(self):
        """ИД-33: четыре прогона давали четыре копии связи REVISION_OF."""
        DD._ensure_cluster(self.a, self.b, "REVISION_OF", 0.8, "совпадение названия и DOI")
        first = db.count("content_relations", "from_document_id=? AND to_document_id=?", (self.a, self.b))
        self.assertEqual(first, 1)
        for _ in range(4):
            DD._ensure_cluster(self.a, self.b, "REVISION_OF", 0.85, "совпадение названия и DOI")
        self.assertEqual(db.count("content_relations", "from_document_id=? AND to_document_id=?",
                                  (self.a, self.b)), 1)
        row = db.one("SELECT * FROM content_relations WHERE from_document_id=? AND to_document_id=?",
                     (self.a, self.b))
        self.assertEqual(row["confidence"], 0.85, "повтор должен обновлять уверенность")
        # другой тип связи — самостоятельная сущность, он не теряется
        DD._ensure_cluster(self.a, self.b, "TRANSLATION_OF", 0.7, "перевод заголовка")
        self.assertEqual(db.count("content_relations", "from_document_id=? AND to_document_id=?",
                                  (self.a, self.b)), 2)

    def test_RLN_02_analyst_confirmation_is_not_downgraded(self):
        DD._ensure_cluster(self.a, self.b, "REVISION_OF", 0.8, "совпадение названия")
        DD.confirm_relation(self.a, self.b, "REVISION_OF", "analyst-1")
        row = db.one("SELECT * FROM content_relations WHERE from_document_id=? AND to_document_id=?",
                     (self.a, self.b))
        self.assertEqual(row["decided_by"], "analyst-1")
        DD._ensure_cluster(self.a, self.b, "REVISION_OF", 0.6, "алгоритм: совпадение названия")
        again = db.one("SELECT * FROM content_relations WHERE from_document_id=? AND to_document_id=?",
                       (self.a, self.b))
        self.assertEqual(again["decided_by"], "analyst-1")
        self.assertEqual(again["basis"], "подтверждено аналитиком")
        self.assertGreaterEqual(again["confidence"], 1.0)
        self.assertEqual(db.count("content_relations", "from_document_id=? AND to_document_id=?",
                                  (self.a, self.b)), 1)

    def test_RLN_03_summary_counts_pairs_not_rows(self):
        DD._ensure_cluster(self.a, self.b, "REVISION_OF", 0.8, "совпадение названия")
        before = DD.summary(self.rid)["relations"]
        self.assertEqual(before.get("REVISION_OF"), 1)
        DD._ensure_cluster(self.a, self.b, "REVISION_OF", 0.8, "совпадение названия")
        self.assertEqual(DD.summary(self.rid)["relations"], before)
        _legacy_relation(self.a, self.b)
        _legacy_relation(self.a, self.b)
        self.assertEqual(DD.summary(self.rid)["relations"].get("REVISION_OF"), 1)

    def test_RLN_04_relations_list_and_graph_do_not_double(self):
        DD._ensure_cluster(self.a, self.b, "REVISION_OF", 0.8, "совпадение названия")
        _legacy_relation(self.a, self.b)
        rels = S.document_relations(self.rid)
        self.assertEqual(len(rels), 1)
        graph = S.document_graph(self.rid)
        self.assertEqual(len(graph["edges"]), 1)
        self.assertEqual([t["count"] for t in graph["types"] if t["type"] == "REVISION_OF"], [1])
        self.assertEqual(len(graph["nodes"]), len({n["id"] for n in graph["nodes"]}))
