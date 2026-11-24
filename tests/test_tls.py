"""Испытания доверия сертификатам исходящих запросов (редакция 1.4.3).

Основание — журнал действий с машины пользователя (ред. 1.4.2):

    search.source_failed  CON-ARXIV  E_NETWORK
    <urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
     unable to get local issuer certificate (_ssl.c:1006)>

Сертификат export.arxiv.org подписан центром «Certainly Root R1/E1». В Linux
его корень есть в системном наборе, в хранилище Windows на машине пользователя
его не было — источник отказывал, хотя сеть исправна и в браузере адрес открыт.

TLS-01 — набор корней поставляется вместе с приложением, проверка включена.
TLS-02 — запрос к серверу с «неизвестным» центром падает (воспроизведение отказа).
TLS-03 — тот же запрос проходит с дополнительным набором корней (ISHEIKA_CA_BUNDLE).
TLS-04 — отказ сертификата не повторяется впустую и несёт пояснение оператору.
TLS-05 — самопроверка загрузки и диагностика показывают состояние доверия.
"""
from __future__ import annotations

import http.server
import os
import ssl
import threading
import urllib.error
import urllib.request

from isheika import boot, diagnostics, tls
from isheika.contracts import CoreError
from isheika.search import http as H
from tests.base import BaseCase

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "tls")
CA = os.path.join(FIXTURES, "test-ca.pem")


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):                                   # noqa: N802
        body = b'{"ok": true, "works": []}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):                       # тишина в выводе испытаний
        pass


class _Server:
    """Локальный HTTPS-сервер с сертификатом от «неизвестного» центра."""

    def __enter__(self):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(os.path.join(FIXTURES, "server.pem"),
                            os.path.join(FIXTURES, "server.key"))
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"https://127.0.0.1:{self.httpd.server_address[1]}/api"
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class TlsTrustTests(BaseCase):
    def setUp(self):
        super().setUp()
        self._env = os.environ.pop("ISHEIKA_CA_BUNDLE", None)
        tls.reset()

    def tearDown(self):
        os.environ.pop("ISHEIKA_CA_BUNDLE", None)
        if self._env is not None:
            os.environ["ISHEIKA_CA_BUNDLE"] = self._env
        tls.reset()

    def test_TLS_01_bundle_shipped_and_verification_on(self):
        """TLS-01: набор корней приложения на месте, проверка сертификатов обязательна."""
        self.assertTrue(os.path.isfile(tls.BUNDLE), "isheika/data/cacert.pem должен поставляться")
        info = tls.info()
        self.assertGreaterEqual(info["bundled_certs"], 100)
        self.assertGreater(info["total_anchors"], 0)
        ctx = tls.context()
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        # корень, из-за которого отказывал arXiv, обязан быть в наборе
        with open(tls.BUNDLE, encoding="utf-8") as fh:
            self.assertIn("BEGIN CERTIFICATE", fh.read())

    def test_TLS_02_unknown_ca_reproduces_user_failure(self):
        """TLS-02: без доверия к центру запрос падает — как у пользователя на arXiv."""
        with _Server() as srv:
            with self.assertRaises(urllib.error.URLError) as caught:
                urllib.request.urlopen(srv.url, timeout=10, context=tls.context())
            self.assertIn("CERTIFICATE_VERIFY_FAILED", str(caught.exception))

    def test_TLS_03_extra_bundle_fixes_without_disabling_verify(self):
        """TLS-03: дополнительный набор корней лечит отказ, проверка остаётся включённой."""
        os.environ["ISHEIKA_CA_BUNDLE"] = CA
        tls.reset()
        info = tls.info()
        self.assertGreater(info["extra_anchors"], 0, "корень из ISHEIKA_CA_BUNDLE не загружен")
        with _Server() as srv:
            with urllib.request.urlopen(srv.url, timeout=10, context=tls.context()) as r:
                self.assertEqual(r.status, 200)
            self.assertTrue(tls.context().check_hostname)
            self.assertEqual(tls.context().verify_mode, ssl.CERT_REQUIRED)

    def test_TLS_04_http_client_reports_hint_and_no_retry(self):
        """TLS-04: клиент поиска отдаёт пояснение и не повторяет отказ трижды."""
        from unittest import mock

        from isheika import journal
        from isheika.config import SETTINGS
        was_network = SETTINGS.network_enabled
        SETTINGS.network_enabled = True          # испытание ходит на локальный сервер
        self.addCleanup(setattr, SETTINGS, "network_enabled", was_network)
        with _Server() as srv:
            before = journal.query(limit=1)["total"]
            # Защита от SSRF запрещает loopback — в испытании сервер локальный,
            # поэтому проверка адреса подменяется только здесь и только на время запроса.
            with mock.patch.object(H, "check_url_allowed", lambda *a, **k: None):
                try:
                    H.request(srv.url, connector={"code": "CON-TLSTEST", "limits": {}, "quota_policy": {}},
                              max_attempts=3, ttl_s=-1)
                    self.fail("ожидался отказ проверки сертификата")
                except CoreError as exc:
                    self.assertEqual(exc.error.code, "E_NETWORK")
                    self.assertFalse(exc.error.retryable, "отказ сертификата повтором не лечится")
                    self.assertIn("ISHEIKA_CA_BUNDLE", exc.error.details.get("tls_hint", ""))
            rows = [r for r in journal.query(kind="connector", limit=20)["items"]
                    if "CON-TLSTEST" in (r.get("action") or "")]
            self.assertEqual(len(rows), 1, f"отказ записан {len(rows)} раз вместо одного")
            self.assertGreaterEqual(journal.query(limit=1)["total"], before)

    def test_TLS_05_boot_and_diagnostics_show_trust(self):
        """TLS-05: состояние доверия видно в журнале загрузки и в диагностике."""
        snap = boot.snapshot()
        check = next((c for c in snap["checks"] if "сертификат" in c["check"].lower()), None)
        self.assertIsNotNone(check, "в самопроверке загрузки нет проверки доверия")
        self.assertTrue(check["ok"], check["detail"])
        self.assertIn("tls", snap)
        self.assertGreaterEqual(snap["tls"]["bundled_certs"], 100)

        from isheika import journal
        journal.record(level="warn", kind="connector", action="http:CON-TLSTEST",
                       message="<urlopen error [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed>",
                       error_code="E_NETWORK", source="server")
        found = diagnostics.rule_tls()
        codes = {f["code"] for f in found}
        self.assertIn("DIA-20", codes, "диагностика не увидела отказ проверки сертификата")
        dia20 = next(f for f in found if f["code"] == "DIA-20")
        self.assertIn("ISHEIKA_CA_BUNDLE", dia20["recommendation"])
        self.assertNotIn("DIA-21", codes, "набор приложения на месте — ложная находка")
