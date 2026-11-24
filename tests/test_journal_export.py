"""Испытания разбора выгрузки журнала и классификации отмены запроса (ред. 1.5.1).

Основание — выгрузка с машины пользователя (`2_journal.txt`, `3_isheika-log.txt`):
в 21:26:55 около 50 запросов данных записаны как «Сервер недоступен» (E_NETWORK),
при этом в ту же секунду сервер принимал `POST /api/v1/journal/client` за 0.2…0.8 мс
и никаких запросов данных не получал. Отличить отмену запроса (перезагрузка
вкладки) от недоступности сервера по выгрузке было НЕЧЕМ: текстовая и CSV-выгрузка
журнала не включали ни деталей события, ни версии приложения, ни признака задержки
очереди — они хранились в БД, но не выгружались.

JEX-01…04 — контекст и детали события браузера в выгрузке TXT/CSV/JSON.
NET-09…12 — оболочка отличает отмену запроса от отказа сети.
"""
from __future__ import annotations

import json
import os
import re

from isheika import journal as J
from isheika.config import WEB_DIR
from tests.base import BaseCase


def web_src(name: str) -> str:
    with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
        return f.read()


class JournalExportTests(BaseCase):
    def _client_event(self):
        return J.client_event({
            "level": "error", "kind": "ui", "action": "api.POST /api/v1/researches",
            "message": "Сервер недоступен. Проверьте соединение — данные могли устареть.",
            "error_code": "E_NETWORK", "error_type": "NetworkError",
            "route": "#/query", "screen": "query", "app_version": "1.5.0",
            "viewport": "1600x900", "boot_id": "boot-test",
            "queued_at": "2026-11-24T21:20:00Z",
            "detail": {"http": 0, "attempts": 3, "request_id": "req-test"},
        }, peer="127.0.0.1")

    def test_JEX_01_txt_contains_client_context(self):
        self._client_event()
        txt = J.export("txt")
        self.assertIn("версия 1.5.0", txt, "в выгрузке нет версии приложения")
        self.assertIn("экран query", txt)
        self.assertIn("маршрут #/query", txt)
        self.assertIn("в очереди с 2026-11-24T21:20:00Z", txt,
                      "задержка доставки не видна — событие выглядит свежим отказом")

    def test_JEX_02_txt_contains_detail_and_request_id(self):
        self._client_event()
        txt = J.export("txt")
        self.assertIn("детали:", txt)
        self.assertIn('"attempts": 3', txt, "число попыток не выгружается")
        self.assertIn("NetworkError", txt)
        self.assertIn("rid=", txt)

    def test_JEX_03_csv_contains_client_columns(self):
        self._client_event()
        csv_text = J.export("csv")
        head = csv_text.splitlines()[0]
        for col in ("app_version", "screen", "route", "queued_at", "delivered_with_delay", "detail", "client"):
            self.assertIn(col, head, f"в CSV нет колонки {col}")
        self.assertIn("1.5.0", csv_text)
        self.assertIn("req-test", csv_text)

    def test_JEX_04_json_keeps_detail(self):
        self._client_event()
        data = json.loads(J.export("json"))
        row = data["items"][0]
        self.assertEqual(row["client"]["app_version"], "1.5.0")
        self.assertEqual(row["detail"]["attempts"], 3)
        self.assertTrue(row["client"]["delivered_with_delay"])


class AbortClassificationTests(BaseCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = web_src("app.js")
        self.core = web_src("screens_core.js")

    def test_NET_09_timeout_is_marked_explicitly(self):
        """NET-09: отмену по нашему таймеру отличаем от внешней отмены."""
        self.assertTrue(re.search(r"let timedOut = false", self.app))
        self.assertTrue(re.search(r"setTimeout\(\(\) => \{ timedOut = true; ctrl\.abort\(\); \}, limit\)", self.app))

    def test_NET_10_abort_is_not_network_failure(self):
        """NET-10: AbortError без таймера — E_ABORTED, без markOffline и без записи отказа."""
        self.assertIn("const aborted = (e && e.name === 'AbortError')", self.app)
        m = re.search(r"if \(aborted && !timedOut\) \{(.*?)\n        \}", self.app, re.S)
        self.assertIsNotNone(m, "в оболочке нет ветки отмены запроса")
        block = m.group(1)
        self.assertIn("E_ABORTED", block)
        self.assertNotIn("markOffline", block, "отмена запроса не должна переводить приложение в offline")
        self.assertNotIn("reportClient", block, "отмена запроса не должна писаться в журнал как отказ")

    def test_NET_11_page_unload_is_tracked(self):
        """NET-11: выгрузка страницы отмечается и не порождает ложных отказов."""
        self.assertIn("pagehide", self.app)
        self.assertIn("NET.unloading = true", self.app)
        self.assertTrue(re.search(r"if \(NET\.unloading\) throw netErr", self.app),
                        "при выгрузке страницы отказ не должен уходить в журнал как E_NETWORK")

    def test_NET_12_aborted_screen_is_not_an_error(self):
        """NET-12: отменённый запрос не рисуется как ошибка экрана."""
        self.assertTrue(re.search(r"if \(code === 'E_ABORTED'\) return ''", self.app))

    def test_NET_13_create_key_is_per_action(self):
        """NET-13: ключ идемпотентности уникален для действия, а не для текста запроса."""
        self.assertIn("'create:' + App.uid('idem-')", self.core)
        self.assertNotIn("'create:' + body.query", self.core,
                         "ключ по тексту запроса вернул бы старое исследование при новом действии")
