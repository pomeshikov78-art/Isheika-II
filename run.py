#!/usr/bin/env python3
"""Точка входа «ИЩЕЙКА НТР AI».

    python3 run.py                 # профиль DEV, порт 8000, без внешних зависимостей
    python3 run.py --port 8080
    python3 run.py --no-network    # полностью офлайн (имитационный коннектор)
    python3 run.py --allow-paid    # разрешить платные маршруты ИИ (по умолчанию запрещено)
    python3 run.py --open-browser  # открыть интерфейс в браузере после запуска
    python3 run.py --port-auto     # если порт занят, взять следующий свободный
    python3 run.py --backup        # резервная копия состояния и выход
    python3 run.py --list-backups  # реестр резервных копий
    python3 run.py --verify-backup ID|ПУТЬ   # проверка копии без восстановления
    python3 run.py --restore ID|ПУТЬ --yes   # восстановление (сервер остановлен)

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
    ap.add_argument("--open-browser", action="store_true", help="открыть браузер после запуска сервера")
    ap.add_argument("--port-auto", action="store_true", help="при занятом порте искать следующий свободный")
    ap.add_argument("--backup", action="store_true", help="создать резервную копию состояния и выйти")
    ap.add_argument("--backup-dir", default=None, help="каталог для резервной копии")
    ap.add_argument("--list-backups", action="store_true", help="показать реестр резервных копий")
    ap.add_argument("--verify-backup", default=None, metavar="ID|ПУТЬ", help="проверить копию")
    ap.add_argument("--restore", default=None, metavar="ID|ПУТЬ", help="восстановить состояние из копии")
    ap.add_argument("--yes", action="store_true", help="подтверждение необратимых операций")
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

    # Эксплуатационные операции выполняются ДО запуска сервера и завершают работу:
    # восстановление требует, чтобы с БД не работали другие потоки (ROADMAP P6).
    if args.backup or args.list_backups or args.verify_backup or args.restore:
        return _ops(args)

    from isheika.api.server import main as serve
    return serve(open_browser=args.open_browser, port_auto=args.port_auto)


def _ops(args) -> int:
    """Резервное копирование и восстановление из командной строки."""
    import json

    from isheika import backup as BK, slo
    from isheika.storage import db
    db.init_db()
    if args.backup:
        row = BK.create(actor="cli", kind="cli", dest_dir=args.backup_dir)
        check = BK.verify(row["path"])
        print(f"Копия: {row['path']}")
        print(f"Размер: {row['size_bytes']} Б  sha256={row['sha256']}")
        print("Проверка: " + ("пройдена" if check["ok"] else "НЕ пройдена"))
        for c in check["checks"]:
            print(f"  {'✓' if c['ok'] else '✗'} {c['check']}: {c['detail']}")
        return 0 if check["ok"] else 1
    if args.list_backups:
        items = BK.list_backups()
        if not items:
            print("Резервных копий нет. Создайте: python3 run.py --backup")
        for r in items:
            print(f"{r['id']}  {r['created_at']}  {r['size_bytes']} Б  "
                  f"{r['kind']}  {'есть' if r['exists'] else 'ФАЙЛ ОТСУТСТВУЕТ'}  {r['file_name']}")
        return 0
    if args.verify_backup:
        res = BK.verify(BK.resolve(args.verify_backup))
        print(json.dumps({"ok": res["ok"], "checks": res["checks"]}, ensure_ascii=False, indent=2))
        return 0 if res["ok"] else 1
    if args.restore:
        if not args.yes:
            print("Восстановление перезаписывает текущее состояние. "
                  "Подтвердите ключом --yes (перед записью снимается копия текущего состояния).")
            return 2
        res = BK.restore(args.restore, actor="cli", confirm=True)
        print(f"Восстановлено из: {res['restored_from']}")
        print(f"Копия прежнего состояния: {res['safety_backup']['path']}")
        print("Состав после восстановления: " + json.dumps(res["counts"], ensure_ascii=False))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
