"""Испытания устойчивости интерфейса к недоступности сервера (редакция 1.4.1).

Замечание пользователя: «Ошибка E_NETWORK … этап: UI-24», экраны «Подробный
журнал работы» и «Журнал действий и диагностика» остались недоступны. Причина —
интерфейс не восстанавливался сам: один отказ сети оставлял экран с ошибкой до
перезагрузки страницы, а события журнала после первого отказа переставали
отправляться навсегда (jrnMuted). Здесь закреплены правила нового поведения.

NET-01…08 — статические требования к сценарию оболочки (повторы, классификация
шлюза, автопереподключение, очередь событий, частичная доступность экрана).
JRN-17 — сервер принимает событие, прождавшее в очереди браузера.
"""
from __future__ import annotations

import os
import re

from isheika import journal as J
from isheika.config import WEB_DIR
from isheika.storage import db
from tests.base import BaseCase


def web_src(name: str) -> str:
    with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
        return f.read()


class OfflineUITests(BaseCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = web_src("app.js")
        self.journal_screen = web_src("screens_journal.js")

    def test_NET_01_safe_requests_are_retried(self):
        """NET-01: безопасный запрос повторяется, изменяющий — нет (без двойных эффектов)."""
        self.assertTrue(re.search(r"const safe = method === 'GET' \|\| method === 'HEAD' \|\| !!idem", self.app))
        self.assertTrue(re.search(r"const attempts = opts\.attempts \|\| \(safe \? 3 : 1\)", self.app))
        self.assertTrue(re.search(r"for \(let attempt = 1; attempt <= attempts; attempt\+\+\)", self.app))
        self.assertTrue(re.search(r"if \(attempt > 1\) await sleep\(", self.app), "между попытками нужна пауза")

    def test_NET_02_gateway_response_is_network_error(self):
        """NET-02: ответ шлюза 502/503/504 без тела API — недоступность, а не ошибка данных."""
        self.assertTrue(re.search(r"\[502, 503, 504\]\.includes\(res\.status\) && !\(data && data\.error\)", self.app))
        self.assertTrue(re.search(r"Шлюз вернул HTTP ", self.app))

    def test_NET_03_auto_reconnect_and_rerender(self):
        """NET-03: после отказа включается проба сервера, при успехе экран перерисовывается."""
        for token in ("function startProbe(", "function stopProbe(", "async function probeServer(",
                      "function markOffline(", "function markOnline("):
            self.assertIn(token, self.app)
        self.assertTrue(re.search(r"NET\.probe = setTimeout\(tick, NET\.delay\)", self.app))
        self.assertTrue(re.search(r"NET\.delay = Math\.min\(15000, 4000 \+ NET\.tries \* 1000\)", self.app),
                        "пауза между пробами должна расти, но не превышать 15 с")
        self.assertTrue(re.search(r"if \(S\.route\) render\(\);", self.app))
        self.assertIn("window.addEventListener('online'", self.app)
        self.assertIn("window.addEventListener('offline'", self.app)

    def test_NET_04_journal_events_are_queued_not_muted(self):
        """NET-04: отказ доставки не отключает журнал навсегда — событие ждёт в очереди."""
        self.assertNotIn("jrnMuted", self.app, "прежний вечный запрет отправки вернулся")
        self.assertIn("const QUEUE_KEY = 'isheika.journal.queue'", self.app)
        self.assertTrue(re.search(r"const QUEUE_MAX = 50", self.app))
        self.assertTrue(re.search(r"function queuePush\(payload\)", self.app))
        self.assertTrue(re.search(r"async function flushJournal\(", self.app))
        self.assertTrue(re.search(r"queued_at: p\.queued_at \|\| new Date\(\)\.toISOString\(\)", self.app))
        # при восстановлении связи очередь досылается сама
        self.assertTrue(re.search(r"flushJournal\(\)\.then\(", self.app))

    def test_NET_05_status_line_shows_queue_and_reconnect(self):
        """NET-05: строка состояния показывает недоступность, попытку и размер очереди."""
        self.assertTrue(re.search(r"недоступно — переподключение", self.app))
        self.assertTrue(re.search(r"событий журнала в очереди: ", self.app))

    def test_NET_06_error_block_offers_reconnect(self):
        """NET-06: блок ошибки объясняет автоповтор и даёт переподключение."""
        self.assertTrue(re.search(r"App\.retry\(\)", self.app))
        self.assertTrue(re.search(r"retry: \(\) => \{ probeServer\(\); return render\(\); \}", self.app))
        self.assertTrue(re.search(r"Переподключиться", self.app))
        self.assertTrue(re.search(r"события журнала сохранены в очереди", self.app))

    def test_NET_07_journal_screen_survives_partial_failure(self):
        """NET-07: отказ сводки не лишает ленты — экран показывает частичные данные."""
        self.assertIn("Promise.allSettled", self.journal_screen)
        self.assertTrue(re.search(r"if \(rd\.status === 'rejected' && rs\.status === 'rejected'\) throw rd\.reason",
                                  self.journal_screen))
        self.assertTrue(re.search(r"Часть данных не получена", self.journal_screen))

    def test_NET_08_browser_tab_exposes_queue(self):
        """NET-08: вкладка «Ошибки браузера» показывает очередь и умеет её дослать."""
        self.assertIn("App.journalQueueSize()", self.journal_screen)
        self.assertIn("jb-flush", self.journal_screen)
        self.assertIn("App.flushJournal()", self.journal_screen)
        for name in ("flushJournal", "journalQueueSize", "probeServer", "netState", "retry"):
            self.assertTrue(re.search(r"\b" + name + r"\b", self.app.split("return {")[-1]),
                            f"{name} не опубликован в App")

    def test_JRN_17_queued_client_event_keeps_queue_time(self):
        """JRN-17: событие из очереди браузера сохраняет время постановки — задержка видна."""
        res = J.client_event({"level": "error", "kind": "ui", "action": "ui.offline.sample",
                              "message": "Отказ, случившийся пока сервер был недоступен",
                              "queued_at": "2026-11-24T17:05:00Z"}, peer="203.0.113.44")
        self.assertTrue(res["accepted"])
        row = db.one("SELECT * FROM ops_journal WHERE id=?", (res["id"],))
        client = db.dec(row, "client")["client"]
        self.assertEqual(client.get("queued_at"), "2026-11-24T17:05:00Z")
        self.assertTrue(client.get("delivered_with_delay"))
        # без очереди — обычных полей нет (не выдумываем задержку)
        res2 = J.client_event({"message": "обычное событие"}, peer="203.0.113.45")
        row2 = db.one("SELECT * FROM ops_journal WHERE id=?", (res2["id"],))
        self.assertNotIn("queued_at", db.dec(row2, "client")["client"])
