"""Испытания журнала действий и поиска противоречий (редакция 1.4.0).

JRN-01…14 — журнал: запись, трассировка, маскировка секретов, подпись дефекта,
группировка, отказоустойчивость записи, приём ошибок браузера, выгрузка, ротация.
DIA-01…19 — правила: каждое проверяется ВНЕСЕНИЕМ противоречия в данные,
а не только отсутствием находок на чистом состоянии.
"""
from __future__ import annotations

import json
import os
import types
from pathlib import Path

from isheika import diagnostics as DG, journal as J
from isheika.api import service as S
from isheika.config import DATA_DIR, SETTINGS
from isheika.contracts import CoreError, iso_now, new_id
from isheika.storage import db
from isheika import telemetry
from tests.base import BaseCase


class JournalTests(BaseCase):
    def test_JRN_01_record_carries_trace_and_filters(self):
        """JRN-01: запись несёт трассировку и находится фильтрами по уровню/виду/действию."""
        with telemetry.scope(request="req-jrn-0001", correlation="cid-jrn-0001"):
            jid = J.record("warn", "action", "test.filter", "проверка фильтра",
                           actor="tester", research_id="res-jrn-0001", entity_kind="test",
                           entity_id="x1", outcome="fail", error_code="E_TEST", duration_ms=12.5)
        self.assertTrue(jid)
        row = db.one("SELECT * FROM ops_journal WHERE id=?", (jid,))
        self.assertEqual(row["request_id"], "req-jrn-0001")
        self.assertEqual(row["correlation_id"], "cid-jrn-0001")
        self.assertEqual(row["level"], "warn")
        self.assertEqual(row["duration_ms"], 12.5)
        found = J.query(correlation_id="cid-jrn-0001")
        self.assertTrue(any(r["id"] == jid for r in found["items"]))
        self.assertTrue(any(r["id"] == jid for r in J.query(level="warn", kind="action")["items"]))
        self.assertTrue(any(r["id"] == jid for r in J.query(q="test.filter")["items"]))
        self.assertFalse(any(r["id"] == jid for r in J.query(kind="connector")["items"]))

    def test_JRN_02_secrets_are_masked_at_any_depth(self):
        """JRN-02: пароли, токены и ключи не попадают в журнал ни на какой глубине."""
        jid = J.record("error", "security", "test.secret", "Authorization: Bearer abcdef123456789",
                       detail={"password": "super-secret-1", "nested": {"api_key": "key-12345678"},
                               "list": [{"token": "tok-12345678"}],
                               "url": "https://api.example.org/x?api_key=abcdef123456&q=test"})
        row = db.one("SELECT * FROM ops_journal WHERE id=?", (jid,))
        blob = json.dumps(row, ensure_ascii=False)
        for leak in ("super-secret-1", "key-12345678", "tok-12345678", "abcdef123456789", "abcdef123456"):
            self.assertNotIn(leak, blob)
        self.assertIn(J.MASK, blob)
        self.assertEqual(J.redact({"password": "x"})["password"], J.MASK)
        self.assertIn("q=test", J.redact({"url": "https://x/y?api_key=zzzzzzzz&q=test"})["url"])

    def test_JRN_03_fingerprint_groups_same_bug(self):
        """JRN-03: одинаковые падения с разными идентификаторами — одна подпись дефекта."""
        f1 = J.fingerprint("api", "POST /researches", "ValueError", "E_INTERNAL",
                           "нет поля res-11111111-2222-3333-4444-555555555555 в 42 строке")
        f2 = J.fingerprint("api", "POST /researches", "ValueError", "E_INTERNAL",
                           "нет поля res-99999999-8888-7777-6666-555555555555 в 77 строке")
        f3 = J.fingerprint("api", "POST /reports", "KeyError", "E_INTERNAL", "другой дефект")
        self.assertEqual(f1, f2)
        self.assertNotEqual(f1, f3)
        for i in range(3):
            J.record("error", "api", "test.repeat", f"падение номер {i} res-{new_id()}",
                     error_type="ValueError", error_code="E_INTERNAL", stack="  File \"x.py\", line 10, in f\n")
        groups = J.errors(limit=100)["items"]
        g = next(x for x in groups if x["action"] == "test.repeat")
        self.assertGreaterEqual(g["occurrences"], 3)
        self.assertTrue(g["sample"]["stack"])

    def test_JRN_04_capture_measures_and_records_failure(self):
        """JRN-04: обёртка действия пишет длительность, а при отказе — traceback, и не глушит его."""
        with J.capture("action", "test.ok", actor="tester"):
            pass
        row = db.one("SELECT * FROM ops_journal WHERE action='test.ok' ORDER BY at DESC LIMIT 1")
        self.assertEqual(row["outcome"], "ok")
        self.assertIsNotNone(row["duration_ms"])
        with self.assertRaises(ValueError):
            with J.capture("action", "test.boom", actor="tester", research_id="res-jrn-0002"):
                raise ValueError("проверка отказа действия")
        row = db.one("SELECT * FROM ops_journal WHERE action='test.boom' ORDER BY at DESC LIMIT 1")
        self.assertEqual(row["level"], "error")
        self.assertEqual(row["outcome"], "fail")
        self.assertEqual(row["error_type"], "ValueError")
        self.assertIn("ValueError", row["stack"])
        self.assertIn("test_JRN_04", row["stack"])       # полный traceback, а не сообщение
        self.assertTrue(row["fingerprint"])

    def test_JRN_05_write_failure_does_not_break_operation(self):
        """JRN-05: сбой записи журнала не роняет операцию и не теряется молча."""
        from unittest import mock
        before = J.FAILED_WRITES
        with mock.patch.object(db, "insert", side_effect=RuntimeError("БД недоступна")):
            self.assertIsNone(J.record("error", "system", "test.db_down", "свидетельство отказа"))
        self.assertEqual(J.FAILED_WRITES, before + 1)
        path = os.path.join(DATA_DIR, "journal-fallback.log")
        self.assertTrue(os.path.isfile(path))
        with open(path, encoding="utf-8") as f:
            self.assertIn("test.db_down", f.read())

    def test_JRN_06_level_threshold_and_disable(self):
        """JRN-06: минимальный уровень записи и полное отключение журнала соблюдаются."""
        old_level, old_enabled = SETTINGS.journal_level, SETTINGS.journal_enabled
        try:
            SETTINGS.journal_level = "warn"
            self.assertIsNone(J.record("debug", "system", "test.debug_skip"))
            self.assertIsNone(J.record("info", "system", "test.info_skip"))
            self.assertTrue(J.record("error", "system", "test.error_kept"))
            SETTINGS.journal_enabled = False
            self.assertIsNone(J.record("error", "system", "test.disabled"))
        finally:
            SETTINGS.journal_level, SETTINGS.journal_enabled = old_level, old_enabled
        self.assertFalse(db.one("SELECT * FROM ops_journal WHERE action='test.debug_skip'"))
        self.assertFalse(db.one("SELECT * FROM ops_journal WHERE action='test.disabled'"))

    def test_JRN_07_domain_actions_reach_journal(self):
        """JRN-07: доменное действие (аудит) видно и в журнале действий."""
        from isheika.api import service as S
        rid = self.make_research()
        rows = J.query(kind="action", q="research.create")["items"]
        self.assertTrue(rows, "создание исследования не попало в журнал")
        self.assertTrue(any(r["research_id"] == rid or r["entity_id"] == rid for r in rows))

    def test_JRN_08_workflow_failures_reach_journal(self):
        """JRN-08: отказ этапа и предупреждение ИИ попадают в журнал с уровнем и кодом."""
        from isheika.workflow import events
        events.emit("job.failed", research_id="res-jrn-0003", job_id="job-jrn-0003", severity="error",
                    payload={"stage": "S07", "code": "E_NETWORK", "message": "источник недоступен",
                             "trace": "Traceback: строка 1"})
        events.emit("ai.schema_error", research_id="res-jrn-0003", severity="warning",
                    payload={"message": "ответ не по схеме", "code": "E_SCHEMA"})
        row = db.one("SELECT * FROM ops_journal WHERE action='job.failed' ORDER BY at DESC LIMIT 1")
        self.assertEqual(row["level"], "error")
        self.assertEqual(row["kind"], "workflow")
        self.assertEqual(row["error_code"], "E_NETWORK")
        self.assertEqual(row["job_id"], "job-jrn-0003")
        warn = db.one("SELECT * FROM ops_journal WHERE action='ai.schema_error' ORDER BY at DESC LIMIT 1")
        self.assertEqual(warn["level"], "warn")
        self.assertEqual(warn["kind"], "ai")

    def test_JRN_09_browser_events_validated_and_rate_limited(self):
        """JRN-09: ошибка браузера принимается без входа, но проверяется и ограничивается."""
        res = J.client_event({"level": "error", "kind": "ui", "action": "render.trl",
                              "message": "TypeError: x is undefined", "stack": "at trl (screens_core.js:1)",
                              "route": "#/trl"}, peer="203.0.113.7", user_agent="TestBrowser/1.0")
        self.assertTrue(res["accepted"])
        row = db.one("SELECT * FROM ops_journal WHERE id=?", (res["id"],))
        self.assertEqual(row["source"], "browser")
        self.assertEqual(row["level"], "error")
        self.assertTrue(row["fingerprint"])
        self.assertIn("TestBrowser", row["client"])
        with self.assertRaises(CoreError) as ctx:
            J.client_event({"level": "error"}, peer="203.0.113.8")
        self.assertEqual(ctx.exception.error.code, "E_VALIDATION")
        old = SETTINGS.journal_client_rate
        try:
            SETTINGS.journal_client_rate = 2
            for i in range(2):
                J.client_event({"message": f"событие {i}"}, peer="203.0.113.9")
            with self.assertRaises(CoreError) as ctx:
                J.client_event({"message": "сверх лимита"}, peer="203.0.113.9")
            self.assertEqual(ctx.exception.error.code, "E_RATE_LIMIT")
        finally:
            SETTINGS.journal_client_rate = old

    def test_JRN_10_export_formats_and_no_secrets(self):
        """JRN-10: выгрузка TXT/JSON/CSV содержит записи и не раскрывает секреты."""
        J.record("error", "api", "test.export", "падение для выгрузки", error_code="E_INTERNAL",
                 detail={"token": "tok-should-not-leak"})
        txt = J.export("txt", limit=100)
        self.assertIn("журнал действий", txt)
        self.assertIn("test.export", txt)
        data = json.loads(J.export("json", limit=100))
        self.assertTrue(data["items"])
        csv_text = J.export("csv", limit=100)
        self.assertIn("fingerprint", csv_text.splitlines()[0])
        self.assertIn("test.export", csv_text)
        for blob in (txt, csv_text, json.dumps(data, ensure_ascii=False)):
            self.assertNotIn("tok-should-not-leak", blob)

    def test_JRN_11_retention_prunes_by_age_and_cap(self):
        """JRN-11: политика хранения ограничивает журнал по сроку и по объёму."""
        from datetime import datetime, timedelta, timezone
        old = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat(timespec="seconds")
        old_id = new_id("jrn-")
        db.insert("ops_journal", {"id": old_id, "at": old, "level": "info", "kind": "system",
                                  "action": "test.old", "message": "старая запись", "source": "server",
                                  "detail": {}, "client": {}})
        res = J.prune(days=30)
        self.assertGreaterEqual(res["removed_by_age"], 1)
        self.assertFalse(db.one("SELECT * FROM ops_journal WHERE id=?", (old_id,)))
        total = db.count("ops_journal")
        res = J.prune(days=0, max_rows=max(1, total - 5))
        self.assertGreaterEqual(res["removed_by_cap"], 1)
        self.assertLessEqual(db.count("ops_journal"), max(1, total - 5))

    def test_JRN_12_entry_returns_trace_context(self):
        """JRN-12: запись отдаёт контекст своей трассировки; неизвестный id — 404."""
        with telemetry.scope(request="req-jrn-0012", correlation="cid-jrn-0012"):
            J.record("info", "action", "test.ctx.first", "первое действие")
            jid = J.record("error", "action", "test.ctx.second", "второе действие с отказом")
        entry = J.entry(jid)
        actions = [c["action"] for c in entry["context"]]
        self.assertIn("test.ctx.first", actions)
        self.assertIn("test.ctx.second", actions)
        with self.assertRaises(CoreError) as ctx:
            J.entry("jrn-none")
        self.assertEqual(ctx.exception.error.code, "E_NOT_FOUND")

    def test_JRN_13_rbac_journal_routes(self):
        """JRN-13: журнал читает роль с logs.read; приём ошибок браузера публичный."""
        from isheika.api import server as SRV, service as S
        req = types.SimpleNamespace(session={"role": "observer", "login": "observer"}, qs={})
        for fn in (SRV.r_journal, SRV.r_journal_stats, SRV.r_journal_errors, SRV.r_diagnostics):
            with self.assertRaises(CoreError) as ctx:
                fn(req, None, None)
            self.assertEqual(ctx.exception.error.code, "E_FORBIDDEN")
        auditor = types.SimpleNamespace(session={"role": "auditor", "login": "auditor"}, qs={})
        self.assertIn("items", SRV.r_journal(auditor, None, None))
        self.assertIn("findings", SRV.r_diagnostics(auditor, None, None))
        self.assertIn("/api/v1/journal/client", SRV.PUBLIC_PATHS)
        self.assertNotIn("/api/v1/journal", SRV.PUBLIC_PATHS)
        self.assertTrue(S.journal_stats()["total"] >= 0)

    def test_JRN_14_api_requests_are_journaled(self):
        """JRN-14: каждое обращение к API даёт запись с методом, кодом и длительностью."""
        from isheika.api import server as SRV
        h = SRV.Handler.__new__(SRV.Handler)
        h._method, h._path, h._resp_status, h._err_code = "POST", "/api/v1/researches", 422, "E_VALIDATION"
        h.qs, h.session, h.client_address = {}, {"login": "analyst", "role": "analyst"}, ("127.0.0.1", 1)
        h.headers = {"User-Agent": "TestClient/1.0"}
        h._journal_request("POST", 7.5)
        row = db.one("SELECT * FROM ops_journal WHERE action='POST /api/v1/researches' ORDER BY rowid DESC LIMIT 1")
        self.assertEqual(row["kind"], "api")
        self.assertEqual(row["level"], "warn")
        self.assertEqual(row["http_status"], 422)
        self.assertEqual(row["error_code"], "E_VALIDATION")
        self.assertEqual(row["actor"], "analyst")
        # путь с идентификатором сводится к шаблону — иначе действия не группируются
        h._path = "/api/v1/researches/res-11111111-2222-3333-4444-555555555555/start"
        h._resp_status, h._err_code = 200, None
        h._journal_request("POST", 3.0)
        self.assertTrue(db.one("SELECT * FROM ops_journal WHERE action='POST /api/v1/researches/{id}/start'"))
        # успешный GET — уровень debug: по умолчанию не пишется, но включается настройкой
        h._path, h._resp_status = "/api/v1/system", 200
        h._journal_request("GET", 1.0)
        self.assertFalse(db.one("SELECT * FROM ops_journal WHERE action='GET /api/v1/system'"))
        old = SETTINGS.journal_level
        try:
            SETTINGS.journal_level = "debug"
            h._journal_request("GET", 1.0)
            self.assertTrue(db.one("SELECT * FROM ops_journal WHERE action='GET /api/v1/system'"))
        finally:
            SETTINGS.journal_level = old

    def test_JRN_15_routes_published_and_rbac(self):
        """JRN-15: маршруты журнала в контракте OpenAPI; чтение — logs.read, приём браузера — публичный."""
        import json

        from isheika.api import openapi as OA, server as SV
        raw = json.dumps([list(map(str, r[:2])) for r in SV.ROUTES])
        for path in ("/api/v1/journal", "/api/v1/diagnostics", "/api/v1/journal/client"):
            self.assertIn(path, raw)
        self.assertEqual(OA.missing_canonical(SV.ROUTES), [])
        spec = OA.build_spec(SV.ROUTES)
        for path in ("/api/v1/journal", "/api/v1/diagnostics"):
            self.assertIn(path, spec["paths"])
        S.require({"login": "auditor", "role": "auditor"}, "logs.read")
        with self.assertRaises(CoreError):
            S.require({"login": "observer", "role": "observer"}, "logs.read")
        self.assertIn("/api/v1/journal/client", SV.PUBLIC_PATHS)
        # остальные маршруты журнала анониму закрыты
        self.assertNotIn("/api/v1/journal", SV.PUBLIC_PATHS)
        self.assertNotIn("/api/v1/diagnostics", SV.PUBLIC_PATHS)

    def test_JRN_16_ui_screen_registered(self):
        """JRN-16: экран UI-32 подключён к оболочке и защищён правом logs.read."""
        import re

        web = Path(__file__).resolve().parents[1] / "isheika" / "web"
        js = (web / "screens_journal.js").read_text(encoding="utf-8")
        self.assertTrue(re.search(r"UI-32.*M33", js))
        self.assertTrue(re.search(r"Screens\.journal\s*=", js))
        self.assertIn("right: 'logs.read'", js)
        for token in ("j-level", "j-kind", "j-q", "journal/export", "journal/errors",
                      "journal/stats", "diagnostics/run", "source: 'browser'"):
            self.assertIn(token, js)
        app = (web / "app.js").read_text(encoding="utf-8")
        self.assertIn("route: 'journal'", app)
        self.assertIn("function reportClient(", app)
        self.assertIn("window.addEventListener('error'", app)
        self.assertIn("window.addEventListener('unhandledrejection'", app)



class DiagnosticsTests(BaseCase):
    def codes(self, research_id=None):
        return {f["code"] for f in DG.run(research_id=research_id)["findings"]}

    def test_DIA_01_completed_research_with_failed_stage(self):
        """DIA-01: «completed» с проваленным этапом — противоречие итога исследования."""
        rid = self.make_research()
        db.insert("workflow_jobs", {"id": new_id("job-"), "research_id": rid, "stage": "S07",
                                    "name": "Расчёт", "status": "failed", "created_at": iso_now()})
        db.update("core_researches", "id", rid, {"status": "completed"})
        found = [f for f in DG.rule_states(rid) if f["code"] == "DIA-01a"]
        self.assertTrue(found)
        self.assertEqual(found[0]["severity"], "error")
        self.assertTrue(found[0]["evidence"][0]["research_id"] == rid)

    def test_DIA_02_forbidden_state_transition(self):
        """DIA-02: переход в обход конечного автомата находится по истории состояний."""
        db.insert("core_state_history", {"id": new_id("sth-"), "entity_kind": "research",
                                         "entity_id": "res-dia-0002", "from_state": "draft",
                                         "to_state": "completed", "reason": "прямое изменение",
                                         "actor": "tester", "created_at": iso_now()})
        found = DG.rule_transitions()
        self.assertTrue(any(f["code"] == "DIA-02" for f in found))
        self.assertTrue(any(e["from"] == "draft" and e["to"] == "completed" for e in found[0]["evidence"]))

    def test_DIA_03_report_without_files(self):
        """DIA-03: запись отчёта без файлов на диске — противоречие, а не «пустая ссылка»."""
        rid = self.make_research()
        db.insert("reporting_reports", {"id": new_id("rep-"), "research_id": rid, "title": "Отчёт",
                                        "status": "ready", "formats": ["html"],
                                        "files": {"html": os.path.join(DATA_DIR, "files", "нет-такого.html")},
                                        "methodology_version": SETTINGS.methodology_version,
                                        "created_at": iso_now()})
        found = DG.rule_report_files(rid)
        self.assertTrue(found and found[0]["code"] == "DIA-03")
        self.assertIn("html", found[0]["evidence"][0]["missing"])

    def test_DIA_04_supported_claim_without_evidence(self):
        """DIA-04: SUPPORTED без доказательств противоречит доказательной модели."""
        rid = self.make_research()
        self.add_claim(rid, "Дальность 250 км подтверждена", status="SUPPORTED")
        found = [f for f in DG.rule_claims(rid) if f["code"] == "DIA-04"]
        self.assertTrue(found)
        self.assertEqual(found[0]["severity"], "error")
        self.assertIn("UNVERIFIED", found[0]["recommendation"])

    def test_DIA_05_cross_research_evidence(self):
        """DIA-05: доказательство из чужого исследования находится правилом."""
        r1, r2 = self.make_research(), self.make_research()
        cid = self.add_claim(r1)
        db.insert("evidence_items", {"id": new_id("evd-"), "claim_id": cid, "research_id": r2,
                                     "evidence_class": "primary_peer_reviewed", "created_at": iso_now()})
        found = [f for f in DG.rule_claims() if f["code"] == "DIA-05"]
        self.assertTrue(found)
        self.assertEqual(found[0]["severity"], "error")

    def test_DIA_06_07_relevance_class_and_components(self):
        """DIA-06/07: класс не по порогу и неполные компоненты расчёта."""
        rid = self.make_research()
        did = self.add_doc(rid, "Документ с противоречивой оценкой", score=0.95, cls="DIRECT")
        db.execute("UPDATE search_results SET relevance_class='ADJACENT', score_k=NULL WHERE document_id=?", (did,))
        codes = {f["code"] for f in DG.rule_relevance(rid)}
        self.assertIn("DIA-06", codes)
        self.assertIn("DIA-07", codes)

    def test_DIA_08_trl_above_confirmed_criteria(self):
        """DIA-08: TRL выше уровня с выполненными обязательными критериями (усреднение запрещено)."""
        rid = self.make_research()
        criteria = [{"level": 3, "criterion_code": "C3", "is_mandatory": True, "confirmed": True},
                    {"level": 4, "criterion_code": "C4", "is_mandatory": True, "confirmed": False}]
        db.insert("analytics_trl", {"id": new_id("trl-"), "research_id": rid, "trl": 6,
                                    "criteria": criteria, "methodology_version": SETTINGS.methodology_version,
                                    "created_at": iso_now()})
        found = DG.rule_trl(rid)
        self.assertTrue(found and found[0]["code"] == "DIA-08")
        self.assertEqual(found[0]["evidence"][0]["confirmed_max"], 3)

    def test_DIA_09_unknown_factor_counted_as_number(self):
        """DIA-09: неизвестный фактор с числом — нарушение ИД-02 (неизвестное ≠ 0)."""
        rid = self.make_research()
        db.insert("analytics_feasibility", {
            "id": new_id("fea-"), "research_id": rid, "score": 40.0, "coverage": 0.5,
            "interpretation_allowed": 0, "interpretation": "низкая",
            "factors": [{"code": "F_PROD", "assessment": "unknown", "x": 0.0, "weight": 0.15}],
            "methodology_version": SETTINGS.methodology_version, "created_at": iso_now()})
        codes = {f["code"] for f in DG.rule_feasibility(rid)}
        self.assertIn("DIA-09", codes)
        self.assertIn("DIA-10", codes)      # запрет интерпретации без coverage_warning

    def test_DIA_10_interpretation_allowed_below_coverage_threshold(self):
        """DIA-10: интерпретация разрешена при покрытии ниже порога — нарушение ТЗ-03."""
        rid = self.make_research()
        base = {"research_id": rid, "score": 55.0, "coverage": 0.3, "interpretation": "условная",
                "factors": [], "parameters": {"min_coverage_for_interpretation": 0.6},
                "methodology_version": SETTINGS.methodology_version, "created_at": iso_now()}
        # разрешена при покрытии 0,3 < 0,6 — противоречие
        db.insert("analytics_feasibility", dict(base, id=new_id("fea-"), interpretation_allowed=1,
                                                coverage_warning="покрытие ниже порога"))
        found = [f for f in DG.rule_feasibility(rid) if f["code"] == "DIA-10"]
        self.assertTrue(found)
        self.assertIn("ниже порога", found[0]["evidence"][0]["reason"])
        # штатный случай: интерпретация рассчитана, но запрещена и объяснена — находки нет
        rid2 = self.make_research()
        db.insert("analytics_feasibility", dict(base, id=new_id("fea-"), research_id=rid2,
                                                interpretation_allowed=0,
                                                coverage_warning="Покрытие 30 % ниже порога 60 %"))
        self.assertFalse([f for f in DG.rule_feasibility(rid2) if f["code"] == "DIA-10"],
                         "штатное ограничение интерпретации не должно считаться противоречием")

    def test_DIA_11_12_forecast_monotonicity_and_horizon(self):
        """DIA-11/12: убывающая P(T≤t) и количественный прогноз за 20 лет."""
        rid = self.make_research()
        fid = new_id("fcr-")
        db.insert("forecast_runs", {"id": fid, "research_id": rid, "target": "TRL8",
                                    "method": "logistic_diffusion",
                                    "methodology_version": SETTINGS.methodology_version,
                                    "created_at": iso_now()})
        for years, prob, mode in ((0, 0.4, "EXACT"), (5, 0.3, "EXACT"), (25, 0.9, "EXACT")):
            db.insert("forecast_points", {"id": new_id("fpt-"), "forecast_id": fid, "research_id": rid,
                                          "target": "TRL8", "scenario_id": "base", "horizon_code": f"H{years}",
                                          "forecast_horizon_years": years, "years_from": years,
                                          "probability_value": prob, "display_mode": mode,
                                          "uncertainty_class": "medium", "created_at": iso_now()})
        codes = {f["code"] for f in DG.rule_forecast(rid)}
        self.assertIn("DIA-11", codes)
        self.assertIn("DIA-12", codes)

    def test_DIA_13_paid_provider_when_paid_ai_forbidden(self):
        """DIA-13: вызов платного провайдера при запрете платного ИИ — нарушение ТЗ-02."""
        paid = db.one("SELECT id FROM ai_providers WHERE paid=1 LIMIT 1")
        self.assertTrue(paid, "в реестре нет платного провайдера — проверка бессмысленна")
        rid = self.make_research()
        tid = new_id("ait-")
        db.insert("ai_tasks", {"id": tid, "research_id": rid, "agent_code": "A05",
                               "task_class": "analysis", "created_at": iso_now()})
        db.insert("ai_requests", {"id": new_id("air-"), "task_id": tid, "research_id": rid,
                                  "agent_code": "A05", "provider_id": paid["id"],
                                  "estimated_cost": 0.42, "created_at": iso_now()})
        old = SETTINGS.allow_paid_ai
        try:
            SETTINGS.allow_paid_ai = False
            self.assertTrue(any(f["code"] == "DIA-13" for f in DG.rule_policy()))
            SETTINGS.allow_paid_ai = True
            self.assertFalse(any(f["code"] == "DIA-13" for f in DG.rule_policy()),
                             "при явном разрешении платный вызов не является противоречием")
        finally:
            SETTINGS.allow_paid_ai = old

    def test_DIA_16_repeated_browser_errors(self):
        """DIA-16: одна и та же ошибка интерфейса дважды — дефект вёрстки, а не случайность."""
        for i in range(2):
            J.client_event({"level": "error", "kind": "ui", "action": "render.feasibility",
                            "message": f"TypeError:cannot read property {i} of undefined",
                            "stack": "at render (screens_core.js:120)"}, peer="203.0.113.20")
        found = [f for f in DG.rule_journal() if f["code"] == "DIA-16"]
        self.assertTrue(found)
        self.assertTrue(any(e["action"] == "render.feasibility" for e in found[0]["evidence"]))

    def test_DIA_18_journal_write_failures_are_reported(self):
        """DIA-18: сбои записи журнала не замалчиваются — они сами становятся находкой."""
        old = J.FAILED_WRITES
        try:
            J.FAILED_WRITES = old + 2
            found = [f for f in DG.rule_journal() if f["code"] == "DIA-18"]
            self.assertTrue(found)
            self.assertEqual(found[0]["evidence"][0]["failed_writes"], old + 2)
            self.assertIn("journal-fallback.log", found[0]["evidence"][0]["fallback"])
        finally:
            J.FAILED_WRITES = old

    def test_DIA_14_quota_over_limit(self):
        """DIA-14: расход сверх лимита — расхождение счётчика и ограничителя."""
        db.upsert("audit_quota_usage", {"id": new_id("qta-"), "scope": "source", "key": "SRC-TEST",
                                        "window": "day", "used": 120.0, "limit_value": 100.0,
                                        "updated_at": iso_now()}, key=("scope", "key", "window"))
        found = DG.rule_policy()
        self.assertTrue(any(f["code"] == "DIA-14" for f in found))

    def test_DIA_15_repeated_defect_detected(self):
        """DIA-15: одна подпись дефекта трижды — устойчивый баг, а не случайность."""
        for i in range(3):
            J.record("error", "workflow", "stage.S09", f"падение расчёта {i}",
                     error_type="KeyError", error_code="E_INTERNAL",
                     stack="  File \"analytics.py\", line 5, in calc\n")
        found = [f for f in DG.rule_journal() if f["code"] == "DIA-15"]
        self.assertTrue(found)
        self.assertTrue(any(e["action"] == "stage.S09" for e in found[0]["evidence"]))

    def test_DIA_17_secret_like_journal_entry(self):
        """DIA-17: похожая на секрет запись журнала помечается как критичное противоречие."""
        db.insert("ops_journal", {"id": new_id("jrn-"), "at": iso_now(), "level": "info",
                                  "kind": "system", "action": "test.leak",
                                  "message": "ключ api_key=abcdef123456 передан в запросе",
                                  "source": "server", "detail": {}, "client": {}})
        found = [f for f in DG.rule_journal() if f["code"] == "DIA-17"]
        self.assertTrue(found)
        self.assertEqual(found[0]["severity"], "critical")

    def test_DIA_19_unknown_methodology_version(self):
        """DIA-19: расчёт с версией методики вне реестра невоспроизводим."""
        rid = self.make_research()
        self.add_doc(rid, "Документ с чужой методикой")
        db.execute("UPDATE search_results SET methodology_version='M-9.9.9' WHERE research_id=?", (rid,))
        found = DG.rule_methodology(rid)
        self.assertTrue(found and found[0]["code"] == "DIA-19")
        self.assertEqual(found[0]["evidence"][0]["version"], "M-9.9.9")

    def test_DIA_19_registry_version_format_is_not_a_finding(self):
        """DIA-19: формат «CODE version» из реестра — не противоречие (ложная находка недопустима)."""
        rid = self.make_research()
        self.add_doc(rid, "Документ с реестровой версией методики")
        row = db.one("SELECT code, version FROM analytics_methodologies WHERE is_active=1 LIMIT 1")
        self.assertTrue(row)
        db.execute("UPDATE search_results SET methodology_version=? WHERE research_id=?",
                   (f'{row["code"]} {row["version"]}', rid))
        self.assertFalse(DG.rule_methodology(rid),
                         "штатная версия расчёта объявлена невоспроизводимой")

    def test_DIA_run_survives_broken_rule_and_reports_clean_scope(self):
        """Прогон правил: отказ одного правила не отменяет остальные; чистое исследование — без находок."""
        from unittest import mock
        rid = self.make_research()
        for code, _title, name in DG.RULES:
            if code.startswith(("DIA-01", "DIA-03", "DIA-04", "DIA-06", "DIA-08", "DIA-09", "DIA-11")):
                self.assertFalse(DG.rule_fn(name)(rid), f"чистое исследование дало находку правила {code}")
        with mock.patch.object(DG, "rule_trl", side_effect=RuntimeError("правило сломано")):
            res = DG.run(research_id=rid)
        self.assertTrue(res["broken_rules"])
        self.assertEqual(res["broken_rules"][0]["rule"], "DIA-08")
        self.assertEqual(res["rules"], len(DG.RULES))
        self.assertTrue(db.one("SELECT * FROM ops_journal WHERE action='diagnostics.DIA-08'"))
        res = DG.run(research_id=rid, to_journal=True, actor="tester")
        self.assertIn("checked_at", res)
        self.assertTrue(db.one("SELECT * FROM ops_journal WHERE action='diagnostics.run'"))
