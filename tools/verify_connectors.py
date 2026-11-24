#!/usr/bin/env python3
"""TOOL-02. Верификация коннекторов и источников (ТЗ-01 §3.3, ПРИЛОЖЕНИЕ А перечня).

    python3 tools/verify_connectors.py                 # проверка всех коннекторов
    python3 tools/verify_connectors.py --code CON-OPENALEX
    python3 tools/verify_connectors.py --offline       # без сети: только конфигурация
    python3 tools/verify_connectors.py --json var/connector-health.json

Для каждого коннектора фиксируется: статус, причина, задержка, наличие ключа,
политика robots, лимиты. Статус источника в реестре обновляется автоматически
(CANDIDATE → TESTED → CONNECTED / RESTRICTED / UNAVAILABLE).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default=None, help="код одного коннектора")
    ap.add_argument("--offline", action="store_true", help="не выполнять сетевых обращений")
    ap.add_argument("--json", default=None, help="путь для JSON-отчёта")
    args = ap.parse_args()

    from isheika.config import SETTINGS
    from isheika.storage import db
    from isheika.registry import loader
    from isheika.api import service as S
    from isheika.workflow import pipeline  # noqa: F401  регистрация этапов

    SETTINGS.ensure_dirs()
    db.init_db()
    loader.seed_all()
    if args.offline:
        SETTINGS.network_enabled = False

    rows = S.connectors()
    if args.code:
        rows = [r for r in rows if r["code"] == args.code]
    results = []
    print(f'{"КОД":22} {"РЕАЛ.":11} {"КЛЮЧ":6} {"СТАТУС":16} {"мс":>6}  ПРИЧИНА')
    for r in rows:
        t0 = time.time()
        if args.offline:
            res = {"code": r["code"], "status": "not_checked",
                   "reason": "офлайн-режим: сетевые обращения отключены"}
        else:
            try:
                res = S.connector_health(r["code"], actor="verify-tool")[0]
            except Exception as e:  # noqa: BLE001
                res = {"code": r["code"], "status": "error", "reason": str(e)[:160]}
        ms = int((time.time() - t0) * 1000)
        key = "нет" if not r["requires_key"] else ("есть" if r["key_configured"] else "нужен")
        print(f'{r["code"]:22} {r["implementation"]:11} {key:6} {res["status"]:16} {ms:6}  '
              f'{str(res.get("reason") or "")[:80]}')
        results.append({**res, "latency_ms": ms, "implementation": r["implementation"],
                        "requires_key": bool(r["requires_key"]), "key_configured": r["key_configured"],
                        "robots_policy": r.get("robots_policy"), "limits": r.get("limits"),
                        "source_code": r["source_code"], "docs_url": r.get("docs_url")})

    ok = sum(1 for r in results if r["status"] == "active")
    deg = sum(1 for r in results if r["status"] in ("degraded", "restricted"))
    bad = sum(1 for r in results if r["status"] in ("error", "unavailable", "auth_error"))
    print(f"\nИтого: {len(results)} коннекторов · активных {ok} · ограниченных/деградация {deg} · недоступных {bad}")
    print("Источников в реестре:", db.count("registry_sources"),
          "· подключено:", db.count("registry_sources", "integration_status='CONNECTED'"),
          "· протестировано:", db.count("registry_sources", "integration_status='TESTED'"))
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump({"checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "network_enabled": SETTINGS.network_enabled, "items": results}, f,
                      ensure_ascii=False, indent=1)
        print("JSON-отчёт:", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
