"""Состояния, идемпотентность, безопасность, RBAC, квоты, отчёты, workflow."""
import json
import os
import time

from isheika.config import SETTINGS
from isheika.contracts import CoreError
from isheika.states import FSMS, assert_transition
from isheika.storage import db
from isheika.storage.secrets import SecretStore, decrypt, encrypt, mask

from .base import BaseCase


class StateTests(BaseCase):
    def test_valid_transitions(self):
        assert_transition("research", "draft", "queued")
        assert_transition("task", "queued", "running")
        assert_transition("ai_request", "waiting_response", "response_received")

    def test_invalid_transition_raises(self):
        with self.assertRaises(CoreError) as ctx:
            assert_transition("research", "draft", "completed")
        self.assertEqual(ctx.exception.error.code, "E_STATE")

    def test_all_fsm_present(self):
        for key in ("research", "task", "ai_request", "document", "provider", "source", "report"):
            self.assertIn(key, FSMS)

    def test_terminal_states_have_no_illegal_exits(self):
        self.assertEqual(FSMS["ai_request"]["completed"], set())

    def test_restart_and_resume_allowed(self):
        assert_transition("research", "partial", "queued")
        assert_transition("research", "completed", "queued")
        assert_transition("research", "failed", "queued")
        assert_transition("provider", "rate_limited", "active")
        assert_transition("source", "CANDIDATE", "TESTED")


class WorkflowTests(BaseCase):
    def test_create_workflow_idempotent(self):
        from isheika.workflow import engine as W
        rid = self.make_research()
        W.create_workflow(rid)
        W.create_workflow(rid)
        self.assertEqual(db.count("workflow_jobs", "research_id=?", (rid,)), 12)
        keys = [r["idempotency_key"] for r in db.query("SELECT idempotency_key FROM workflow_jobs WHERE research_id=?", (rid,))]
        self.assertEqual(len(keys), len(set(keys)))

    def test_offline_pipeline_completes(self):
        from isheika.workflow import engine as W, pipeline  # noqa: F401
        rid = self.make_research(settings={"connector_codes": ["CON-SIM"], "max_docs_per_source": 5})
        W.start(rid)
        deadline = time.time() + 120
        while time.time() < deadline:
            st = W.status(rid)
            if not st["running"] and all(j["status"] in ("completed", "partial", "failed", "cancelled") for j in st["jobs"]):
                break
            time.sleep(1)
        st = W.status(rid)
        stages = {j["stage"]: j["status"] for j in st["jobs"]}
        self.assertEqual(len(stages), 12)
        self.assertIn(stages["report"], ("completed", "partial"))
        self.assertGreater(db.count("research_documents", "research_id=?", (rid,)), 0)
        self.assertGreater(db.count("evidence_items", "research_id=?", (rid,)), 0)
        self.assertIsNotNone(db.one("SELECT * FROM analytics_trl WHERE research_id=?", (rid,)))

    def test_resume_keeps_completed_stages(self):
        from isheika.workflow import engine as W, pipeline  # noqa: F401
        rid = self.make_research(settings={"connector_codes": ["CON-SIM"], "max_docs_per_source": 3})
        W.start(rid)
        deadline = time.time() + 120
        while time.time() < deadline and W.status(rid)["running"]:
            time.sleep(1)
        first = {j["id"]: j["finished_at"] for j in W.status(rid)["jobs"] if j["status"] == "completed"}
        W.start(rid, resume=True)
        deadline = time.time() + 120
        while time.time() < deadline and W.status(rid)["running"]:
            time.sleep(1)
        second = {j["id"]: j["finished_at"] for j in W.status(rid)["jobs"] if j["status"] == "completed"}
        for jid, fin in first.items():
            self.assertEqual(second.get(jid), fin, "завершённые этапы не должны пересчитываться")


class SecurityTests(BaseCase):
    def test_secret_roundtrip_and_mask(self):
        SecretStore.put("test_key", "api_key", "tester", "super-secret-value-123456")
        self.assertTrue(SecretStore.has("test_key"))
        self.assertEqual(SecretStore.get("test_key"), "super-secret-value-123456")
        pub = SecretStore.list_public()
        row = next(r for r in pub if r["ref"] == "test_key")
        self.assertNotIn("super-secret-value", json.dumps(row, ensure_ascii=False))
        self.assertNotIn("super-secret-value-123456", mask("api_key=super-secret-value-123456"))
        self.assertNotIn("super-secret-value-123456", mask("Authorization: Bearer super-secret-value-123456"))
        SecretStore.delete("test_key")
        self.assertFalse(SecretStore.has("test_key"))

    def test_encryption_is_not_plaintext(self):
        blob = encrypt("текст-секрет")
        self.assertNotIn("текст-секрет", blob)
        self.assertEqual(decrypt(blob), "текст-секрет")
        self.assertNotEqual(encrypt("текст-секрет"), encrypt("текст-секрет"))  # случайный nonce

    def test_rbac(self):
        from isheika.api import service as S
        S.require({"role": "admin"}, "keys.write")
        S.require({"role": "analyst"}, "research.write")
        with self.assertRaises(CoreError) as ctx:
            S.require({"role": "observer"}, "research.write")
        self.assertEqual(ctx.exception.error.code, "E_FORBIDDEN")
        with self.assertRaises(CoreError):
            S.require({"role": "expert"}, "keys.write")

    def test_login_and_session(self):
        from isheika.api import service as S
        with self.assertRaises(CoreError):
            S.login("analyst", "wrong-password")
        d = S.login("analyst", "dev:analyst")
        self.assertTrue(d["token"])
        self.assertEqual(S.session(d["token"])["role"], "analyst")
        with self.assertRaises(CoreError):
            S.session("invalid-token")

    def test_paid_ai_blocked_by_default(self):
        self.assertFalse(SETTINGS.allow_paid_ai)
        from isheika.ai import orchestrator as O
        c = O.candidates("tech_analysis")
        self.assertTrue(c["free"] or c["local"])
        for e in c["paid"]:
            self.assertTrue(e["provider"]["paid"])

    def test_stoplist_blocks_forbidden_sources(self):
        from isheika.search.http import check_url_allowed
        for url in ("https://sci-hub.se/10.1234/x", "https://libgen.is/get.php?md5=1",
                    "https://scholar.google.com/scholar?q=test",
                    "https://worldwide.espacenet.com/patent/search",
                    "https://fileserver-az.core.ac.uk/download/1.pdf"):
            with self.assertRaises(CoreError, msg=url) as ctx:
                check_url_allowed(url)
            self.assertEqual(ctx.exception.error.code, "E_POLICY")

    def test_ssrf_and_scheme_protection(self):
        from isheika.search.http import check_url_allowed
        for url in ("file:///etc/passwd", "http://127.0.0.1:8000/x", "http://169.254.169.254/latest/meta-data"):
            with self.assertRaises(CoreError, msg=url):
                check_url_allowed(url)

    def test_cross_research_evidence_rejected(self):
        from isheika.api import service as S
        r1, r2 = self.make_research(), self.make_research()
        cid = self.add_claim(r1)
        did = self.add_doc(r2, "Чужой документ")
        with self.assertRaises(CoreError) as ctx:
            S.add_evidence(r1, {"claim_id": cid, "document_id": did}, actor="tester")
        self.assertEqual(ctx.exception.error.code, "E_POLICY")


class QuotaTests(BaseCase):
    def test_usage_and_limit(self):
        from isheika.search import quota
        for _ in range(2):
            quota.check_counter("calls", "TEST-CONN", "day", 2)
            quota.add_usage("calls", "TEST-CONN", "day", 1, limit=2)
        self.assertEqual(quota.usage("calls", "TEST-CONN", "day")["used"], 2)
        with self.assertRaises(CoreError) as ctx:
            quota.check_counter("calls", "TEST-CONN", "day", 2)
        self.assertEqual(ctx.exception.error.code, "E_QUOTA")

    def test_unknown_limit_stays_unknown(self):
        from isheika.search import quota
        quota.check_counter("calls", "TEST-UNKNOWN", "day", None)
        quota.add_usage("calls", "TEST-UNKNOWN", "day", 1, limit=None)
        self.assertIsNone(quota.usage("calls", "TEST-UNKNOWN", "day")["limit"])

    def test_snapshot_uses_safe_aliases(self):
        from isheika.search import quota
        rows = quota.snapshot()
        self.assertIsInstance(rows, list)
        if rows:
            self.assertIn("limit", rows[0])
            self.assertIn("window", rows[0])


class EvidenceTests(BaseCase):
    def test_fact_requires_evidence(self):
        from isheika.analytics import evidence as E
        rid = self.make_research()
        did = self.add_doc(rid, "Тропосферная связь: измерения")
        cid = self.add_claim(rid, "Дальность связи 250 км подтверждена измерениями", "FACT")
        self.add_evidence(rid, cid, did, status="SUPPORTED")
        s = E.summary(rid)
        self.assertEqual(s["by_status"]["SUPPORTED"], 1)
        self.assertGreaterEqual(s["independence_groups"], 1)

    def test_unverified_without_evidence(self):
        rid = self.make_research()
        cid = self.add_claim(rid, "Утверждение без доказательства", "FACT")
        row = db.one("SELECT status FROM knowledge_claims WHERE id=?", (cid,))
        self.assertEqual(row["status"], "UNVERIFIED")


class ReportTests(BaseCase):
    def test_formats_generated(self):
        from isheika.reports import builder as RB
        rid = self.make_research()
        did = self.add_doc(rid, "Тропосферная связь: испытания", abstract="Экспериментальные результаты.")
        cid = self.add_claim(rid, "Испытания подтвердили дальность 250 км")
        self.add_evidence(rid, cid, did)
        res = RB.generate(rid)
        for fmt in ("html", "json", "xlsx", "docx"):
            self.assertIn(fmt, res["files"], fmt)
            self.assertTrue(os.path.exists(res["files"][fmt]))
            self.assertGreater(os.path.getsize(res["files"][fmt]), 200)
        with open(res["files"]["html"], encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("ИЩЕЙКА", html)
        self.assertIn(SETTINGS.methodology_version, html)

    def test_pdf_generated_with_cyrillic_font(self):
        from isheika.reports import builder as RB
        rid = self.make_research()
        did = self.add_doc(rid, "Тропосферная связь: испытания", abstract="Экспериментальные результаты.")
        cid = self.add_claim(rid, "Испытания подтвердили дальность 250 км")
        self.add_evidence(rid, cid, did)
        res = RB.generate(rid, ["pdf"])
        path = res["files"]["pdf"]
        with open(path, "rb") as fh:
            head = fh.read(8)
            fh.seek(-32, 2)
            tail = fh.read()
        self.assertTrue(head.startswith(b"%PDF-1."))
        self.assertIn(b"%%EOF", tail)
        self.assertGreater(os.path.getsize(path), 10000)
        with open(path, "rb") as fh:
            body = fh.read()
        self.assertIn(b"/FontFile2", body)      # встроенный шрифт с кириллицей
        self.assertIn(b"/ToUnicode", body)      # текст выделяемый и искомый
        self.assertIn(b"/Type /Page", body)

    def test_empty_research_report_does_not_crash(self):
        from isheika.reports import builder as RB
        rid = self.make_research()
        res = RB.generate(rid)
        self.assertIn("html", res["files"])
        self.assertTrue(res["warnings"], "пустой отчёт обязан содержать предупреждения")

    def test_missing_report_file_is_reported_not_linked(self):
        """RPT-05: запись отчёта переживает сам файл — доступность считает сервер.

        Перенос состояния без каталога var/files (клонирование, восстановление,
        ручная чистка) оставлял в БД запись со списком форматов. Интерфейс рисовал
        ссылку на каждый формат, клик по отсутствующему файлу давал голый 404.
        Теперь сервис отдаёт files_available/missing_files, а UI показывает
        неактивную кнопку и объяснение вместо ссылки.
        """
        from isheika.api import service as S
        from isheika.reports import builder as RB
        rid = self.make_research()
        res = RB.generate(rid, ["html", "json"])
        row = next(r for r in S.reports(rid) if r["id"] == res["report_id"])
        self.assertEqual(row["missing_files"], [])
        self.assertTrue(all(row["files_available"].values()))

        os.remove(res["files"]["html"])
        row = next(r for r in S.reports(rid) if r["id"] == res["report_id"])
        self.assertIn("html", row["missing_files"])
        self.assertFalse(row["files_available"]["html"])
        self.assertTrue(row["files_available"]["json"])
        with self.assertRaises(CoreError) as ctx:
            S.report_file(res["report_id"], "html")
        self.assertEqual(ctx.exception.error.code, "E_NOT_FOUND")

        # интерфейс обязан опираться на серверную доступность, а не на список форматов
        from isheika.config import WEB_DIR
        with open(os.path.join(WEB_DIR, "screens_core.js"), encoding="utf-8") as fh:
            ui = fh.read()
        self.assertIn("r.missing_files", ui)

    def test_passport_on_empty_research(self):
        from isheika.analytics import passport as P
        rid = self.make_research()
        p = P.build(rid)
        self.assertIn("passport", p)
        self.assertIn("limitations", p["passport"])


class ServiceTests(BaseCase):
    def test_validation_errors(self):
        from isheika.api import service as S
        with self.assertRaises(CoreError) as ctx:
            S.create_research({"query": ""})
        self.assertEqual(ctx.exception.error.code, "E_VALIDATION")
        with self.assertRaises(CoreError):
            S.create_research({"query": "x", "countries": ["ZZ"]})
        with self.assertRaises(CoreError):
            S.create_research({"query": "x", "forecast_horizon_years": 99})

    def test_query_versioning(self):
        from isheika.api import service as S
        rid = self.make_research()
        S.update_query(rid, {"query": "тропосферная связь 5G NTN"}, actor="tester")
        rows = db.query("SELECT query_version FROM search_queries WHERE research_id=? ORDER BY query_version", (rid,))
        self.assertEqual([r["query_version"] for r in rows], [1, 2])

    def test_document_exclusion_and_label(self):
        from isheika.api import service as S
        rid = self.make_research()
        did = self.add_doc(rid, "Тропосферная связь")
        S.exclude_document(did, "нерелевантно", actor="tester", research_id=rid)
        row = db.one("SELECT decision, relevance_class FROM search_results WHERE document_id=? ORDER BY created_at DESC LIMIT 1", (did,))
        self.assertEqual(row["decision"], "MANUAL_EXCLUDE")
        # ИД-06: класс релевантности не меняется при ручном исключении
        self.assertEqual(row["relevance_class"], "DIRECT")
        S.label_document(did, 2, actor="tester", research_id=rid)
        row = db.one("SELECT details FROM analytics_quality WHERE research_id=? AND metric='relevance_label'", (rid,))
        self.assertEqual(json.loads(row["details"])["label"], 2)

    def test_settings_update_is_audited(self):
        from isheika.api import service as S
        res = S.update_settings({"max_docs_per_source": 7}, actor="tester")
        self.assertEqual(res["changed"]["max_docs_per_source"], 7)
        self.assertTrue(db.one("SELECT * FROM audit_log WHERE action='settings.update'"))
        S.update_settings({"max_docs_per_source": SETTINGS.max_docs_per_source}, actor="tester")
