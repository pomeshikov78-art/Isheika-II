"""Контрольные испытания ведомости корректирующих изменений v1.1.

Каждый тест соответствует нормативному идентификатору из ведомости:
REL-01/02, FEAS-01/02/03, DEDUP-01/02, API-01/02, FCST-01/02, DOC-01/02,
TRL-01/02, METH-01/02, SEP-01/02, EVID-01/02, REPR-01/02.

Тесты проверяют не отдельный модуль, а прохождение данных через контур:
запрос → документы → дедупликация → релевантность → доказательства → расчёт → API.
"""
from __future__ import annotations

import json

from isheika.analytics import confidence as CF, evidence as E, feasibility as F
from isheika.analytics import forecast as FC, methodologies as M, snapshot as SNAP, trl as T
from isheika.contracts import CoreError, Document, iso_now, new_id
from isheika.search import dedup as DD, normalize as norm, relevance as R
from isheika.storage import db
from tests.base import BaseCase


def _doc(title: str, url: str, **kw) -> Document:
    return norm.normalize(Document(
        document_id=new_id("doc-"), source_code=kw.pop("source_code", "SRC-0451"),
        connector_code="CON-TEST", external_id=kw.pop("external_id", new_id()),
        title=title, url=url, abstract=kw.pop("abstract", title), **kw))


class RELTests(BaseCase):
    def test_REL_01_identical_score_same_methodology(self):
        """REL-01: один документ, одна версия методики → идентичный R при повторе."""
        from isheika.search import expansion as EX, query_parser as QP
        q = QP.parse("тропосферная связь загоризонтная передача данных")
        ex = EX.build(q)
        d = _doc("Тропосферная связь: загоризонтная передача данных",
                 "https://example.org/rel01", doc_type="article",
                 evidence_class="primary_peer_reviewed", published_at="2023-04-01")
        a = R.assess(d, q, ex)
        b = R.assess(d, q, ex)
        self.assertEqual(a.score, b.score)
        self.assertEqual(a.components, b.components)
        self.assertEqual(a.methodology_id, b.methodology_id)
        self.assertEqual(a.cls, b.cls)

    def test_REL_02_class_boundaries(self):
        """REL-02: R = 0,82 → DIRECT; R = 0,59 → BELOW_THRESHOLD; 0,60 → ADJACENT."""
        self.assertEqual(R.classify(0.82), "DIRECT")
        self.assertEqual(R.classify(0.80), "DIRECT")
        self.assertEqual(R.classify(0.79), "ADJACENT")
        self.assertEqual(R.classify(0.60), "ADJACENT")
        self.assertEqual(R.classify(0.59), "BELOW_THRESHOLD")

    def test_REL_01_components_persisted(self):
        """ИД-01: все шесть компонент и версия методики сохраняются в БД."""
        rid = self.make_research()
        did = self.add_doc(rid, "Тропосферная связь: компоненты")
        row = db.one("SELECT * FROM search_results WHERE document_id=?", (did,))
        for col in ("score_s", "score_t", "score_c", "score_e", "score_k", "score_f"):
            self.assertIsNotNone(row[col], col)
        self.assertIn(row["relevance_class"], ("DIRECT", "ADJACENT", "BELOW_THRESHOLD"))
        self.assertIsNotNone(row["methodology_version"])


class FEASTests(BaseCase):
    FACTORS = [("k1", 0.15), ("k2", 0.15), ("k3", 0.15), ("k4", 0.15), ("k5", 0.10),
               ("k6", 0.10), ("k7", 0.10), ("k8", 0.05), ("k9", 0.05)]

    def _factors(self, unknown: set[str], value: float = 0.8) -> list[dict]:
        out = []
        for code, w in self.FACTORS:
            known = code not in unknown
            out.append({"code": code, "name": code, "weight": w,
                        "assessment": "confirmed" if known else "unknown",
                        "x": value if known else None})
        return out

    def test_FEAS_01_unknown_factors_excluded(self):
        """FEAS-01: 9 факторов, 4 неизвестны → F по доступным, C < 1."""
        rid = self.make_research()
        unknown = {"k5", "k6", "k7", "k8"}
        res = F.compute(rid, factors=self._factors(unknown))
        known_w = sum(w for c, w in self.FACTORS if c not in unknown)
        total_w = sum(w for _, w in self.FACTORS)
        self.assertAlmostEqual(res["coverage"], round(known_w / total_w, 4), places=6)
        self.assertLess(res["coverage"], 1.0)
        self.assertAlmostEqual(res["score"], 80.0, places=6)
        self.assertEqual(set(res["unknown_factors"]), unknown)
        row = db.one("SELECT * FROM analytics_feasibility WHERE id=?", (res["id"],))
        self.assertEqual(row["score"], res["score"])
        for f in res["factors"]:
            self.assertEqual(f["is_available"], f["code"] not in unknown)

    def test_FEAS_02_repeatable(self):
        """FEAS-02: повторный расчёт на тех же входах даёт идентичный результат."""
        rid = self.make_research()
        fs = self._factors({"k3", "k9"})
        a = F.compute(rid, factors=[dict(f) for f in fs])
        b = F.compute(rid, factors=[dict(f) for f in fs])
        self.assertEqual(a["score"], b["score"])
        self.assertEqual(a["coverage"], b["coverage"])
        self.assertEqual(a["range"], b["range"])
        self.assertEqual(a["input_hash"], b["input_hash"])

    def test_FEAS_03_all_unknown_gives_null(self):
        """ИД-02: все факторы неизвестны → F = NULL (не ноль), C = 0."""
        rid = self.make_research()
        res = F.compute(rid, factors=self._factors({c for c, _ in self.FACTORS}))
        self.assertIsNone(res["score"])
        self.assertEqual(res["coverage"], 0.0)
        row = db.one("SELECT score, coverage, interpretation_allowed FROM analytics_feasibility WHERE id=?", (res["id"],))
        self.assertIsNone(row["score"])
        self.assertEqual(row["interpretation_allowed"], 0)

    def test_FEAS_04_negative_value_is_assessment(self):
        """Подтверждённое отрицательное значение — оценка, а не пропуск."""
        rid = self.make_research()
        fs = self._factors(set())
        fs[0]["x"] = 0.0
        res = F.compute(rid, factors=fs)
        self.assertEqual(res["coverage"], 1.0)
        self.assertLess(res["score"], 80.0)
        self.assertEqual(res["unknown_factors"], [])

    def test_FEAS_05_low_coverage_warning(self):
        """Недостаточное покрытие → предупреждение и ограничение интерпретации."""
        rid = self.make_research()
        res = F.compute(rid, factors=self._factors({"k1", "k2", "k3", "k4", "k5", "k6"}))
        self.assertFalse(res["interpretation_allowed"])
        self.assertTrue(res["coverage_warning"])


class DEDUPTests(BaseCase):
    def test_DEDUP_01_preprint_and_published_are_linked(self):
        """DEDUP-01: препринт и публикация — два вхождения и один кластер со связью."""
        rid = self.make_research()
        published = _doc("Тропосферный модем: результаты испытаний",
                         "https://journal.example/article-1", doc_type="article",
                         evidence_class="primary_peer_reviewed", published_at="2022-01-01",
                         authors=["Петров П.П."])
        preprint = _doc("Тропосферный модем: результаты испытаний",
                        "https://arxiv.example/abs/2201.00001", doc_type="preprint",
                        evidence_class="preprint", published_at="2022-01-01",
                        authors=["Петров П.П."])
        a = DD.store(rid, published)
        b = DD.store(rid, preprint)
        self.assertTrue(a["new_document"])
        self.assertEqual(b["relation"], "PREPRINT_OF")
        self.assertIsNotNone(b["cluster_id"])
        clusters = DD.clusters(rid)
        self.assertEqual(len(clusters), 1)
        relations = {r["relation_type"] for r in db.query("SELECT relation_type FROM content_relations")}
        self.assertIn("PREPRINT_OF", relations)
        occ = db.count("content_occurrences", "research_id=?", (rid,))
        self.assertEqual(occ, 2)

    def test_DEDUP_02_five_urls_one_document(self):
        """Т-006/DEDUP-02: 5 URL → 5 вхождений, один логический документ, происхождение сохранено."""
        rid = self.make_research()
        ids = set()
        for i in range(5):
            d = _doc("Единый материал о загоризонтной связи",
                     f"https://mirror{i}.example/paper", doc_type="article",
                     evidence_class="primary_peer_reviewed", published_at="2021-03-01",
                     authors=["Сидоров С.С."], source_code=f"SRC-{i:04d}")
            res = DD.store(rid, d)
            ids.add(res["document_id"])
        self.assertEqual(len(ids), 1)
        self.assertEqual(db.count("content_occurrences", "research_id=?", (rid,)), 5)
        sm = DD.summary(rid)
        self.assertEqual(sm["logical_documents"], 1)
        self.assertEqual(sm["occurrences"], 5)
        self.assertEqual(sm["merged"], 4)
        urls = {r["url"] for r in db.query("SELECT url FROM content_occurrences WHERE research_id=?", (rid,))}
        self.assertEqual(len(urls), 5)

    def test_DEDUP_03_blob_uniqueness(self):
        """Уникальность SHA-256 — на физическом содержимом, не на логическом документе."""
        rid = self.make_research()
        d1 = _doc("Материал А", "https://a.example/1", published_at="2020-01-01")
        d2 = _doc("Материал А", "https://b.example/2", published_at="2020-01-01")
        r1, r2 = DD.store(rid, d1), DD.store(rid, d2)
        self.assertEqual(r1["content_sha256"], r2["content_sha256"])
        self.assertEqual(db.count("content_blobs", "content_sha256=?", (r1["content_sha256"],)), 1)


class DOCStatusTests(BaseCase):
    def test_DOC_01_extraction_and_relevance_independent(self):
        """DOC-01: EXTRACTED + BELOW_THRESHOLD — не противоречие."""
        rid = self.make_research()
        did = self.add_doc(rid, "Нерелевантный материал", extraction_status="EXTRACTED",
                           cls="BELOW_THRESHOLD", score=0.2)
        d = db.one("SELECT extraction_status FROM content_documents WHERE id=?", (did,))
        r = db.one("SELECT relevance_class FROM search_results WHERE document_id=?", (did,))
        self.assertEqual(d["extraction_status"], "EXTRACTED")
        self.assertEqual(r["relevance_class"], "BELOW_THRESHOLD")

    def test_DOC_02_one_document_two_researches(self):
        """DOC-02: один документ участвует в разных исследованиях с разными классами."""
        r1, r2 = self.make_research(title="Исследование 1"), self.make_research(title="Исследование 2")
        d = _doc("Общий документ о тропосферной связи", "https://shared.example/doc",
                 published_at="2019-01-01", authors=["Общий А.А."])
        a = DD.store(r1, d)
        b = DD.store(r2, norm.normalize(Document(
            document_id=new_id("doc-"), source_code="SRC-0451", connector_code="CON-TEST",
            external_id="shared-2", title="Общий документ о тропосферной связи",
            url="https://shared.example/doc", abstract="Общий документ о тропосферной связи",
            published_at="2019-01-01", authors=["Общий А.А."])))
        self.assertEqual(a["document_id"], b["document_id"])
        for rid, cls, score in ((r1, "DIRECT", 0.9), (r2, "BELOW_THRESHOLD", 0.3)):
            db.insert("search_results", {
                "id": new_id("rel-"), "research_id": rid, "document_id": a["document_id"],
                "relevance_score": score, "relevance_class": cls, "decision": "INCLUDE",
                "methodology_version": "test", "created_at": iso_now()})
        rows = db.query("SELECT research_id, relevance_class FROM search_results WHERE document_id=? ORDER BY relevance_score DESC",
                        (a["document_id"],))
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["relevance_class"] for r in rows}, {"DIRECT", "BELOW_THRESHOLD"})

    def test_DOC_03_manual_exclusion_keeps_class(self):
        """Решение о включении хранится отдельно от класса (КИ-005)."""
        from isheika.api import service as S
        rid = self.make_research()
        did = self.add_doc(rid, "Релевантный, но исключённый аналитиком", cls="DIRECT", score=0.91)
        S.exclude_document(did, "дубль по содержанию", actor="tester", research_id=rid)
        row = db.one("SELECT relevance_class, decision FROM search_results WHERE document_id=? AND research_id=?", (did, rid))
        self.assertEqual(row["relevance_class"], "DIRECT")
        self.assertEqual(row["decision"], "MANUAL_EXCLUDE")


class TRLTests(BaseCase):
    def test_TRL_01_mandatory_gap_blocks_level(self):
        """TRL-01: нет обязательного критерия TRL5 → уровень < 5, даже если TRL6 подтверждён."""
        rid = self.make_research()
        for i in range(3):
            self.add_doc(rid, f"Тропосферная связь: лабораторный макет {i}",
                         abstract="Эксперимент, измеренные значения, лабораторный макет, интегрированная сборка.",
                         evidence_class="primary_report", group=f"g{i}")
        signals = {}
        for lv in range(1, 10):
            for idx in (1, 2):
                code = f"TRL{lv}-C{idx:02d}"
                docs = db.query("SELECT id FROM research_documents WHERE research_id=?", (rid,))
                signals[code] = {"observed": True, "document_ids": [d["id"] for d in docs],
                                 "producer": "test"}
        # обязательный критерий уровня 5 не подтверждён
        signals["TRL5-C01"] = {"observed": False, "document_ids": [], "producer": "test"}
        res = T.compute(rid, signals=signals)
        self.assertLess(res["trl"], 5)
        self.assertTrue(any(g["criterion_code"] == "TRL5-C01" for g in res["gaps"]))

    def test_TRL_02_averaging_rejected(self):
        """TRL-02: усреднение уровней отклоняется валидатором."""
        with self.assertRaises(CoreError):
            T.validate_no_averaging({"method": "average", "trl": 5})
        with self.assertRaises(CoreError):
            T.validate_no_averaging({"aggregation": "mean_of_models", "trl": 6})
        with self.assertRaises(CoreError):
            T.validate_no_averaging({"trl": 7})            # уровень без проверки критериев
        T.validate_no_averaging({"method": "max_level_with_mandatory_criteria", "trl": 4,
                                 "criteria": [{"criterion_code": "TRL4-C01", "confirmed": True}]})

    def test_TRL_03_criterion_codes_stable(self):
        """ИД-08: критерии имеют стабильные идентификаторы TRL<n>-C<nn>."""
        cat = T.criteria_catalog()
        self.assertTrue(cat)
        for c in cat:
            self.assertRegex(c["criterion_code"], r"^TRL[1-9]-C\d{2}$")
        rid = self.make_research()
        self.add_doc(rid, "Тропосферная связь: принципы", abstract="Базовые принципы и концепция.")
        res = T.compute(rid)
        ev = T.criterion_evidence(res["id"])
        self.assertTrue(ev)
        self.assertTrue(all(e["criterion_code"].startswith("TRL") for e in ev))


class METHTests(BaseCase):
    def test_METH_01_new_version_keeps_history(self):
        """METH-01: изменение весов создаёт новую версию; старый результат связан со старой."""
        rid = self.make_research()
        fs = [{"code": c, "name": c, "weight": w, "assessment": "confirmed", "x": 0.7}
              for c, w in FEASTests.FACTORS]
        first = F.compute(rid, factors=[dict(f) for f in fs])
        old_id = first["methodology_id"]
        cur = M.by_id(old_id)
        new_factors = [dict(f, weight=f["weight"] * 1.1) for f in cur["parameters"]["factors"]]
        new = M.create_version("FEASIBILITY", parameters={"factors": new_factors},
                               author="tester", description="Тест METH-01")
        self.assertNotEqual(new["code"], cur["code"])
        self.assertTrue(new["code"].startswith("FEASIBILITY_V"))
        second = F.compute(rid, factors=[dict(f) for f in fs])
        self.assertEqual(second["methodology_id"], new["id"])
        old_row = db.one("SELECT methodology_id FROM analytics_feasibility WHERE id=?", (first["id"],))
        self.assertEqual(old_row["methodology_id"], old_id)
        self.assertEqual(db.count("analytics_feasibility", "research_id=?", (rid,)), 2)
        self.assertFalse(M.by_id(old_id)["is_active"])

    def test_METH_02_repeatability_precision(self):
        """METH-02: повторный расчёт совпадает с точностью до 1e-9."""
        rid = self.make_research()
        fs = [{"code": c, "name": c, "weight": w, "assessment": "confirmed", "x": 0.63}
              for c, w in FEASTests.FACTORS]
        a = F.compute(rid, factors=[dict(f) for f in fs])
        b = F.compute(rid, factors=[dict(f) for f in fs])
        self.assertLess(abs(a["score"] - b["score"]), 1e-9)
        self.assertLess(abs(a["coverage"] - b["coverage"]), 1e-9)

    def test_METH_03_registry_fields(self):
        """ИД-09: обязательные поля реестра методик заполнены."""
        for m in M.listing():
            for field in ("code", "version", "formula_definition", "parameters", "thresholds",
                          "valid_from", "approval_status", "config_checksum"):
                self.assertIsNotNone(m[field], f"{m['code']}.{field}")
            self.assertIn(m["approval_status"], ("PROVISIONAL", "VALIDATED", "DEPRECATED"))


class FCSTTests(BaseCase):
    def test_FCST_01_long_horizon_is_scenario(self):
        """FCST-01: 40 лет, внутреннее 0,734821 → SCENARIO без точечного процента."""
        point = {"years_from": 35, "years_to": 50, "forecast_horizon_years": 40,
                 "probability_value": 0.734821, "probability_lower": 0.4, "probability_upper": 0.95}
        pres = FC.presentation_for(point, calibrated=True)
        self.assertEqual(pres["mode"], "SCENARIO")
        self.assertIsNone(pres["display_value"])
        self.assertNotIn("73.48", pres["display_text"])
        self.assertNotIn("73,48", pres["display_text"])
        self.assertTrue(pres["warning_text"])

    def test_FCST_02_presentation_policy_by_horizon(self):
        """FCST-02: режим и точность определяются сервером для каждой полосы."""
        cases = [(0, 2, "INTERVAL"), (2, 5, "INTERVAL"), (5, 10, "INTERVAL"),
                 (10, 20, "COARSE"), (20, 35, "SCENARIO"), (35, 50, "SCENARIO")]
        for lo, hi, mode in cases:
            pres = FC.presentation_for({"years_from": lo, "years_to": hi, "probability_value": 0.5,
                                        "probability_lower": 0.2, "probability_upper": 0.8},
                                       calibrated=False)
            self.assertEqual(pres["mode"], mode, f"{lo}–{hi}")
            if mode == "SCENARIO":
                self.assertIsNone(pres["display_value"])
                self.assertEqual(pres["precision"], -1)
        exact = FC.presentation_for({"years_from": 0, "years_to": 2, "probability_value": 0.5,
                                     "probability_lower": 0.3, "probability_upper": 0.7}, calibrated=True)
        self.assertEqual(exact["mode"], "EXACT")

    def test_FCST_03_points_stored_with_policy(self):
        """ИД-05: точки прогноза хранят внутреннее значение и режим представления."""
        rid = self.make_research()
        self.add_doc(rid, "Тропосферная связь: прогноз")
        T.compute(rid)
        F.compute(rid)
        res = FC.compute(rid)
        rows = db.query("SELECT * FROM forecast_points WHERE forecast_id=?", (res["id"],))
        self.assertTrue(rows)
        for r in rows:
            self.assertIn(r["display_mode"], ("EXACT", "INTERVAL", "COARSE", "SCENARIO"))
            if r["forecast_horizon_years"] > 20:
                self.assertEqual(r["display_mode"], "SCENARIO")
                self.assertIsNone(r["display_value"])
        self.assertTrue(res["monotonic_ok"])


class SEPTests(BaseCase):
    def test_SEP_01_feasibility_probability_confidence_separate(self):
        """SEP-01: F, P(T≤t) и уверенность — три разные записи в разных таблицах."""
        rid = self.make_research()
        did = self.add_doc(rid, "Тропосферная связь: разделённые показатели")
        cid = self.add_claim(rid, "Достигнута передача данных")
        self.add_evidence(rid, cid, did)
        fs = [{"code": c, "name": c, "weight": w, "assessment": "confirmed", "x": 0.8}
              for c, w in FEASTests.FACTORS]
        fea = F.compute(rid, factors=fs)
        T.compute(rid)
        fct = FC.compute(rid)
        conf = CF.compute(rid, "feasibility", subject_id=fea["id"], coverage=fea["coverage"])
        self.assertEqual(fea["score"], 80.0)
        self.assertIsNotNone(db.one("SELECT id FROM analytics_feasibility WHERE id=?", (fea["id"],)))
        self.assertIsNotNone(db.one("SELECT id FROM forecast_runs WHERE id=?", (fct["id"],)))
        self.assertIsNotNone(db.one("SELECT id FROM analytics_confidence WHERE id=?", (conf["id"],)))
        self.assertNotEqual(conf["confidence"], fea["score"] / 100)

    def test_SEP_02_api_returns_separate_indicators(self):
        """SEP-02/КИ-014: API отдаёт показатели раздельно, без объединённого индикатора."""
        from isheika.api import service as S
        rid = self.make_research()
        self.add_doc(rid, "Тропосферная связь: панель показателей")
        T.compute(rid)
        F.compute(rid)
        FC.compute(rid)
        CF.compute_all(rid)
        bundle = S.analytics_bundle(rid)
        for key in ("trl", "feasibility", "forecast", "confidence"):
            self.assertIn(key, bundle)
        self.assertIsInstance(bundle["confidence"], list)


class EVIDTests(BaseCase):
    def test_EVID_01_reprints_one_group(self):
        """EVID-01: 5 перепечаток одного пресс-релиза → одна группа независимости."""
        rid = self.make_research()
        primary_url = "https://lab.example/press-release-1"
        primary = self.add_doc(rid, "Лаборатория заявила о достижении", url=primary_url,
                               evidence_class="press_release", doc_type="press_release",
                               group="org:lab", origin_class="PRIMARY")
        for i in range(5):
            self.add_doc(rid, f"Новость {i}: лаборатория заявила о достижении",
                         url=f"https://news{i}.example/story", evidence_class="media",
                         doc_type="news", group=f"dom:news{i}",
                         identifiers={"derived_from": primary_url})
        res = E.assign_independence(rid)
        groups = db.query("SELECT * FROM evidence_independence_groups WHERE research_id=?", (rid,))
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["members"], 6)
        self.assertEqual(res["reprints"], 0)  # явная ссылка на первоисточник, не отпечаток
        docs = db.query("SELECT origin_class FROM research_documents WHERE research_id=?", (rid,))
        self.assertEqual(sum(1 for d in docs if d["origin_class"] == "REPRINT"), 5)

    def test_EVID_02_independent_confirmation_adds_group(self):
        """EVID-02: независимое подтверждение другой лаборатории увеличивает покрытие."""
        rid = self.make_research()
        self.add_doc(rid, "Первичное сообщение о результате", url="https://lab1.example/pr",
                     evidence_class="press_release", doc_type="press_release", group="org:lab1")
        before = E.assign_independence(rid)["groups"]
        self.add_doc(rid, "Независимое воспроизведение результата другой группой",
                     url="https://lab2.example/paper", evidence_class="primary_peer_reviewed",
                     doc_type="article", group="org:lab2", org="Другая лаборатория")
        after = E.assign_independence(rid)["groups"]
        self.assertEqual(after, before + 1)
        E.build_evidence(rid)                     # контур: документы → доказательства
        conf = CF.compute(rid, "trl")
        self.assertEqual(conf["independent_groups"], after)
        self.assertGreater(conf["evidence_count"], 0)


class REPRTests(BaseCase):
    def test_REPR_01_replay_identical(self):
        """REPR-01: повторный расчёт по снимку даёт идентичный результат."""
        rid = self.make_research()
        fs = [{"code": c, "name": c, "weight": w, "assessment": "confirmed", "x": 0.55}
              for c, w in FEASTests.FACTORS]
        res = F.compute(rid, factors=fs)
        rep = SNAP.replay("feasibility", res["id"])
        self.assertTrue(rep["identical"], rep)

    def test_REPR_02_old_result_reproducible_after_version_change(self):
        """REPR-02: после смены методики старый результат воспроизводится по исходной версии."""
        rid = self.make_research()
        fs = [{"code": c, "name": c, "weight": w, "assessment": "confirmed", "x": 0.42}
              for c, w in FEASTests.FACTORS]
        res = F.compute(rid, factors=fs)
        cur = M.active("FEASIBILITY")
        new_factors = [dict(f, weight=f["weight"] * 2) for f in cur["parameters"]["factors"]]
        M.create_version("FEASIBILITY", parameters={"factors": new_factors}, author="tester",
                         description="Тест REPR-02")
        rep = SNAP.replay("feasibility", res["id"])
        self.assertTrue(rep["identical"], rep)
        self.assertEqual(rep["methodology_id"], res["methodology_id"])

    def test_REPR_03_snapshot_fields_present(self):
        """ИД-12: обязательные поля снимка присутствуют в записи расчёта."""
        rid = self.make_research()
        self.add_doc(rid, "Тропосферная связь: снимок")
        res = F.compute(rid)
        row = db.one("SELECT * FROM analytics_feasibility WHERE id=?", (res["id"],))
        for field in ("document_set_version", "methodology_id", "methodology_version",
                      "input_snapshot", "parameters", "config_checksum", "input_hash",
                      "output_hash", "assessed_by", "created_at"):
            self.assertIsNotNone(row[field], field)
        self.assertTrue(json.loads(row["input_snapshot"]))

    def test_REPR_04_report_shows_bound_methodology(self):
        """ИД-09/ИД-12: отчёт показывает версию, связанную с результатом, а не текущую активную."""
        from isheika.reports import builder as RB
        rid = self.make_research()
        fs = [{"code": c, "name": c, "weight": w, "assessment": "confirmed", "x": 0.5}
              for c, w in FEASTests.FACTORS]
        res = F.compute(rid, factors=fs)
        bound = res["methodology_id"]
        cur = M.by_id(bound)
        M.create_version("FEASIBILITY",
                         parameters={"factors": [dict(f, weight=f["weight"] * 3)
                                                 for f in cur["parameters"]["factors"]]},
                         author="tester", description="Тест REPR-04")
        data = RB.collect(rid)
        reg = data["methodology_registry"]["FEASIBILITY"]
        self.assertEqual(reg["id"], bound)
        self.assertEqual(reg["source"], "result")
        self.assertNotEqual(reg["id"], M.active("FEASIBILITY")["id"])
        html_text = RB.build_html(data)
        self.assertIn(reg["code"], html_text)


class APITests(BaseCase):
    def test_API_01_canonical_catalog_in_openapi(self):
        """API-01: все канонические маршруты зарегистрированы и описаны в OpenAPI 3.1."""
        from isheika.api import openapi as OA, server as SV
        self.assertEqual(OA.missing_canonical(SV.ROUTES), [])
        spec = OA.build_spec(SV.ROUTES)
        self.assertEqual(spec["openapi"], "3.1.0")
        for path in OA.CANONICAL:
            self.assertIn(path, spec["paths"])
        self.assertIn("SearchResult", spec["components"]["schemas"])
        self.assertIn("Error", spec["components"]["schemas"])

    def test_API_02_legacy_route_gone(self):
        """API-02: старый маршрут /api/v1/research возвращает 410 Gone с новым путём."""
        from isheika.api import server as SV
        legacy = [(meth, pat, fn) for meth, pat, fn in SV.ROUTES
                  if pat.pattern == r"^/api/v1/research$"]
        self.assertTrue(legacy)
        meth, pat, fn = legacy[0]
        with self.assertRaises(CoreError) as ctx:
            fn(None, pat.match("/api/v1/research"), {})
        self.assertEqual(ctx.exception.error.code, "E_GONE")
        self.assertEqual(ctx.exception.error.details.get("new_path"), "/api/v1/researches")
        self.assertTrue(ctx.exception.error.details.get("sunset"))
