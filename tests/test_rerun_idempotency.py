"""Испытания повторного прогона: утверждения и дедупликация (ИД-24, ИД-25, ред. 1.5.2).

Основание — четвёртая выгрузка журнала с машины пользователя (25.11.2026,
исследование res-3cd74672…, запрос «бшпд»): пять прогонов подряд давали
8 → 16 → 24 → 32 → 40 утверждений при нуле доказательств (ИД-24) и
«уникальных 0, дублей 15» для собственного корпуса исследования (ИД-25).

CLM-01 — повторный прогон ИИ-задач не удваивает утверждения.
CLM-02 — повтор обновляет утверждение, не сбрасывая статус проверки и связи.
CLM-03 — слой утверждений из документов идемпотентен.
EVD-01 — повторный прогон не удваивает доказательства (ИД-28, найдено живой проверкой).
DED-01 — повторное обнаружение своего же URL не помечает документ дубликатом.
DED-02 — настоящий дубль (другое исследование) по-прежнему помечается.
DED-03 — сводка этапа обработки документов после повторного прогона честная.
"""
from __future__ import annotations

from dataclasses import replace
from unittest import mock

from isheika.ai import agents as AG
from isheika.analytics import evidence as EV
from isheika.search import dedup as DD
from isheika.storage import db

from .base import BaseCase


def _agent_result() -> dict:
    """Ответ агента в том виде, в каком его возвращает маршрутизатор ИИ."""
    return {
        "ok": True, "provider": "PRV-TEST", "model": "test", "simulated": True,
        "structured": {
            "findings": [{"claim": "Заявлена дальность 300 км на частоте 6 ГГц",
                          "claim_type": "ANALYSIS", "document_ids": []}],
            "countries": [{"iso2": "RU", "activity": "испытания макета", "document_ids": []}],
            "alternatives": [{"name": "Спутниковый канал", "principle": "геостационарный ретранслятор"}],
            "assumptions": [{"text": "Дальность ограничена энергетикой линии"}],
            "issues": [{"kind": "gap", "text": "Нет независимых измерений"}],
            "principle": "Рассеяние на неоднородностях тропосферы",
        },
    }


class RerunClaimTests(BaseCase):
    def test_CLM_01_agent_rerun_does_not_multiply_claims(self):
        """ИД-24: пять прогонов подряд давали 8/16/24/32/40 утверждений."""
        rid = self.make_research("бшпд")
        res = _agent_result()
        AG._claims_from_agent(rid, "AG-01", res)
        first = db.count("knowledge_claims", "research_id=?", (rid,))
        self.assertGreater(first, 0)
        for _ in range(4):
            AG._claims_from_agent(rid, "AG-01", res)
        self.assertEqual(db.count("knowledge_claims", "research_id=?", (rid,)), first)
        # связи агента с документами тоже не размножаются
        self.assertEqual(db.count("knowledge_links", "research_id=?", (rid,)),
                         db.one("""SELECT COUNT(*) AS n FROM (SELECT DISTINCT from_id, to_id
                                   FROM knowledge_links WHERE research_id=?)""", (rid,))["n"])

    def test_CLM_02_upsert_keeps_verification_status_and_links(self):
        rid = self.make_research("6G")
        did = self.add_doc(rid, "Terahertz link field trial", abstract="Measured 300 m link.")
        cid = EV.upsert_claim(rid, text="Дальность 300 м подтверждена измерениями",
                              ctype="FACT", section="AG-02", produced_by="AG-02:test",
                              doc_ids=[did])
        db.update("knowledge_claims", "id", cid, {"status": "SUPPORTED", "confidence": 0.9})
        again = EV.upsert_claim(rid, text="Дальность 300 м подтверждена измерениями",
                                ctype="ANALYSIS", section="AG-02", produced_by="AG-02:other",
                                doc_ids=[did])
        self.assertEqual(again, cid)
        row = db.one("SELECT * FROM knowledge_claims WHERE id=?", (cid,))
        self.assertEqual(row["status"], "SUPPORTED")
        self.assertEqual(row["claim_type"], "ANALYSIS")
        self.assertEqual(row["produced_by"], "AG-02:other")
        self.assertEqual(db.count("knowledge_claims", "research_id=?", (rid,)), 1)
        self.assertEqual(db.count("knowledge_links", "research_id=? AND to_id=?", (rid, did)), 1)

    def test_CLM_03_document_layer_is_idempotent(self):
        rid = self.make_research("тропосферная связь за горизонтом")
        self.add_doc(rid, "Tropospheric scatter measurements", abstract="Beyond horizon link.")
        self.add_doc(rid, "Second troposcatter trial", abstract="Independent measurements.")
        EV._claims_from_documents(rid, {r["id"]: db.dec(r, "authors", "organizations", "identifiers")
                                       for r in db.query("SELECT * FROM research_documents WHERE research_id=?", (rid,))})
        first = db.count("knowledge_claims", "research_id=?", (rid,))
        self.assertGreaterEqual(first, 2)
        EV._claims_from_documents(rid, {r["id"]: db.dec(r, "authors", "organizations", "identifiers")
                                       for r in db.query("SELECT * FROM research_documents WHERE research_id=?", (rid,))})
        self.assertEqual(db.count("knowledge_claims", "research_id=?", (rid,)), first)


class RerunEvidenceTests(BaseCase):
    def test_EVD_01_evidence_items_are_not_doubled(self):
        """ИД-28: живая проверка 1.5.2 — 120 доказательств превращались в 240."""
        rid = self.make_research("тропосферная связь за горизонтом")
        for i, (title, abstract) in enumerate([
                ("Tropospheric scatter link budget at 4.4 GHz",
                 "Energy budget of a 320 km beyond-horizon path."),
                ("Antenna array design for troposcatter terminals",
                 "Phased array aperture synthesis and beam steering.")]):
            self.add_doc(rid, title, abstract=abstract, url=f"https://example.org/evd-152-{i}")
        first = EV.build_evidence(rid)
        n1 = db.count("evidence_items", "research_id=?", (rid,))
        self.assertGreater(n1, 0)
        second = EV.build_evidence(rid)
        n2 = db.count("evidence_items", "research_id=?", (rid,))
        self.assertEqual(n2, n1, "повторный прогон удвоил доказательства")
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["updated"], first["created"])
        self.assertEqual(second["evidence_items"], first["evidence_items"])
        self.assertEqual(db.count("knowledge_claims", "research_id=?", (rid,)), first["claims"])


class RerunDedupTests(BaseCase):
    def test_DED_01_same_occurrence_does_not_mark_self_duplicate(self):
        """ИД-25: повтор своего же URL помечал документ дубликатом самого себя."""
        rid = self.make_research("бшпд")
        doc = replace(self.document("Beyond-horizon tropospheric link budget",
                                    abstract="Measured link budget for 300 km path."),
                      url="https://example.org/ded01-152", external_id="ded01-152")
        first = DD.store(rid, doc)
        self.assertEqual(first["deduplication_status"], "UNIQUE")
        again = DD.store(rid, doc)
        self.assertEqual(again["document_id"], first["document_id"])
        self.assertFalse(again["new_occurrence"])
        self.assertFalse(again["new_document"])
        self.assertEqual(again["deduplication_status"], "UNIQUE")
        row = db.one("SELECT deduplication_status FROM content_documents WHERE id=?",
                     (first["document_id"],))
        self.assertEqual(row["deduplication_status"], "UNIQUE")
        self.assertEqual(db.count("content_occurrences", "research_id=?", (rid,)), 1)

    def test_DED_02_real_duplicate_from_other_research_still_marked(self):
        rid1 = self.make_research("6G")
        rid2 = self.make_research("6G повтор")
        doc = replace(self.document("6G terahertz roadmap", abstract="Roadmap of 6G research."),
                      url="https://example.org/ded02-152", external_id="ded02-152")
        DD.store(rid1, doc)
        other = DD.store(rid2, doc)
        self.assertEqual(other["deduplication_status"], "DUPLICATE")
        self.assertFalse(other["new_document"])
        self.assertTrue(other["new_occurrence"])
        # возврат в первое исследование не меняет статус на «дубль»
        back = DD.store(rid1, doc)
        self.assertEqual(back["deduplication_status"],
                         db.one("SELECT deduplication_status FROM content_documents WHERE id=?",
                                (other["document_id"],))["deduplication_status"])

    def test_DED_03_stage_summary_after_rerun_is_honest(self):
        from isheika.workflow import pipeline as PL
        rid = self.make_research("тропосферная связь за горизонтом")
        docs = [replace(self.document(title, abstract=abstract),
                        url=f"https://example.org/tro-152-{i}", external_id=f"tro-152-{i}")
                for i, (title, abstract) in enumerate([
                    ("Tropospheric scatter link budget at 4.4 GHz",
                     "Energy budget of a 320 km beyond-horizon path."),
                    ("Antenna array design for troposcatter terminals",
                     "Phased array aperture synthesis and beam steering."),
                    ("Rain attenuation statistics for millimetre waves",
                     "Ten-year rain rate measurements at 38 GHz.")])]
        for d in docs:
            DD.store(rid, d)
        for d in docs:            # повторный поиск того же корпуса
            DD.store(rid, d)
        job = {"id": "job-test-152", "research_id": rid}
        with mock.patch.object(PL.W, "progress", lambda *a, **k: None), \
             mock.patch.object(PL.TR, "run", lambda *a, **k: {"translated": 0}):
            res = PL.stage_document_processing(job, {"research_id": rid})
        self.assertEqual(res["documents_total"], 3)
        self.assertEqual(res["unique"], 3)
        self.assertEqual(res["duplicates"], 0)
        self.assertEqual(res["occurrences"], 3)
