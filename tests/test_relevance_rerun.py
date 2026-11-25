"""Испытания повторной оценки релевантности (ИД-32, ред. 1.5.3).

Основание — собственный живой прогон темы «технологии цифровых двойников в системах
связи» до исправления: два прогона подряд дали 134 записи оценки на 67 документов,
распределение классов в контроле качества выросло с 55/7/5 до 110/14/10,
а решение аналитика об исключении документа затиралось новой записью INCLUDE.

REL-01 — повторная оценка не добавляет вторую запись на документ.
REL-02 — распределение классов и метрики считаются по документам (исторические
         записи прежних версий не удваивают выборку).
REL-03 — ручное решение аналитика (MANUAL_EXCLUDE / MANUAL_INCLUDE) сохраняется.
REL-04 — список результатов исследования не двоится, в том числе на «старой» базе.
REL-05 — результат этапа различает созданные и пересчитанные оценки.
"""
from __future__ import annotations

from isheika.analytics import quality as Q
from isheika.api import service as S
from isheika.contracts import new_id
from isheika.search import expansion as EX, manager as SM, query_parser as QP
from isheika.storage import db

from .base import BaseCase

TOPIC = "технологии цифровых двойников в системах связи"


def _legacy_row(rid: str, did: str, score: float = 0.9, cls: str = "DIRECT",
                at: str = "2026-11-01T00:00:00Z") -> str:
    """Запись оценки, оставленная редакцией до исправления (≤ 1.5.2): дубль, старше текущей."""
    rid_row = new_id("rel-")
    db.insert("search_results", {
        "id": rid_row, "document_id": did, "research_id": rid,
        "relevance_score": score, "relevance_class": cls, "decision": "INCLUDE",
        "score_s": 0.9, "score_t": 0.9, "score_c": 0.8, "score_e": 0.9, "score_k": 0.8, "score_f": 0.7,
        "components": {"S": 0.9, "T": 0.9, "C": 0.8, "E": 0.9, "K": 0.8, "F": 0.7},
        "weights": {"S": 0.30, "T": 0.25, "C": 0.15, "E": 0.15, "K": 0.10, "F": 0.05},
        "reason": "прежняя оценка", "reason_codes": ["LEGACY"],
        "methodology_version": "REL-1.0.0", "created_at": at})
    return rid_row


class RelevanceRerunTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.q = QP.parse(TOPIC)
        self.ex = EX.build(self.q, languages=["ru", "en"])

    def _research_with_docs(self, n: int = 3) -> tuple[str, list[str]]:
        rid = self.make_research(TOPIC)
        topics = [
            ("Digital twin of a wireless communication network",
             "Digital twin model of a wireless communication system for link quality prediction."),
            ("Цифровой двойник радиоканала связи",
             "Цифровой двойник радиоканала связи применяется для прогноза качества обслуживания."),
            ("Digital shadow of an optical transport system",
             "A digital shadow of the optical transport network reproduces routing and load states."),
            ("Виртуальный прототип сети связи оператора",
             "Виртуальный прототип сети оператора связи воспроизводит нагрузки и отказы оборудования."),
            ("Digital twins for satellite communication payloads",
             "Digital twins of satellite communication payloads emulate beamforming and interference."),
        ]
        ids = []
        for i in range(n):
            title, abstract = topics[i % len(topics)]
            ids.append(self.add_doc(
                rid, title, abstract=abstract,
                language="ru" if i % 2 else "en", score=0.9, cls="DIRECT"))
        self.assertEqual(len(set(ids)), n, "документы склеились дедупликацией")
        return rid, ids

    def _assess(self, rid: str) -> dict:
        return SM.assess_documents(rid, self.q, self.ex, {})

    def test_REL_01_rerun_does_not_multiply_assessments(self):
        """ИД-32: два прогона давали 134 записи оценки на 67 документов."""
        rid, ids = self._research_with_docs(3)
        # фабрика уже создала по одной оценке: считаем от исходного числа
        base = db.count("search_results", "research_id=?", (rid,))
        self.assertEqual(base, len(ids))
        for _ in range(3):
            self._assess(rid)
        self.assertEqual(db.count("search_results", "research_id=?", (rid,)), len(ids))
        self.assertEqual(db.one("""SELECT COUNT(*) AS n FROM (SELECT DISTINCT document_id
                                   FROM search_results WHERE research_id=?)""", (rid,))["n"], len(ids))

    def test_REL_02_quality_distribution_counts_documents(self):
        """ИД-32: распределение 55/7/5 превращалось в 110/14/10 после повторного прогона."""
        rid, ids = self._research_with_docs(3)
        self._assess(rid)
        first = Q.compute(rid)["distribution"]
        self.assertEqual(sum(first[k] for k in ("DIRECT", "ADJACENT", "BELOW_THRESHOLD")), len(ids))
        self._assess(rid)
        second = Q.compute(rid)["distribution"]
        self.assertEqual(second, first)
        # записи, оставленные прежней редакцией, тоже не удваивают выборку
        for did in ids:
            _legacy_row(rid, did)
        third = Q.compute(rid)
        self.assertEqual(third["distribution"], first)
        self.assertEqual(sum(third["distribution"][k] for k in
                             ("DIRECT", "ADJACENT", "BELOW_THRESHOLD")), len(ids))

    def test_REL_03_manual_decision_survives_rerun(self):
        """ИД-32: повторный прогон затирал исключение документа аналитиком."""
        rid, ids = self._research_with_docs(2)
        self._assess(rid)
        S.exclude_document(ids[0], "не относится к теме", actor="analyst", research_id=rid)
        db.update("search_results", "id",
                  db.one("SELECT id FROM search_results WHERE research_id=? AND document_id=?",
                         (rid, ids[1]))["id"], {"decision": "MANUAL_INCLUDE"})
        self._assess(rid)
        rows = {r["document_id"]: r for r in
                db.query("SELECT * FROM search_results WHERE research_id=?", (rid,))}
        self.assertEqual(rows[ids[0]]["decision"], "MANUAL_EXCLUDE")
        self.assertIn("не относится к теме", rows[ids[0]]["reason"] or "")
        self.assertEqual(rows[ids[1]]["decision"], "MANUAL_INCLUDE")
        view = {r["id"]: r for r in db.query("SELECT * FROM research_documents WHERE research_id=?", (rid,))}
        self.assertEqual(view[ids[0]]["decision"], "MANUAL_EXCLUDE")

    def test_REL_04_results_list_has_one_row_per_document(self):
        """ИД-32: GET /researches/{id}/results возвращал документ дважды."""
        rid, ids = self._research_with_docs(3)
        self._assess(rid)
        for did in ids:
            _legacy_row(rid, did)
        res = S.search_results(rid, limit=100)
        self.assertEqual(res["total"], len(ids))
        self.assertEqual(len({r["document_id"] for r in res["items"]}), len(ids))
        direct = S.search_results(rid, cls="DIRECT", limit=100)
        self.assertEqual(direct["total"], len([r for r in res["items"] if r["relevance_class"] == "DIRECT"]))

    def test_REL_05_stage_result_reports_created_and_updated(self):
        rid, ids = self._research_with_docs(2)
        db.execute("DELETE FROM search_results WHERE research_id=?", (rid,))
        first = self._assess(rid)
        self.assertEqual(first["created"], len(ids))
        self.assertEqual(first["updated"], 0)
        second = self._assess(rid)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], len(ids))
        self.assertEqual(second["assessed"], len(ids))
