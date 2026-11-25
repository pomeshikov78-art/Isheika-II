"""Испытания окна текущей версии в диагностике журнала (ИД-26, ред. 1.5.2).

Основание — четвёртая выгрузка (25.11.2026): проверка противоречий в версии 1.5.1
сообщала «Повторяющийся дефект» (DIA-15, 5 случаев) и «Повторяющиеся ошибки
интерфейса» (DIA-16, 8 случаев) по записям 24.11, сделанным прежними версиями,
где дефекты уже исправлены. Журнал хранится 30 суток и переживает обновления,
поэтому повторы нужно считать в окне текущей версии, а историю показывать
справкой, а не действующим дефектом.

DGW-01 — повторы прежней версии: справка (info), а не ошибка.
DGW-02 — те же повторы в текущей версии: действующий дефект (error).
DGW-03 — ошибки интерфейса прежней версии: справка, а не предупреждение.
DGW-04 — справки не считаются противоречиями в сводке проверки.
DGW-05 — граница окна определяется по клиентской записи текущей версии.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

from isheika import __version__, diagnostics as DG, journal as J
from isheika.contracts import iso_now
from isheika.storage import db

from .base import BaseCase


def _shift(iso: str, days: float) -> str:
    base = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (base + timedelta(days=days)).isoformat(timespec="seconds")


def _err(action: str, message: str, *, at: str, version: str, source: str = "server") -> str:
    jid = J.record("error", "connector", action, message, source=source,
                   error_code="E_NETWORK", error_type="ConnectionError",
                   client={"app_version": version, "screen": "test"})
    db.update("ops_journal", "id", jid, {"at": at})
    return jid


class DiagnosticsVersionWindowTests(BaseCase):
    def _boundary(self) -> str:
        """Гарантируем наличие клиентской записи текущей версии и берём границу окна."""
        jid = J.record("info", "action", "test.dgw152.current", "запись текущей версии",
                       source="browser", client={"app_version": __version__, "screen": "test"})
        # запись в прошлом: граница окна не должна уходить в будущее,
        # иначе записи других испытаний перестанут попадать в окно текущей версии
        db.update("ops_journal", "id", jid, {"at": _shift(iso_now(), -1)})
        since, ver = DG._version_window()
        self.assertEqual(ver, __version__)
        self.assertTrue(since)
        return since

    def _dia(self, code: str) -> list[dict]:
        return [f for f in DG.rule_journal() if f["code"] == code]

    def test_DGW_01_historical_repeats_are_informational(self):
        since = self._boundary()
        old = _shift(since, -3)
        action = "test.dgw152.history"
        for _ in range(12):
            _err(action, "источник недоступен (прежняя версия)", at=old, version="1.4.0")
        fp = db.one("SELECT fingerprint FROM ops_journal WHERE action=?", (action,))["fingerprint"]
        findings = self._dia("DIA-15")
        self.assertFalse([f for f in findings if f["severity"] in ("error", "critical")
                          and any(e.get("fingerprint") == fp for e in f["evidence"])],
                         "повторы прежней версии не должны считаться действующим дефектом")
        info = [f for f in findings if f["severity"] == "info"
                and any(e.get("fingerprint") == fp for e in f["evidence"])]
        self.assertTrue(info, "исторические повторы должны быть показаны справкой")
        self.assertIn("прежних версий", info[0]["title"])

    def test_DGW_02_current_version_repeats_are_defects(self):
        since = self._boundary()
        action = "test.dgw152.actual"
        for _ in range(4):
            _err(action, "источник недоступен (текущая версия)",
                 at=iso_now(), version=__version__)
        fp = db.one("SELECT fingerprint FROM ops_journal WHERE action=?", (action,))["fingerprint"]
        bad = [f for f in self._dia("DIA-15") if f["severity"] == "error"
               and any(e.get("fingerprint") == fp for e in f["evidence"])]
        self.assertTrue(bad, "повтор в текущей версии обязан оставаться дефектом")
        self.assertGreaterEqual(bad[0]["count"], 1)

    def test_DGW_03_browser_history_is_informational(self):
        since = self._boundary()
        old = _shift(since, -4)
        action = "test.dgw152.ui"
        for _ in range(9):
            _err(action, "падание экрана (прежняя версия)", at=old,
                 version="1.5.0", source="browser")
        fp = db.one("SELECT fingerprint FROM ops_journal WHERE action=?", (action,))["fingerprint"]
        findings = self._dia("DIA-16")
        self.assertFalse([f for f in findings if f["severity"] == "warn"
                          and any(e.get("fingerprint") == fp for e in f["evidence"])])
        self.assertTrue([f for f in findings if f["severity"] == "info"
                         and any(e.get("fingerprint") == fp for e in f["evidence"])])
        # а свежие ошибки интерфейса той же подписи — предупреждение
        for _ in range(2):
            _err(action, "падание экрана (прежняя версия)", at=iso_now(),
                 version=__version__, source="browser")
        self.assertTrue([f for f in self._dia("DIA-16") if f["severity"] == "warn"
                         and any(e.get("fingerprint") == fp for e in f["evidence"])])

    def test_DGW_04_informational_findings_are_not_contradictions(self):
        note = DG._finding("DIA-15", "info", "Повторяющиеся ошибки прежних версий",
                           "историческая запись", 7, [], "действий не требуется")
        with mock.patch.object(DG, "RULES", [("DIA-15…18", "Дефекты по журналу", "rule_journal")]), \
             mock.patch.object(DG, "rule_journal", lambda research_id=None: [note]):
            res = DG.run()
        self.assertTrue(res["ok"])
        self.assertEqual(res["cases"], 0)
        self.assertEqual(res["informational"], 1)
        self.assertEqual(res["counts"]["info"], 1)
        real = DG._finding("DIA-15", "error", "Повторяющийся дефект", "действующий", 3, [], "исправить")
        with mock.patch.object(DG, "RULES", [("DIA-15…18", "Дефекты по журналу", "rule_journal")]), \
             mock.patch.object(DG, "rule_journal", lambda research_id=None: [note, real]):
            res2 = DG.run()
        self.assertFalse(res2["ok"])
        self.assertEqual(res2["cases"], 3)

    def test_DGW_05_window_follows_earliest_current_version_record(self):
        since = self._boundary()
        # запись текущей версии глубже во времени сдвигает границу окна назад
        past = _shift(since, -2)
        jid = J.record("info", "action", "test.dgw152.earlier", "ранняя запись текущей версии",
                       source="browser", client={"app_version": __version__})
        db.update("ops_journal", "id", jid, {"at": past})
        new_since, _ = DG._version_window()
        self.assertLessEqual(new_since, past)
        self.assertLess(new_since, since)
        # записи прежней версии границу не двигают
        older = _shift(new_since, -5)
        jid2 = J.record("info", "action", "test.dgw152.old", "запись прежней версии",
                        source="browser", client={"app_version": "1.3.0"})
        db.update("ops_journal", "id", jid2, {"at": older})
        self.assertEqual(DG._version_window()[0], new_since)
