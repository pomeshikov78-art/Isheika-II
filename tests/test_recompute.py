"""Испытания пересчёта зависимых этапов при повторном запуске (редакция 1.4.4).

Основание — журнал с машины пользователя (ред. 1.4.2/1.4.3, файлы
`1_journal.txt`, `2_isheika-log.txt`): пять повторных запусков подряд выполняли
только этап 3 (`job.started source_search` → `job.completed` → `research.completed`
за 1 секунду), находили 114 документов вместо прежних 106, но этапы 4–12
оставались «completed» и пропускались. Новые документы не оценивались, не
попадали в доказательную базу и отчёт, а исследование значилось завершённым.

RER-01 — изменившийся результат этапа возвращает зависимые этапы в очередь.
RER-02 — неизменившийся результат не вызывает лишнего пересчёта.
RER-03 — полный повторный прогон доводит новые документы до отчёта.
RER-04 — пересчёт виден в журнале и истории состояний.
"""
from __future__ import annotations

import time

from isheika.storage import db
from isheika.workflow import engine as W
from isheika.workflow import pipeline as P  # noqa: F401  (регистрация обработчиков)
from tests.base import BaseCase


def wait_done(rid: str, timeout: float = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        st = W.status(rid)
        if not st["running"] and all(j["status"] in ("completed", "partial", "failed", "cancelled", "skipped")
                                     for j in st["jobs"]):
            return st
        time.sleep(0.2)
    raise AssertionError("исследование не завершилось за отведённое время")


def stages_status(rid: str) -> dict:
    return {j["stage"]: j["status"] for j in W.status(rid)["jobs"]}


class RecomputeTests(BaseCase):
    def _offline_research(self, **settings) -> str:
        s = {"connector_codes": ["CON-SIM"], "max_docs_per_source": 4}
        s.update(settings)
        # отдельный запрос: корпус общий для исследований, испытание не должно
        # менять выборку других испытаний
        return self.make_research("тропосферная связь за горизонтом — пересчёт этапов RER",
                                  settings=s)

    def test_RER_01_changed_result_resets_dependents(self):
        """RER-01: новый результат этапа 3 возвращает этапы 4–12 в очередь."""
        rid = self._offline_research()
        W.start(rid)
        wait_done(rid)
        self.assertEqual(stages_status(rid)["report"], "completed")
        reset = W.invalidate_dependents(rid, "source_search", reason="испытание")
        self.assertIn("document_processing", reset)
        self.assertIn("report", reset)
        st = stages_status(rid)
        self.assertIn(st["source_search"], ("completed", "partial"),
                      "сам этап 3 сбрасывать не нужно")
        for s in reset:
            self.assertEqual(st[s], "queued", f"этап {s} не поставлен в очередь пересчёта")

    def test_RER_02_same_result_keeps_completed(self):
        """RER-02: тот же результат — лишнего пересчёта нет (повторный запуск дёшев)."""
        rid = self._offline_research()
        W.start(rid)
        wait_done(rid)
        before = {j["stage"]: j["attempts"] for j in W.status(rid)["jobs"]}
        W.start(rid)
        wait_done(rid)
        after = {j["stage"]: j["attempts"] for j in W.status(rid)["jobs"]}
        for stage in ("relevance_filter", "math_core", "report"):
            self.assertEqual(after[stage], before[stage],
                             f"этап {stage} пересчитан без изменения исходных данных")

    def test_RER_03_new_documents_reach_report(self):
        """RER-03: новые документы из источника доходят до оценки и отчёта."""
        rid = self._offline_research(max_docs_per_source=2)
        W.start(rid)
        wait_done(rid)
        first = db.dec(db.one("SELECT result FROM workflow_jobs WHERE research_id=? AND stage='document_processing'",
                              (rid,)), "result")["result"]["documents_total"]
        first_report = db.one("SELECT id FROM reporting_reports WHERE research_id=? ORDER BY rowid DESC LIMIT 1",
                              (rid,))
        # источник при повторном поиске отдаёт больше документов
        r = db.dec(db.one("SELECT * FROM core_researches WHERE id=?", (rid,)), "settings")
        settings = r["settings"] or {}
        settings["max_docs_per_source"] = 6
        db.update("core_researches", "id", rid, {"settings": settings})
        db.update("workflow_jobs", "id",
                  db.one("SELECT id FROM workflow_jobs WHERE research_id=? AND stage='source_search'", (rid,))["id"],
                  {"status": "queued"})
        W.start(rid)
        wait_done(rid)
        row = db.dec(db.one("SELECT result FROM workflow_jobs WHERE research_id=? AND stage='document_processing'",
                            (rid,)), "result")
        self.assertGreater(row["result"]["documents_total"], first,
                           "новые документы не дошли до этапа обработки")
        self.assertEqual(stages_status(rid)["report"], "completed")
        rep = db.dec(db.one("SELECT * FROM reporting_reports WHERE research_id=? ORDER BY rowid DESC LIMIT 1",
                            (rid,)), "files")
        self.assertTrue(rep and rep["files"], "отчёт не пересобран")
        self.assertNotEqual(rep["id"], (first_report or {}).get("id"),
                            "отчёт остался прежним после поступления новых документов")

    def test_RER_04_recompute_is_visible(self):
        """RER-04: пересчёт отражён в истории состояний и журнале действий."""
        from isheika import journal
        rid = self._offline_research()
        W.start(rid)
        wait_done(rid)
        W.invalidate_dependents(rid, "source_search", reason="испытание видимости")
        hist = db.query("""SELECT * FROM core_state_history WHERE entity_kind='task'
                           AND to_state='queued' AND reason LIKE '%испытание видимости%'""")
        self.assertTrue(hist, "переход в очередь пересчёта не записан в историю состояний")
        rows = journal.query(kind="workflow", limit=50)["items"]
        self.assertTrue([r for r in rows if r["action"] == "workflow.recompute"],
                        "пересчёт не отражён в журнале действий")
