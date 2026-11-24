#!/usr/bin/env python3
"""Точка входа «ИЩЕЙКА НТР AI».

    python3 run.py                 # профиль DEV, порт 8000, без внешних зависимостей
    python3 run.py --port 8080
    python3 run.py --no-network    # полностью офлайн (имитационный коннектор)
    python3 run.py --allow-paid    # разрешить платные маршруты ИИ (по умолчанию запрещено)

Промышленный контур (ТЗ-05 §9.2): uvicorn через isheika/api/adapters_fastapi.py.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    from isheika.config import configure_console
    configure_console()          # кириллица в консоли Windows (cp1252/cp866)
    ap = argparse.ArgumentParser(description="ИЩЕЙКА НТР AI — серверное ядро")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--profile", choices=["DEV", "PILOT", "PROD"], default=None)
    ap.add_argument("--no-network", action="store_true", help="отключить исходящие запросы")
    ap.add_argument("--allow-paid", action="store_true", help="разрешить платные вызовы ИИ")
    ap.add_argument("--email", default=None, help="контактный e-mail для polite pool / Unpaywall")
    args = ap.parse_args()

    from isheika.config import SETTINGS
    if args.profile:
        SETTINGS.profile = args.profile
    if args.no_network:
        SETTINGS.network_enabled = False
    if args.allow_paid:
        SETTINGS.allow_paid_ai = True
    if args.email:
        SETTINGS.contact_email = args.email
    if args.host:
        SETTINGS.host = args.host
    if args.port:
        SETTINGS.port = args.port

    from isheika.api.server import main as serve
    return serve()


if __name__ == "__main__":
    raise SystemExit(main())
