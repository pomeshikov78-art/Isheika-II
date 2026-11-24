"""Испытания технического перевода найденной НТИ на русский язык (ред. 1.5.0).

Задача пользователя: «найденная научно-техническая информация должна быть
переведена на русский язык (технический перевод)».

TRN-01 — иностранный документ получает русский заголовок и аннотацию.
TRN-02 — числа, единицы, обозначения и идентификаторы сохраняются дословно.
TRN-03 — русский материал не переводится и помечается как оригинал.
TRN-04 — режим перевода и признак вычитки указаны честно, доля перевода считается.
TRN-05 — перевод выполняется этапом 4 и виден в сводке исследования.
TRN-06 — перевод попадает во все форматы отчёта (HTML/CSV/XLSX/DOCX/PDF/JSON).
TRN-07 — API отдаёт перевод и оригинал, повторный перевод по force.
TRN-08 — маршрут ИИ используется только настоящий (имитация перевод не подменяет).
TRN-09 — отказ перевода одного документа не срывает этап.
"""
from __future__ import annotations

import json
import os
import time

from isheika import translation as TR
from isheika.storage import db
from isheika.workflow import engine as W
from isheika.workflow import pipeline as P  # noqa: F401
from tests.base import BaseCase

EN_TITLE = "A novel tropospheric scatter link budget model for 6G backhaul at 4.7 GHz"
EN_ABSTRACT = ("This paper presents a compact wideband antenna array with 18 dBi gain. "
               "The measured data rate reaches 12 Gbps over 3 km. DOI 10.1234/abc.2024.001.")


def wait_done(rid: str, timeout: float = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = W.status(rid)
        if not st["running"] and all(j["status"] in ("completed", "partial", "failed", "cancelled", "skipped")
                                     for j in st["jobs"]):
            return st
        time.sleep(0.2)
    raise AssertionError("исследование не завершилось")


class TranslationTests(BaseCase):
    def _en_doc(self, rid: str, **kw) -> str:
        return self.add_doc(rid, EN_TITLE, abstract=EN_ABSTRACT, language="en",
                            external_id=kw.get("external_id", "en-1"),
                            url=kw.get("url", "https://example.org/en-1"))

    def test_TRN_01_foreign_document_gets_russian(self):
        """TRN-01: иностранный материал получает русский заголовок и аннотацию."""
        rid = self.make_research()
        did = self._en_doc(rid)
        row = TR.translate_document(db.one("SELECT * FROM content_documents WHERE id=?", (did,)),
                                    research_id=rid)
        self.assertTrue(row["title_ru"])
        self.assertNotEqual(row["title_ru"], EN_TITLE)
        self.assertRegex(row["title_ru"], r"[А-Яа-яЁё]{4,}")
        self.assertIn("тропосферн", row["title_ru"].lower())
        self.assertIn("бюджет радиолинии", row["title_ru"].lower())
        self.assertRegex(row["abstract_ru"], r"[А-Яа-яЁё]{4,}")
        self.assertEqual(row["lang_to"], "ru")
        self.assertEqual(row["lang_from"], "en")

    def test_TRN_02_numbers_units_ids_preserved(self):
        """TRN-02: числа, единицы и идентификаторы не искажаются переводом."""
        out = TR.translate_text(EN_ABSTRACT)
        text = out["text"]
        for fragment in ("18", "12", "3", "10.1234/abc.2024.001"):
            self.assertIn(fragment, text, f"потерян фрагмент {fragment}")
        self.assertIn("дБи", text)          # dBi → дБи
        self.assertIn("Гбит/с", text)       # Gbps → Гбит/с
        self.assertIn("км", text)
        self.assertNotIn("Gbps", text)

    def test_TRN_03_russian_document_untouched(self):
        """TRN-03: русский материал не переводится и помечается оригиналом."""
        rid = self.make_research()
        did = self.add_doc(rid, "Тропосферная связь за горизонтом", language="ru",
                           abstract="Измерен бюджет радиолинии на частоте 4,7 ГГц.",
                           external_id="ru-1", url="https://example.org/ru-1")
        row = TR.translate_document(db.one("SELECT * FROM content_documents WHERE id=?", (did,)),
                                    research_id=rid)
        self.assertEqual(row["mode"], "original")
        self.assertEqual(row["title_ru"], "Тропосферная связь за горизонтом")
        self.assertEqual(row["review_required"], 0)
        self.assertEqual(TR.detect_language("Измерен бюджет радиолинии"), "ru")
        self.assertEqual(TR.detect_language("Measured link budget"), "en")

    def test_TRN_04_mode_and_coverage_are_honest(self):
        """TRN-04: черновой перевод не выдаётся за полноценный, доля считается."""
        rid = self.make_research()
        did = self._en_doc(rid)
        row = TR.translate_document(db.one("SELECT * FROM content_documents WHERE id=?", (did,)),
                                    research_id=rid)
        self.assertIn(row["mode"], ("terminology", "ai_technical"))
        self.assertEqual(row["review_required"], 1, "машинный перевод требует вычитки")
        self.assertTrue(0 < row["coverage"] <= 1)
        self.assertTrue(row["glossary_version"].startswith("G-"))
        unknown = TR.translate_text("The quokka flux capacitor improves warp coherence.")
        self.assertLess(unknown["coverage"], 1.0, "неизвестные слова не должны считаться переведёнными")
        self.assertTrue(unknown["untranslated"])

    def test_TRN_05_stage4_translates_and_reports(self):
        """TRN-05: перевод выполняется этапом 4 и виден в сводке исследования."""
        rid = self.make_research("тропосферная связь за горизонтом — перевод TRN",
                                 settings={"connector_codes": ["CON-SIM"], "max_docs_per_source": 3})
        self._en_doc(rid, external_id="en-stage", url="https://example.org/en-stage")
        W.start(rid)
        wait_done(rid)
        job = db.dec(db.one("SELECT result FROM workflow_jobs WHERE research_id=? AND stage='document_processing'",
                            (rid,)), "result")
        tr = job["result"].get("translation")
        self.assertTrue(tr, "этап 4 не отчитался о переводе")
        self.assertGreaterEqual(tr["translated"], 1)
        summary = TR.summary(rid)
        self.assertGreaterEqual(summary["translated"], 1)
        self.assertIn("glossary_version", summary)

    def test_TRN_06_report_contains_russian(self):
        """TRN-06: русский перевод попадает во все форматы отчёта."""
        from isheika.reports import builder as RB
        rid = self.make_research("тропосферная связь за горизонтом — перевод TRN",
                                 settings={"connector_codes": ["CON-SIM"], "max_docs_per_source": 3})
        self._en_doc(rid, external_id="en-rep", url="https://example.org/en-rep")
        W.start(rid)
        wait_done(rid)
        res = RB.generate(rid)
        self.assertEqual(res["status"], "ready", res)
        with open(res["files"]["html"], encoding="utf-8") as f:
            html_text = f.read()
        self.assertIn("терминологический перевод", html_text)
        with open(res["files"]["csv_documents"], encoding="utf-8-sig") as f:
            csv_text = f.read()
        self.assertIn("title_ru", csv_text)
        self.assertIn("бюджет радиолинии", csv_text)
        with open(res["files"]["json"], encoding="utf-8") as f:
            data = json.load(f)
        self.assertTrue(any(d.get("title_ru") for d in data["documents"]))
        self.assertIn("translation", data)
        for key in ("xlsx", "docx", "pdf"):
            self.assertTrue(os.path.getsize(res["files"][key]) > 0)
        with open(res["files"]["docx"], "rb") as f:
            self.assertIn(b"PK", f.read(2))

    def test_TRN_07_api_translation_and_force(self):
        """TRN-07: API отдаёт перевод с оригиналом; force пересчитывает перевод."""
        from isheika.api import service as S
        rid = self.make_research()
        did = self._en_doc(rid, external_id="en-api", url="https://example.org/en-api")
        out = S.document_translation(did)
        self.assertEqual(out["translation"]["lang_to"], "ru")
        self.assertEqual(out["original"]["title"], EN_TITLE)
        self.assertIn("вычитки", out["note"])
        first = out["translation"]["updated_at"]
        res = S.translate_research(rid, force=True, actor="tester")
        self.assertGreaterEqual(res["translated"], 1)
        again = S.document_translation(did)["translation"]
        self.assertGreaterEqual(again["updated_at"], first)
        listed = S.list_documents(rid, limit=10)["items"]
        self.assertTrue([d for d in listed if d.get("title_ru")])

    def test_TRN_08_simulation_never_fakes_translation(self):
        """TRN-08: имитационный провайдер не подменяет перевод выдуманным текстом."""
        from unittest import mock
        route = {"entry": {"provider": {"id": "simulation", "family": "local"},
                           "model": {"model_id": "sim-1"}}}
        with mock.patch("isheika.ai.orchestrator.select_route", return_value=route):
            self.assertIsNone(TR.ai_route(), "имитация не должна использоваться для перевода")
        rid = self.make_research()
        did = self._en_doc(rid, external_id="en-sim", url="https://example.org/en-sim")
        row = TR.translate_document(db.one("SELECT * FROM content_documents WHERE id=?", (did,)), research_id=rid)
        self.assertEqual(row["mode"], "terminology")
        self.assertIsNone(row["provider"])

    def test_TRN_10_declared_language_does_not_hide_foreign_text(self):
        """TRN-10: заявленный коннектором «ru» не скрывает английский заголовок.

        Прогон 1.5.0 на реальных источниках: документ с language=ru имел
        английский заголовок «Applications of atmospheric optical communication
        equipment» и русскую аннотацию — заголовок оставался непереведённым.
        """
        rid = self.make_research()
        did = self.add_doc(rid, "Applications of atmospheric optical communication equipment",
                           abstract="В статье приведены сведения о новых беспроводных каналах связи.",
                           language="ru", external_id="mix-1", url="https://example.org/mix-1")
        row = TR.translate_document(db.one("SELECT * FROM content_documents WHERE id=?", (did,)),
                                    research_id=rid)
        self.assertEqual(row["mode"], "terminology")
        self.assertRegex(row["title_ru"], r"[А-Яа-яЁё]{4,}")
        self.assertNotEqual(row["title_ru"], "Applications of atmospheric optical communication equipment")
        self.assertIn("беспроводных каналах", row["abstract_ru"])

    def test_TRN_09_failure_does_not_break_stage(self):
        """TRN-09: отказ перевода одного документа не срывает этап обработки."""
        from unittest import mock
        rid = self.make_research()
        self._en_doc(rid, external_id="en-fail", url="https://example.org/en-fail")
        with mock.patch.object(TR, "translate_document", side_effect=RuntimeError("искусственный отказ")):
            res = TR.run(rid)
        self.assertEqual(res["failed"], 1)
        self.assertEqual(res["translated"], 0)
