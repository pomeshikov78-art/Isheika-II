"""Испытания полноты поиска для многословных тем (ИД-29…ИД-31, ред. 1.5.3).

Основание — пятая выгрузка журнала с машины пользователя (25.11.2026, 08:11,
исследование res-495bc182…, тема «Цифровой двойник в связи»): поисковая модель
состояла из ОДНОЙ ветви с выражением ("технологии цифровых двойников системах") —
склеенная точная фраза из четырёх слов с выброшенными предлогами, без синонимов
и без англоязычной ветви. Итог: 13 документов, 1 прямой, TRL 1, покрытие 0.3,
`interpretation_allowed=false`; у короткого запроса той же сессии — 81/39, TRL 4.

QRY-01 — многословная тема не превращается в одну склеенную фразу.
QRY-02 — для нераспознанной темы строится англоязычная ветвь по глоссарию.
QRY-03 — тема «цифровой двойник» распознана словарём сущностей (синонимы RU/EN).
QRY-04 — нераскрытое сокращение даёт предупреждение, а не пустую выдачу молча.
QRY-05 — предупреждения доходят до этапа и до интерфейса.
QRY-06 — короткие запросы и распознанные темы не изменились (контроль).
ARX-01 — arXiv: скобки и операторы не попадают в термы запроса.
ARX-02 — StackExchange: операторы не становятся словами запроса.
"""
from __future__ import annotations

import os
import re
from unittest import mock

from isheika.search import connectors as CN
from isheika.search import expansion as EX, query_parser as QP
from isheika.storage import db

from .base import BaseCase

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "isheika", "web")


def build(text: str):
    q = QP.parse(text)
    return q, EX.build(q, languages=["ru", "en"])


class QueryRecallTests(BaseCase):
    def test_QRY_01_multiword_topic_is_not_one_glued_phrase(self):
        """ИД-29: («технологии цифровых двойников системах») — одна фраза, 1 ветвь."""
        q, ex = build("технологии цифровых двойников в системах связи")
        core = [b for b in ex.branches if b.kind == "core"]
        self.assertGreaterEqual(len(core), 2, "нет англоязычной ветви")
        ru = next(b for b in core if b.name.endswith("(RU)"))
        self.assertGreater(len(ru.terms), 1, "ядро сведено к одной склеенной фразе")
        self.assertNotIn("технологии цифровых двойников системах", ru.terms)
        for t in ru.terms:
            self.assertLessEqual(len(t.split()), 3, f"слишком длинная точная фраза: {t}")

    def test_QRY_02_english_branch_from_glossary_for_unknown_topic(self):
        """Тема вне словаря сущностей: перевод берётся из глоссария, а не теряется."""
        with mock.patch.object(QP, "ENTITY_LEXICON", {}):
            q, ex = build("технологии цифровых двойников в системах связи")
        en = [b for b in ex.branches if b.name == "Core (EN)"]
        self.assertTrue(en, "англоязычная ветвь не построена")
        self.assertIn("digital twin", en[0].expression)
        self.assertTrue(ex.translations)
        self.assertFalse(re.search(r"[а-яё]", en[0].expression), "в EN-ветви кириллица")

    def test_QRY_03_digital_twin_is_recognised_entity(self):
        q, ex = build("Цифровой двойник в связи")
        self.assertIn("digital_twin", q.entities)
        self.assertIn("цифровой двойник", ex.synonyms)
        self.assertIn("digital twin", ex.translations)
        self.assertGreaterEqual(len([b for b in ex.branches if b.kind == "core"]), 2)
        self.assertFalse(ex.warnings, "распознанная тема не должна предупреждать")

    def test_QRY_04_unexpanded_abbreviation_warns(self):
        q, ex = build("бшпд")
        self.assertTrue(any("не раскрыто" in w for w in ex.warnings), ex.warnings)
        self.assertTrue(any("англоязычная ветвь не построена" in w for w in ex.warnings))
        self.assertEqual([b.expression for b in ex.branches if b.kind == "core"], ["бшпд"])

    def test_QRY_05_warnings_reach_stage_and_ui(self):
        from isheika.workflow import pipeline as PL
        rid = self.make_research("бшпд")
        job = {"id": "job-qry-153", "research_id": rid}
        with mock.patch.object(PL.W, "progress", lambda *a, **k: None):
            res = PL.stage_search_model(job, {})
        self.assertTrue(res["warnings"])
        self.assertTrue(db.one("SELECT id FROM ops_journal WHERE action='search_model.warning' AND research_id=?",
                               (rid,)))
        with open(os.path.join(WEB_DIR, "screens_core.js"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("ex.warnings", src)
        self.assertIn("warns.map", src)

    def test_QRY_06_known_topics_unchanged(self):
        """Контроль: распознанные темы и короткие обозначения работают как раньше."""
        q, ex = build("6G")
        names = [b.name for b in ex.branches]
        self.assertIn("Ядро (RU)", names)
        self.assertIn("Core (EN)", names)
        self.assertIn("6G", ex.core_terms)
        self.assertFalse(ex.warnings)
        q2, ex2 = build("тропосферная связь за горизонтом")
        self.assertIn("tropospheric scatter", ex2.translations)
        self.assertFalse(ex2.warnings)


class ConnectorTermsTests(BaseCase):
    def connector(self, code: str):
        meta = db.dec(db.one("SELECT * FROM registry_connectors WHERE code=?", (code,)),
                      "capabilities", "limits", "quota_policy")
        return CN.build_connector(meta)

    def test_ARX_01_parentheses_do_not_leak_into_terms(self):
        """ИД-30: all:"("технологии" OR all:"цифровых" … — невалидный запрос."""
        c = self.connector("CON-ARXIV")
        atom = ('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        with mock.patch.object(c, "get", return_value={"body": atom}) as gj:
            c.search('("технологии цифровых двойников системах")', limit=5)
        url = gj.call_args[0][0]
        self.assertNotIn("%28", url)          # скобок в запросе нет
        self.assertNotIn("%22%22", url)       # вложенных кавычек нет
        self.assertIn("all%3A%22", url)
        with mock.patch.object(c, "get", return_value={"body": atom}) as gj2:
            c.search('("digital twin" OR "digital twins") AND (communication OR "data link")', limit=5)
        url2 = gj2.call_args[0][0]
        self.assertNotIn("OR%22", url2.replace("all%3A%22digital", ""))
        self.assertNotIn("%28", url2)

    def test_ARX_02_stackexchange_operators_are_not_words(self):
        c = self.connector("CON-STACKEXCHANGE")
        with mock.patch.object(c, "get_json", return_value={"items": []}) as gj:
            c.search('("digital twin" OR "digital twins") AND communication', limit=6)
        url = gj.call_args_list[0][0][0]
        self.assertNotIn("OR", url.split("q=")[1].split("&")[0].replace("digital", ""))
        self.assertNotIn("AND", url)
        self.assertIn("digital%20twin", url)
