"""Поисковая модель и релевантность (ТЗ-01 §4, ТЗ-03 §3)."""
from isheika.registry.loader import methodology
from isheika.search import expansion as EX, query_parser as QP, relevance as R

from .base import BaseCase


class QueryTests(BaseCase):
    def test_parse_russian_query(self):
        q = QP.parse("тропосферная связь за горизонтом 2015-2025")
        self.assertIn("tropospheric_scatter", q.entities)
        self.assertTrue(q.object_terms)

    def test_expansion_has_ru_and_en_branches(self):
        q = QP.parse("тропосферная связь")
        ex = EX.build(q, languages=["ru", "en"])
        kinds = {b.kind for b in ex.branches}
        self.assertIn("core", kinds)
        names = " ".join(b.name for b in ex.branches)
        self.assertIn("RU", names)
        self.assertIn("EN", names)
        self.assertTrue(ex.translations, "должны быть англоязычные синонимы")

    def test_expression_is_quoted(self):
        q = QP.parse("тропосферная связь")
        ex = EX.build(q)
        expr = EX.primary_expression(ex, q)
        self.assertIn('"тропосферная связь"', expr)
        self.assertIn(" OR ", expr)

    def test_unknown_topic_does_not_invent_terms(self):
        q = QP.parse("квантовый гравитационный диод")
        ex = EX.build(q)
        self.assertTrue(ex.core_terms)
        self.assertNotIn("troposcatter", ex.core_terms)


class RelevanceTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.q = QP.parse("тропосферная связь за горизонтом")
        self.ex = EX.build(self.q, languages=["ru", "en"])

    def test_direct_match(self):
        d = self.document("Тропосферная связь за горизонтом: результаты испытаний",
                          "Экспериментальное исследование тропосферного рассеяния на трассе 250 км.",
                          evidence_class="primary_peer_reviewed", published_at="2023-05-01",
                          doc_type="article", language="ru")
        res = R.assess(d, self.q, self.ex)
        self.assertGreaterEqual(res.score, methodology()["relevance"]["thresholds"]["direct"])
        self.assertEqual(res.cls, "DIRECT")

    def test_english_synonym_match(self):
        d = self.document("Troposcatter link measurements beyond line of sight",
                          "Experimental tropospheric scatter propagation trial over 250 km path.", language="en")
        res = R.assess(d, self.q, self.ex)
        self.assertGreaterEqual(res.score, methodology()["relevance"]["thresholds"]["adjacent"])

    def test_poor_metadata_downgrades_class(self):
        """Документ без класса доказательства и даты не может быть «прямым»:
        компонент E (качество доказательства) и F (формальные признаки) снижены."""
        d = self.document("Тропосферная связь за горизонтом: результаты испытаний",
                          "Экспериментальное исследование тропосферного рассеяния.")
        res = R.assess(d, self.q, self.ex)
        self.assertEqual(res.cls, "ADJACENT")
        self.assertLess(res.components["E"], 0.5)

    def test_irrelevant_is_excluded(self):
        d = self.document("Влияние диеты на популяцию ежей", "Зоологическое исследование.", language="ru")
        res = R.assess(d, self.q, self.ex)
        self.assertLess(res.score, methodology()["relevance"]["thresholds"]["adjacent"])
        self.assertEqual(res.cls, "BELOW_THRESHOLD")

    def test_components_and_weights(self):
        d = self.document("Тропосферная связь", "Тропосферное рассеяние, эксперимент.")
        res = R.assess(d, self.q, self.ex)
        w = methodology()["relevance"]["weights"]
        self.assertAlmostEqual(sum(w.values()), 1.0, places=6)
        manual = sum(w[k] * res.components[k] for k in w)
        self.assertAlmostEqual(res.score, round(manual, 4), places=3)
        self.assertTrue(set(w).issubset(set(res.components)))

    def test_metrics(self):
        self.assertEqual(R.precision_at_k([2, 2, 0, 1], 2), 1.0)
        self.assertEqual(R.precision_at_k([2, 0, 0, 0], 4), 0.25)
        self.assertEqual(R.precision_at_k([0, 0, 0], 3), 0.0)
        self.assertLessEqual(R.precision_at_k([2, 2, 2], 3), 1.0)
        self.assertEqual(R.recall_at_k([2, 0, 1, 0], 2, 2), 0.5)
        self.assertIsNone(R.precision_at_k([], 10))
        ndcg = R.ndcg_at_k([2, 1, 0], 3)
        self.assertTrue(0 < ndcg <= 1)
        self.assertGreater(R.ndcg_at_k([2, 1, 0], 3), R.ndcg_at_k([0, 1, 2], 3))
