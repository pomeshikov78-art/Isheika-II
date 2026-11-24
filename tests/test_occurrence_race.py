"""Испытания идемпотентности вхождения при параллельном поиске (ИД-20, ред. 1.5.0).

Основание — плавающий провал испытания `test_resume_keeps_completed_stages`
на полном наборе: этап `source_search` иногда завершался как `partial`,
а при продолжении пересчитывался и по ИД-17 тянул за собой этапы 4–12.
Разбор показал причину: две ветви одного источника находят один и тот же URL
одновременно; проверка «есть ли вхождение» и вставка не атомарны, поэтому
срабатывал UNIQUE(research_id, source_code, canonical_url) и ВЕСЬ источник
падал в failed с ошибкой
«UNIQUE constraint failed: content_occurrences.research_id, ...».

OCC-01 — гонка воспроизводится детерминированно (предпроверка «не видит» строку):
         вхождение переиспользуется, исключение не выходит наружу.
OCC-02 — параллельное сохранение одного URL из нескольких потоков не теряет
         документы и не роняет источник.
"""
from __future__ import annotations

import threading
from unittest import mock

from isheika.search import dedup as DD
from isheika.storage import db

from .base import BaseCase


class OccurrenceRaceTests(BaseCase):
    def test_OCC_01_duplicate_occurrence_is_idempotent(self):
        rid = self.make_research()
        doc = self.document("Tropospheric scatter link measurements",
                            abstract="Measured beyond-horizon tropospheric link performance.")
        first = DD.store(rid, doc)
        real_one = db.one
        seen = {"n": 0}

        def blind_one(sql, params=()):
            # Имитируем окно гонки: предпроверка вхождения не видит уже вставленную строку.
            if "FROM content_occurrences" in sql and "canonical_url=?" in sql and seen["n"] == 0:
                seen["n"] += 1
                return None
            return real_one(sql, params)

        with mock.patch.object(db, "one", blind_one):
            second = DD.store(rid, doc)
        self.assertEqual(second["occurrence_id"], first["occurrence_id"],
                         "вхождение должно переиспользоваться, а не создаваться заново")
        self.assertFalse(second["new_occurrence"])
        self.assertEqual(db.count("content_occurrences", "research_id=?", (rid,)), 1)

    def test_OCC_02_parallel_store_keeps_single_occurrence(self):
        rid = self.make_research()
        doc = self.document("Radio relay link under arctic conditions",
                            abstract="Microwave radio relay link trials in the arctic.")
        barrier = threading.Barrier(6)
        errors: list[str] = []
        results: list[dict] = []
        lock = threading.Lock()

        def worker():
            barrier.wait()
            try:
                r = DD.store(rid, doc)
                with lock:
                    results.append(r)
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(f"{type(e).__name__}: {e}")

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertEqual(errors, [], "параллельное обнаружение одного URL не должно ронять источник")
        self.assertEqual(len(results), 6)
        self.assertEqual(db.count("content_occurrences", "research_id=?", (rid,)), 1)
        self.assertEqual(len({r["document_id"] for r in results}), 1)
