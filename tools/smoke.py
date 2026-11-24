#!/usr/bin/env python3
"""Сквозная проверка (smoke test) полного цикла исследования.

Запуск:  python3 tools/smoke.py [--live] [--query "..."] [--limit N]
Без --live используется имитационный коннектор DEV-профиля (без сети).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from isheika.config import SETTINGS
from isheika.storage import db
from isheika.registry import loader
from isheika.workflow import engine, pipeline  # noqa: F401
from isheika.api import service


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="использовать реальные открытые API")
    ap.add_argument("--query", default="Тропосферная связь загоризонтная передача данных")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--wait", type=int, default=300)
    args = ap.parse_args()

    db.init_db()
    loader.seed_all()
    settings = {"include_simulation": not args.live,
                "max_docs_per_source": args.limit,
                "categories": ["C01", "C02", "C04", "C11"] if args.live else ["C01", "C02", "C04", "C05", "C06", "C07", "C09", "C11"]}
    if args.live:
        settings["connector_codes"] = ["CON-OPENALEX", "CON-CROSSREF", "CON-ARXIV", "CON-DOAJ",
                                       "CON-EUROPEPMC", "CON-DATACITE", "CON-OSTI", "CON-HAL",
                                       "CON-ZENODO", "CON-OPENAIRE", "CON-STACKEXCHANGE"]
    r = service.create_research({"title": args.query[:120], "query": args.query,
                                 "goal": "Оценка состояния и перспектив технологии",
                                 "countries": "all", "languages": ["ru", "en"],
                                 "period_from": 2015, "period_to": 2026,
                                 "settings": settings})
    rid = r["id"]
    print("research:", rid)
    engine.start(rid)
    t0 = time.time()
    while time.time() - t0 < args.wait:
        time.sleep(2)
        st = db.one("SELECT status FROM core_researches WHERE id=?", (rid,))
        jobs = db.query("SELECT stage,status,error_message FROM workflow_jobs WHERE research_id=? ORDER BY created_at", (rid,))
        done = sum(1 for j in jobs if j["status"] in ("completed", "partial", "failed", "skipped"))
        print(f'  [{int(time.time()-t0):3d}s] {st["status"]:9s} {done}/{len(jobs)}', flush=True)
        if st["status"] in ("completed", "partial", "failed", "cancelled"):
            break
    print("\n--- ЭТАПЫ ---")
    for j in db.query("SELECT stage,status,error_message,result FROM workflow_jobs WHERE research_id=? ORDER BY created_at", (rid,)):
        print(f'{j["stage"]:22s} {j["status"]:10s} {(j["error_message"] or "")[:90]}')
    print("\n--- ИТОГИ ---")
    trl = db.one("SELECT trl,confidence FROM analytics_trl WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (rid,))
    fea = db.one("SELECT score,coverage,range_low,range_high,interpretation FROM analytics_feasibility WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (rid,))
    print("документов:", db.count("research_documents", "research_id=?", (rid,)))
    print("прямых:", db.count("research_documents", "research_id=? AND relevance_class='DIRECT'", (rid,)))
    print("TRL:", trl)
    print("F:", fea)
    print("evidence:", db.count("evidence_items", "research_id=?", (rid,)))
    print("claims:", db.count("knowledge_claims", "research_id=?", (rid,)))
    rep = db.one("SELECT status,files,warnings FROM reporting_reports WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (rid,))
    print("отчёт:", (rep or {}).get("status"), list(json.loads((rep or {}).get("files") or "{}")))
    for w in json.loads((rep or {}).get("warnings") or "[]"):
        print("  !", w)
    print("\nID исследования для UI:", rid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
