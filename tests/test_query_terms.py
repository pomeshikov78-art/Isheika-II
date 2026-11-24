"""Испытания разбора коротких технических обозначений в запросе (ред. 1.5.0).

Основание — полный прогон программы на реальных источниках: запрос «6G»
разбирался в `tokens: []`, `object_terms: []` (фильтр `len(w) > 2` отбрасывал
обозначение). Все документы получали S = T = K = 0 и класс BELOW_THRESHOLD:
76 найденных материалов, 0 включённых, 0 доказательств, TRL 1 «по умолчанию».

QRY-01 — обозначения 6G/5G/THz/RF сохраняются в терминах запроса.
QRY-02 — расширение строит ядро RU/EN с обозначением и синонимами.
QRY-03 — профильный документ проходит порог, непрофильный — нет.

ИД-19 (обнаружен на том же прогоне): документовский токенизатор
`relevance._WORD = {3,}` отбрасывал короткие обозначения, которые сохраняет
токенизатор запроса. Статья «The ITU Vision and Framework for 6G» получала
S = 0.06, K = 0.03 и класс BELOW_THRESHOLD (R = 0.531): из 67 найденных
материалов по «6G» включался только один.

QRY-04 — обозначение находится и в тексте документа (единый токенизатор).
QRY-05 — омоним («Rhodamine 6G», краситель) не проходит как стандарт связи.
"""
from __future__ import annotations

from isheika.search import expansion as EX, query_parser as QP, relevance as REL
from tests.base import BaseCase


class ShortTermQueryTests(BaseCase):
    def test_QRY_01_short_technical_terms_kept(self):
        """QRY-01: «6G» не теряет термины (до исправления список был пуст)."""
        q = QP.parse("6G")
        self.assertIn("6g", q.tokens)
        self.assertTrue(q.object_terms, "объект исследования не определён")
        self.assertIn("mobile_generation", q.entities)
        self.assertIn("communication", q.purpose)
        for raw, token in (("5G", "5g"), ("RF фронтенд", "rf"), ("THz канал", "thz"), ("AI ускоритель", "ai")):
            self.assertIn(token, QP.parse(raw).tokens, f"потерян термин {token}")

    def test_QRY_02_expansion_has_core_branches(self):
        """QRY-02: расширение даёт ядро RU/EN с обозначением и синонимами."""
        ex = EX.build(QP.parse("6G"), languages=["ru", "en"])
        core = [b for b in ex.branches if b.kind == "core"]
        self.assertGreaterEqual(len(core), 2)
        joined = " ".join(b.expression for b in core).lower()
        self.assertIn("6g", joined)
        self.assertIn("imt-2030", joined)

    def test_QRY_03_relevant_document_passes_threshold(self):
        """QRY-03: профильный материал проходит порог, посторонний — нет."""
        q = QP.parse("6G")
        ex = EX.build(q, languages=["ru", "en"])
        on_topic = self.document(
            "6G Beyond Radio: From Connecting Devices to Sensing the World",
            abstract="We survey 6G IMT-2030 integrated sensing and communication, terahertz links "
                     "and reconfigurable intelligent surfaces for next generation wireless networks.")
        off_topic = self.document(
            "Complexation-Induced Ring Opening of a Rhodamine 6G-Pyridoxal Schiff Base Probe",
            abstract="A fluorescent probe for selective detection of metal ions in solvent is reported.")
        r_on = REL.assess(on_topic, q, ex)
        r_off = REL.assess(off_topic, q, ex)
        self.assertGreater(r_on.score, r_off.score,
                           "профильный документ не отличается от постороннего")
        self.assertIn(r_on.cls, ("DIRECT", "ADJACENT"),
                      f"профильный документ отброшен: R={r_on.score} ({r_on.reason})")

    def test_QRY_04_document_side_short_terms(self):
        """QRY-04: термины документа строятся тем же правилом, что и термины запроса."""
        self.assertIn("6g", REL._terms_of("Framework for 6G and THz links"))
        self.assertIn("thz", REL._terms_of("THz channel"))
        self.assertIn("rf", REL._terms_of("RF front-end"))
        q = QP.parse("6G")
        ex = EX.build(q, languages=["ru", "en"])
        itu = self.document(
            "The ITU Vision and Framework for 6G: Scenarios, Capabilities, and Enablers",
            abstract="We present the IMT-2030 framework for 6G mobile communication systems, "
                     "usage scenarios and key capabilities.")
        r = REL.assess(itu, q, ex)
        self.assertGreaterEqual(r.components["S"], 0.80,
                                "ядро «6G» не найдено в профильном документе")
        self.assertIn(r.cls, ("DIRECT", "ADJACENT"), f"R={r.score}: {r.reason}")
        self.assertGreaterEqual(r.score, 0.70, "профильный материал недобирает балл")

    def test_QRY_05_ambiguous_short_term_needs_domain_signal(self):
        """QRY-05: «Rhodamine 6G» — краситель, а не поколение связи."""
        q = QP.parse("6G")
        ex = EX.build(q, languages=["ru", "en"])
        for title, abstract in (
            ("Complexation-Induced Ring Opening of a Rhodamine 6G-Pyridoxal Schiff Base Probe",
             "A fluorescent probe for selective detection of metal ions in solvent is reported."),
            ("Rhodamine 6G based fluorescent chemosensor for sensing of Fe3+ ions",
             "The probe shows turn-on fluorescence sensing and monitoring of iron ions in water samples."),
        ):
            r = REL.assess(self.document(title, abstract=abstract), q, ex)
            self.assertEqual(r.cls, "BELOW_THRESHOLD", f"омоним принят за профильный: R={r.score}")
            self.assertFalse(r.gate["passed"], "gate не сработал на омониме")
