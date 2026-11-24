"""Испытания следующего этапа ROADMAP: P4 (граф связей, сравнение версий) и P6 (трассировка, метрики).

Идентификаторы: GRAPH-01/02, DIFF-01/02/03, TRACE-01/02/03, METR-01/02, MIGR-01.
Проверяется прохождение данных через контур, а не отдельная функция.
"""
from __future__ import annotations

import json

from isheika import telemetry
from isheika.analytics import feasibility as F, methodologies as M, snapshot as SNAP, trl as T
from isheika.api import service as S
from isheika.contracts import CoreError, iso_now, new_id
from isheika.search import dedup as DD, normalize as norm
from isheika.storage import db
from isheika.workflow import engine as W, events
from tests.base import BaseCase
from tests.test_change_register import FEASTests, _doc


class GRAPHTests(BaseCase):
    def _chain(self, rid: str) -> None:
        published = _doc("Тропосферный модем: граф связей", "https://journal.example/g1",
                         doc_type="article", evidence_class="primary_peer_reviewed",
                         published_at="2022-01-01", authors=["Петров П.П."])
        preprint = _doc("Тропосферный модем: граф связей", "https://arxiv.example/abs/g1",
                        doc_type="preprint", evidence_class="preprint",
                        published_at="2022-01-01", authors=["Петров П.П."])
        DD.store(rid, published)
        DD.store(rid, preprint)
        self.add_doc(rid, "Отдельный материал о загоризонтной связи", url="https://other.example/g2")

    def test_GRAPH_01_nodes_edges_and_isolated(self):
        """GRAPH-01: граф содержит узлы, типизированные рёбра и счётчик изолированных узлов."""
        rid = self.make_research()
        self._chain(rid)
        g = S.document_graph(rid)
        self.assertEqual(len(g["nodes"]), 3)
        self.assertEqual(len(g["edges"]), 1)
        self.assertEqual(g["edges"][0]["type"], "PREPRINT_OF")
        self.assertEqual(g["isolated"], 1)
        self.assertGreaterEqual(g["clusters"], 1)
        self.assertTrue(all({"id", "title", "occurrences"} <= set(n) for n in g["nodes"]))

    def test_GRAPH_02_type_filter_applied_on_server(self):
        """GRAPH-02: фильтр типов применяется на сервере, браузер получает уже отфильтрованный граф."""
        rid = self.make_research()
        self._chain(rid)
        g = S.document_graph(rid, types=["TRANSLATION_OF"])
        self.assertEqual(g["edges"], [])
        self.assertEqual(len(g["nodes"]), 3)          # узлы сохраняются, рёбра отфильтрованы
        self.assertTrue(any(t["type"] == "PREPRINT_OF" and not t["selected"] for t in g["types"]))
        g2 = S.document_graph(rid, types=["PREPRINT_OF"])
        self.assertEqual(len(g2["edges"]), 1)


class DIFFTests(BaseCase):
    def _two_versions(self, rid: str, x1: float, x2: float) -> tuple[dict, dict]:
        fs = [{"code": c, "name": c, "weight": w, "assessment": "confirmed", "x": x1}
              for c, w in FEASTests.FACTORS]
        first = F.compute(rid, factors=fs)
        cur = M.by_id(first["methodology_id"])
        M.create_version("FEASIBILITY",
                         parameters={"factors": [dict(f, weight=f["weight"] * 1.5)
                                                 for f in cur["parameters"]["factors"]]},
                         author="tester", description="Тест DIFF")
        fs2 = [dict(f, x=x2) for f in fs]
        second = F.compute(rid, factors=fs2)
        return first, second

    def test_DIFF_01_values_and_methodology(self):
        """DIFF-01: сравнение показывает изменение значений и версии методики."""
        rid = self.make_research()
        a, b = self._two_versions(rid, 0.4, 0.8)
        d = S.assessment_diff("feasibility", a["id"], b["id"])
        self.assertTrue(d["methodology_changed"])
        self.assertFalse(d["identical_result"])
        score = next(x for x in d["deltas"] if x["field"] == "score")
        self.assertTrue(score["changed"])
        self.assertAlmostEqual(score["delta"], 40.0, places=6)
        self.assertEqual(len(d["factors"]), 9)
        self.assertTrue(all(f["changed"] for f in d["factors"]))

    def test_DIFF_02_identical_results(self):
        """DIFF-02: повторный расчёт на тех же входах — результаты идентичны."""
        rid = self.make_research()
        fs = [{"code": c, "name": c, "weight": w, "assessment": "confirmed", "x": 0.5}
              for c, w in FEASTests.FACTORS]
        a = F.compute(rid, factors=[dict(f) for f in fs])
        b = F.compute(rid, factors=[dict(f) for f in fs])
        d = S.assessment_diff("feasibility", a["id"], b["id"])
        self.assertTrue(d["identical_result"])
        self.assertFalse(d["methodology_changed"])
        self.assertFalse(any(x["changed"] for x in d["deltas"]))

    def test_DIFF_03_trl_criteria_and_guards(self):
        """DIFF-03: сравнение TRL показывает изменившиеся критерии; чужие исследования запрещены."""
        rid = self.make_research()
        self.add_doc(rid, "Тропосферная связь: принципы", abstract="Базовые принципы и концепция.")
        a = T.compute(rid)
        docs = db.query("SELECT id FROM research_documents WHERE research_id=?", (rid,))
        signals = {f"TRL{lv}-C{i:02d}": {"observed": True, "document_ids": [d["id"] for d in docs],
                                         "producer": "test"}
                   for lv in range(1, 5) for i in (1, 2)}
        b = T.compute(rid, signals=signals)
        d = S.assessment_diff("trl", a["id"], b["id"])
        self.assertIn("criteria", d)
        self.assertNotEqual(d["a"]["output_hash"], d["b"]["output_hash"])
        other = self.make_research()
        c = F.compute(other)
        with self.assertRaises(CoreError):
            S.assessment_diff("feasibility", a["id"], c["id"])
        with self.assertRaises(CoreError):
            S.assessment_diff("nope", a["id"], b["id"])


class TRACETests(BaseCase):
    def test_TRACE_01_events_and_audit_carry_correlation(self):
        """TRACE-01: события и аудит внутри запроса помечаются общим correlation_id."""
        with telemetry.scope(request="req-test-0001", correlation="cid-test-0001"):
            rid = self.make_research()
            ev = events.emit("system.warning", research_id=rid, payload={"test": True})
        self.assertEqual(ev["correlation_id"], "cid-test-0001")
        self.assertEqual(ev["request_id"], "req-test-0001")
        row = db.one("SELECT correlation_id FROM audit_log WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (rid,))
        self.assertEqual(row["correlation_id"], "cid-test-0001")
        tr = S.trace("cid-test-0001")
        self.assertGreaterEqual(len(tr["events"]), 1)
        self.assertIn(rid, tr["research_ids"])

    def test_TRACE_02_background_run_inherits_correlation(self):
        """TRACE-02: фоновый запуск наследует трассировку; этапы пишут длительность."""
        from isheika.workflow import pipeline  # noqa: F401  (регистрация обработчиков этапов)
        from isheika.config import SETTINGS
        SETTINGS.network_enabled = False        # автономный контур: имитационный коннектор
        rid = self.make_research()
        with telemetry.scope(correlation="cid-run-0001"):
            W.start(rid)
        import time
        for _ in range(600):
            row = db.one("SELECT status FROM core_researches WHERE id=?", (rid,)) or {}
            if row.get("status") in ("completed", "partial", "failed"):
                break
            time.sleep(0.05)
        SETTINGS.network_enabled = True
        jobs = db.query("SELECT stage, correlation_id, duration_ms, status FROM workflow_jobs WHERE research_id=?", (rid,))
        started = [j for j in jobs if j["status"] in ("completed", "partial", "failed")]
        self.assertTrue(started)
        self.assertTrue(all(j["correlation_id"] == "cid-run-0001" for j in started))
        self.assertTrue(all(j["duration_ms"] is not None and j["duration_ms"] >= 0 for j in started))
        tr = S.trace("cid-run-0001")
        self.assertGreaterEqual(len(tr["jobs"]), 1)
        self.assertGreaterEqual(len(tr["events"]), 1)

    def test_TRACE_03_external_id_sanitized(self):
        """TRACE-03: внешний идентификатор принимается только в безопасном формате."""
        self.assertIsNone(telemetry.sanitize("<script>alert(1)</script>"))
        self.assertIsNone(telemetry.sanitize("x"))
        self.assertEqual(telemetry.sanitize("req-abc-123"), "req-abc-123")
        with self.assertRaises(CoreError):
            S.trace("'; DROP TABLE audit_log; --")


class METRTests(BaseCase):
    def test_METR_01_stage_latency_and_partial_share(self):
        """METR-01: /metrics отдаёт латентность этапов и долю partial (P6)."""
        from isheika.api.metrics import render
        rid = self.make_research()
        W.create_workflow(rid)
        job = db.one("SELECT id FROM workflow_jobs WHERE research_id=? LIMIT 1", (rid,))
        W.set_job_state(job["id"], "running")
        W.set_job_state(job["id"], "partial", reason="Не все источники ответили")
        text = render()
        self.assertIn("isheika_workflow_stage_duration_ms_avg", text)
        self.assertIn("isheika_workflow_stage_duration_ms_max", text)
        self.assertIn("isheika_workflow_partial_share", text)
        self.assertIn("isheika_traced_events_total", text)
        for line in text.splitlines():
            if line.startswith("isheika_workflow_partial_share "):
                self.assertGreaterEqual(float(line.split()[-1]), 0.0)

    def test_METR_02_api_call_latency_by_target(self):
        """METR-02: средняя длительность вызовов внешних API по источникам."""
        from isheika.api.metrics import render
        from isheika.search import http as H
        with telemetry.scope(correlation="cid-api-0001"):
            H._log_api("search", "SRC-TEST", "https://example.org/api?key=secret", 200, 123, 4096, False, None)
        row = db.one("SELECT * FROM audit_api_calls WHERE target='SRC-TEST'")
        self.assertEqual(row["correlation_id"], "cid-api-0001")
        self.assertNotIn("secret", row["url"])
        self.assertIn("isheika_api_calls_duration_ms_avg", render())


class MIGRTests(BaseCase):
    def test_MIGR_01_observability_columns_idempotent(self):
        """MIGR-01: миграция 0003 добавляет колонки трассировки и повторный запуск безопасен."""
        from isheika.storage import migrate
        conn = db.connect()
        res = migrate.migrate_0003_observability(conn)
        self.assertEqual(res["columns_added"], [])      # уже применена при инициализации
        cols = {r["name"] for r in db.query("PRAGMA table_info(workflow_events)")}
        self.assertTrue({"correlation_id", "request_id"} <= cols)
        jcols = {r["name"] for r in db.query("PRAGMA table_info(workflow_jobs)")}
        self.assertTrue({"correlation_id", "duration_ms"} <= jcols)
        applied = {r["version"] for r in db.query("SELECT version FROM meta_migrations")}
        self.assertIn("0003_observability", applied)
