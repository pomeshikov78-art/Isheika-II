"""Испытания повторного запуска исследования и проб подсистем (редакция 1.4.2).

Основание — журнал действий с машины пользователя (ред. 1.4.1):
  * `stage.source_search` → `KeyError: 'parsed_query'` при попытке 2: завершённые
    этапы пропускаются, живых объектов в контексте нет, а этап 3 брал их напрямую;
  * `system.error` → `FileNotFoundError … '.slo-probe'`: параллельные пробы
    хранилища удаляли общий файл друг у друга и давали ложный алерт COMPONENT_DOWN.

RES-01…05 — контекст восстанавливается из сохранённого состояния.
SLO-09 — параллельные пробы хранилища не мешают друг другу.
"""
from __future__ import annotations

import threading
import time

from isheika import slo
from isheika.storage import db
from isheika.workflow import engine as W, pipeline as P
from tests.base import BaseCase


def run_offline(case: BaseCase, **settings) -> str:
    s = {"connector_codes": ["CON-SIM"], "max_docs_per_source": 3}
    s.update(settings)
    rid = case.make_research(settings=s)
    W.start(rid)
    deadline = time.time() + 120
    while time.time() < deadline:
        st = W.status(rid)
        if not st["running"] and all(j["status"] in ("completed", "partial", "failed", "cancelled", "skipped")
                                     for j in st["jobs"]):
            break
        time.sleep(0.2)
    return rid


def job_of(rid: str, stage: str) -> dict:
    return db.dec(db.one("SELECT * FROM workflow_jobs WHERE research_id=? AND stage=?", (rid, stage)),
                  "depends_on", "result")


class ResumeContextTests(BaseCase):
    def test_RES_01_source_search_without_live_context(self):
        """RES-01: этап 3 работает при пустом контексте — запрос берётся из состояния."""
        rid = run_offline(self)
        job = job_of(rid, "source_search")
        res = P.stage_source_search(job, {"research_id": rid})     # до исправления — KeyError
        self.assertIn("sources_planned", res)
        self.assertGreater(res["sources_planned"], 0)

    def test_RES_02_relevance_filter_without_live_context(self):
        """RES-02: этап 5 работает при пустом контексте (запрос и расширение восстановлены)."""
        rid = run_offline(self)
        job = job_of(rid, "relevance_filter")
        res = P.stage_relevance_filter(job, {"research_id": rid})
        self.assertIn("assessed", res)

    def test_RES_03_expansion_restored_from_saved_model(self):
        """RES-03: расширение восстанавливается из сохранённой модели, а не пересобирается иначе."""
        rid = run_offline(self)
        job = job_of(rid, "source_search")
        ctx: dict = {"research_id": rid}
        ex = P._expansion(job, ctx)
        saved = db.dec(db.one("SELECT * FROM search_queries WHERE research_id=? ORDER BY created_at DESC LIMIT 1",
                              (rid,)), "expansions")["expansions"]
        self.assertEqual(ex.core_terms, saved["core_terms"])
        self.assertEqual([b.name for b in ex.branches], [b["name"] for b in saved["branches"]])
        self.assertIs(ctx["expansion"], ex, "восстановленный объект должен кешироваться в контексте")

    def test_RES_04_resume_after_failed_stage_completes(self):
        """RES-04: продолжение после сбоя этапа 3 доходит до конца без KeyError."""
        rid = run_offline(self)
        job = job_of(rid, "source_search")
        db.update("workflow_jobs", "id", job["id"], {"status": "failed", "error_code": "E_INTERNAL",
                                                    "error_message": "проверка продолжения"})
        W.start(rid, resume=True)
        deadline = time.time() + 120
        while time.time() < deadline and W.status(rid)["running"]:
            time.sleep(0.2)
        st = W.status(rid)
        stages = {j["stage"]: j for j in st["jobs"]}
        self.assertIn(stages["source_search"]["status"], ("completed", "partial"))
        self.assertNotIn("parsed_query", (stages["source_search"].get("error_message") or ""))
        errors = db.query("SELECT message FROM ops_journal WHERE research_id=? AND level='error' "
                          "AND action LIKE 'stage.%'", (rid,))
        self.assertFalse([e for e in errors if "parsed_query" in (e["message"] or "")],
                         "повторный запуск снова упал на отсутствующем контексте")

    def test_RES_05_open_run_is_finished_after_resume(self):
        """RES-05: незавершённый запуск воспроизводимости закрывается, а не остаётся «running»."""
        rid = run_offline(self)
        run = db.one("SELECT id FROM research_runs WHERE research_id=? ORDER BY started_at DESC LIMIT 1", (rid,))
        self.assertTrue(run)
        db.update("research_runs", "id", run["id"], {"status": "running", "finished_at": None})
        job = job_of(rid, "report")
        ctx: dict = {"research_id": rid}
        self.assertEqual(P._run_id(job, ctx), run["id"])
        P.stage_report(job, ctx)
        after = db.one("SELECT status, finished_at FROM research_runs WHERE id=?", (run["id"],))
        self.assertEqual(after["status"], "completed")
        self.assertTrue(after["finished_at"])


class DedupSummaryTests(BaseCase):
    def test_RES_06_summary_separates_new_and_already_known(self):
        """RES-06: «дубли» корпуса не выдаются за дубли исследования — сводка честна."""
        rid1 = run_offline(self, query="6G терагерцовая связь")
        rid2 = run_offline(self, query="6G терагерцовая связь")
        j1 = db.dec(job_of(rid1, "document_processing"), "result")["result"]
        j2 = db.dec(job_of(rid2, "document_processing"), "result")["result"]
        for res in (j1, j2):
            self.assertIn("new_in_corpus", res)
            self.assertIn("known_before", res)
            self.assertEqual(res["new_in_corpus"] + res["known_before"], res["documents_total"])
        self.assertGreater(j1["new_in_corpus"], 0, "первый запуск даёт новые документы корпуса")
        self.assertEqual(j2["new_in_corpus"], 0, "повторный запрос не добавляет новых документов")
        self.assertEqual(j2["known_before"], j2["documents_total"])


class StorageProbeTests(BaseCase):
    def test_SLO_09_parallel_storage_probes_do_not_collide(self):
        """SLO-09: параллельные пробы хранилища не удаляют файл друг у друга."""
        results: list = []
        lock = threading.Lock()

        def probe():
            for _ in range(6):
                r = slo.probe("storage")
                with lock:
                    results.append(r)

        threads = [threading.Thread(target=probe) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
        self.assertEqual(len(results), 24)
        bad = [r for r in results if not r["ok"]]
        self.assertFalse(bad, f"ложные отказы хранилища: {[r['detail'] for r in bad][:3]}")
