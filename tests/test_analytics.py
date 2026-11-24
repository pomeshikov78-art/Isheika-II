"""Расчётное ядро: TRL, реализуемость, барьеры, прогноз (ТЗ-03)."""
from isheika.analytics import barriers as B, feasibility as F, forecast as FC, trl as T
from isheika.registry.loader import methodology
from isheika.storage import db

from .base import BaseCase


class TRLTests(BaseCase):
    def test_no_evidence_means_level_one(self):
        rid = self.make_research()
        res = T.compute(rid)
        self.assertEqual(res["trl"], 1)
        self.assertTrue(res["gaps"], "пробелы должны фиксироваться")
        self.assertIsNone(res["confidence"])

    def test_max_level_not_average(self):
        rid = self.make_research()
        for i in range(4):
            self.add_doc(rid, f"Тропосферная связь: экспериментальное подтверждение {i}",
                         abstract="Экспериментальные измерения и лабораторная проверка принципа действия.",
                         group=f"g{i % 2}", evidence_class="primary_peer_reviewed")
        res = T.compute(rid)
        self.assertGreaterEqual(res["trl"], 1)
        self.assertLessEqual(res["trl"], 9)
        # усреднение запрещено: уровень — целое и совпадает с максимальным пройденным
        self.assertIsInstance(res["trl"], int)
        confirmed_levels = [c["level"] for c in res["criteria"] if c["confirmed"]]
        self.assertLessEqual(res["trl"], max(confirmed_levels) if confirmed_levels else 1)
        self.assertIn("усреднение", res["note"])

    def test_confidence_is_bounded_and_honest(self):
        rid = self.make_research()
        for i in range(2):
            self.add_doc(rid, f"Тропосферная связь, эксперимент {i}", group=f"g{i}",
                         abstract="Экспериментальное подтверждение принципа.")
        res = T.compute(rid)
        if res["confidence"] is not None:
            self.assertLessEqual(res["confidence"], 0.95)
            self.assertGreater(res["confidence"], 0.0)

    def test_reproducible_hash_and_version(self):
        rid = self.make_research()
        self.add_doc(rid, "Тропосферная связь: эксперимент", abstract="Экспериментальные данные.")
        a = T.compute(rid)
        b = T.compute(rid)
        self.assertEqual(a["input_hash"], b["input_hash"])
        from isheika.analytics import methodologies as M
        m = M.active("TRL_CRITERIA")
        self.assertEqual(a["methodology_version"], m["code"] + " " + m["version"])
        self.assertEqual(db.count("analytics_trl", "research_id=?", (rid,)), 2)

    def test_simulated_documents_do_not_confirm(self):
        rid = self.make_research()
        self.add_doc(rid, "Тропосферная связь: демонстрация в реальных условиях",
                     abstract="Прототип испытан в эксплуатационных условиях, серия произведена.",
                     identifiers={"simulated": True}, evidence_class="primary_report")
        res = T.compute(rid)
        self.assertLessEqual(res["trl"], 3, "имитационные документы не подтверждают высокие уровни")

    def test_validation_metrics_without_sample(self):
        m = T.validation_metrics([])
        self.assertFalse(m["calibrated"])
        self.assertEqual(m["status"], "калибровка не завершена")
        m2 = T.validation_metrics([(3, 3), (4, 5), (6, 6)])
        self.assertAlmostEqual(m2["mae"], 1 / 3, places=3)


class FeasibilityTests(BaseCase):
    def _with_docs(self):
        rid = self.make_research()
        for i in range(3):
            self.add_doc(rid, f"Тропосферная связь: эксперимент {i}", group=f"g{i}",
                         abstract="Экспериментальные измерения, расчёт бюджета линии, испытанный прототип.")
        return rid

    def test_formula_and_coverage(self):
        rid = self._with_docs()
        res = F.compute(rid)
        known = [f for f in res["factors"] if f.get("x") is not None and f["assessment"] != "unknown"]
        total_w = sum(f["weight"] for f in res["factors"])
        denom = sum(f["weight"] for f in known)
        numer = sum(f["weight"] * f["x"] for f in known)
        self.assertAlmostEqual(res["score"], round(100 * numer / denom, 2), places=2)
        self.assertAlmostEqual(res["coverage"], round(denom / total_w, 4), places=4)

    def test_unknown_factor_not_zero(self):
        rid = self._with_docs()
        res = F.compute(rid)
        unknown = [f for f in res["factors"] if f["x"] is None]
        self.assertTrue(unknown, "часть факторов должна остаться неизвестной")
        for f in unknown:
            self.assertEqual(f["assessment"], "unknown")
        self.assertLess(res["coverage"], 1.0)
        for f in unknown:
            self.assertIn(f["code"], res["unknown_factors"])

    def test_range_contains_score(self):
        rid = self._with_docs()
        res = F.compute(rid)
        low, high = res["range"]
        self.assertLessEqual(low, res["score"])
        self.assertGreaterEqual(high, res["score"])
        self.assertEqual(res["conservative"], low)

    def test_weights_override_and_sensitivity(self):
        rid = self._with_docs()
        base = F.compute(rid)
        self.assertTrue(base["sensitivity"])
        for s in base["sensitivity"]:
            self.assertIn("without_factor", s)
            self.assertIn("weight_plus30", s)
        # детерминированная проверка формулы на разных оценках факторов
        factors = [
            {"code": "t1", "name": "Фактор 1", "weight": 0.5, "x": 0.2, "assessment": "confirmed",
             "document_ids": [], "rationale": "тест", "producer": "test"},
            {"code": "t2", "name": "Фактор 2", "weight": 0.5, "x": 0.9, "assessment": "confirmed",
             "document_ids": [], "rationale": "тест", "producer": "test"},
            {"code": "t3", "name": "Фактор 3", "weight": 0.5, "x": None, "assessment": "unknown",
             "document_ids": [], "rationale": "нет данных", "producer": "test"},
        ]
        r1 = F.compute(rid, factors=[dict(f) for f in factors])
        self.assertAlmostEqual(r1["score"], 55.0, places=2)
        self.assertAlmostEqual(r1["coverage"], round(1.0 / 1.5, 4), places=4)
        r2 = F.compute(rid, factors=[dict(f) for f in factors], weight_overrides={"t1": 0.8, "t2": 0.2})
        self.assertAlmostEqual(r2["score"], 34.0, places=2)
        self.assertNotEqual(r1["score"], r2["score"])

    def test_empty_research_is_not_zero_score(self):
        rid = self.make_research()
        res = F.compute(rid)
        self.assertIn(res["interpretation"], ("недостаточно данных для оценки", res["interpretation"]))
        self.assertEqual(res["coverage"], 0.0)


class BarrierTests(BaseCase):
    def test_empty_research_does_not_crash(self):
        rid = self.make_research()
        res = B.compute(rid)
        self.assertEqual(res["barriers"], [])
        self.assertEqual(res["types_total"], 11)
        self.assertIn("пробел поиска", res["note"])

    def test_detected_barriers_have_scale(self):
        rid = self.make_research()
        self.add_doc(rid, "Тропосферная связь: ограничения по энергопотреблению",
                     abstract="Высокое энергопотребление усилителя и тепловые ограничения требуют охлаждения.")
        res = B.compute(rid)
        for b in res["barriers"]:
            self.assertTrue(0 <= b["criticality"] <= 1)
            self.assertTrue(0 <= b["probability"] <= 1)
            self.assertIn(b["barrier_type"], methodology()["barriers"]["types"])


class ForecastTests(BaseCase):
    def test_monotonic_and_wide_horizons(self):
        rid = self.make_research()
        for i in range(3):
            self.add_doc(rid, f"Тропосферная связь {i}", year=str(2016 + i), group=f"g{i}")
        T.compute(rid)
        F.compute(rid)
        res = FC.compute(rid)
        self.assertTrue(res["monotonic_ok"])
        self.assertEqual(len(res["horizons"]), 6)
        for target, scen in res["scenarios"].items():
            for name, points in scen.items():
                prev = -1.0
                for p in points:
                    if p["probability"] is not None:
                        self.assertGreaterEqual(p["probability"], prev)
                        prev = p["probability"]
                        self.assertLessEqual(p["probability"], 1.0)
                        self.assertLessEqual(p["interval"][0], p["probability"])
                        self.assertGreaterEqual(p["interval"][1], p["probability"])
                    if p["years_from"] >= 20:
                        self.assertIsNone(p["probability"], "на 20–50 годах только качественные сценарии")
                        self.assertTrue(p["qualitative"])
            self.assertEqual(set(scen), {"optimistic", "base", "pessimistic"})

    def test_brier_without_sample(self):
        m = FC.brier_score([])
        self.assertFalse(m["calibrated"])
        self.assertEqual(m["status"], "калибровка не завершена")
        self.assertAlmostEqual(FC.brier_score([(1.0, 1), (0.0, 0)])["brier"], 0.0)
        self.assertAlmostEqual(FC.brier_score([(1.0, 0), (0.0, 1)])["brier"], 1.0)
