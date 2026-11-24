"""Журнал загрузки и самопроверка исправности (замечание пользователя: «белый экран»).

Каждый шаг запуска фиксируется с результатом, длительностью и подробностями:
конфигурация → каталоги → БД и миграции → реестры → ресурсы интерфейса →
маршруты API → планировщик → привязка порта. Журнал доступен:

* в консоли процесса (`run.py` печатает его при старте);
* файлами `boot-log.txt` / `boot-log.json` в каталоге данных;
* по `GET /api/v1/boot-log` (без аутентификации: секретов и персональных
  данных в журнале нет) и `GET /api/v1/boot-log/export?fmt=txt|json`;
* на экране загрузки в браузере — до и независимо от инициализации интерфейса.

Самопроверка (`self_check`) проверяет то, из-за чего интерфейс может не
открыться: доступность каталога данных, целостность БД, полноту реестров,
**наличие и тип каждого ресурса интерфейса**, число маршрутов, состояние
подсистем. Отказ фиксируется как FAIL с причиной, а не «молча».
"""
from __future__ import annotations

import json
import os
import platform
import re
import sys
import time
from contextlib import contextmanager

from . import __version__
from .config import DATA_DIR, SETTINGS, WEB_DIR
from .contracts import iso_now, new_id
from .storage import db

BOOT_ID = new_id("boot-")
STARTED_AT = iso_now()
_STEPS: list[dict] = []
_LAST_CHECKS: list[dict] = []


def record(step: str, status: str = "ok", detail: str = "", duration_ms: float | None = None) -> dict:
    row = {"at": iso_now(), "step": step, "status": status,
           "detail": str(detail)[:600], "duration_ms": None if duration_ms is None else round(duration_ms, 2)}
    _STEPS.append(row)
    try:
        db.insert("ops_boot_log", {"id": new_id("blg-"), "boot_id": BOOT_ID, "at": row["at"],
                                   "step": step, "status": status, "detail": row["detail"],
                                   "duration_ms": row["duration_ms"]})
    except Exception:
        pass                      # журнал не должен ронять запуск (например, до init_db)
    return row


@contextmanager
def step(name: str):
    """Контекст шага: результат и длительность фиксируются автоматически."""
    started = time.perf_counter()
    info = {"detail": ""}
    try:
        yield info
    except Exception as exc:
        record(name, "fail", f"{type(exc).__name__}: {exc}", (time.perf_counter() - started) * 1000)
        raise
    record(name, "ok", info.get("detail", ""), (time.perf_counter() - started) * 1000)


def ui_assets() -> list[dict]:
    """Ресурсы, перечисленные в index.html: путь, наличие, размер, тип содержимого."""
    from .api.server import static_ctype, static_target

    index = os.path.join(WEB_DIR, "index.html")
    out: list[dict] = []
    if not os.path.isfile(index):
        return [{"asset": "index.html", "exists": False, "bytes": 0, "ctype": "", "ok": False}]
    with open(index, encoding="utf-8") as f:
        html = f.read()
    # сценарии вырезаются: внутри них встречаются строки вида src="..." в коде
    markup = re.sub(r"(<script[^>]*>)[\s\S]*?</script>", r"\1</script>", html)
    refs = re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', markup)
    names = ["index.html"]
    for r in refs:
        r = r.split("?", 1)[0].split("#", 1)[0].strip()
        if (not r or r.startswith(("http", "data:", "//", "api/", "mailto:"))
                or any(ch in r for ch in " '+<>")):
            continue
        names.append(r)
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        rel = static_target("/" + name.lstrip("/"))
        full = os.path.join(WEB_DIR, *(rel or "").split("/")) if rel else ""
        exists = bool(rel) and os.path.isfile(full)
        size = os.path.getsize(full) if exists else 0
        out.append({"asset": name, "exists": exists, "bytes": size,
                    "ctype": static_ctype(full) if exists else "", "ok": bool(exists and size > 0)})
    return out


def self_check() -> list[dict]:
    """Проверки исправности. Каждая возвращает ok/detail — без «зелёного по умолчанию»."""
    global _LAST_CHECKS
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str = ""):
        checks.append({"check": name, "ok": bool(ok), "detail": str(detail)[:400]})

    try:
        SETTINGS.ensure_dirs()
        probe = os.path.join(DATA_DIR, ".boot-probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write(STARTED_AT)
        os.remove(probe)
        add("Каталог данных доступен на запись", True, DATA_DIR)
    except Exception as exc:
        add("Каталог данных доступен на запись", False, f"{type(exc).__name__}: {exc}")

    try:
        state = next(iter((db.one("PRAGMA quick_check") or {}).values()), "unknown")
        migrations = [r["version"] for r in db.query("SELECT version FROM meta_migrations ORDER BY version")]
        add("База данных целостна", state == "ok", f"quick_check={state}; миграции: {', '.join(migrations)}")
    except Exception as exc:
        add("База данных целостна", False, f"{type(exc).__name__}: {exc}")

    try:
        counts = {t: db.count(t) for t in ("registry_sources", "dict_countries", "registry_connectors", "ai_providers")}
        add("Реестры загружены", counts["registry_sources"] > 0 and counts["dict_countries"] > 0,
            "; ".join(f"{k}={v}" for k, v in counts.items()))
    except Exception as exc:
        add("Реестры загружены", False, f"{type(exc).__name__}: {exc}")

    assets = ui_assets()
    missing = [a["asset"] for a in assets if not a["ok"]]
    add("Ресурсы интерфейса на месте", not missing,
        f"проверено {len(assets)}" + (("; отсутствуют: " + ", ".join(missing)) if missing else ""))

    try:
        from .api.server import ROUTES
        add("Маршруты API зарегистрированы", len(ROUTES) > 0, f"{len(ROUTES)} маршрутов")
    except Exception as exc:
        add("Маршруты API зарегистрированы", False, f"{type(exc).__name__}: {exc}")

    try:
        from . import slo
        probes = slo.run_probes()
        bad = [p["component"] for p in probes if not p["ok"]]
        add("Подсистемы отвечают", not bad,
            "; ".join(f"{p['component']}={'ok' if p['ok'] else 'FAIL'} ({p['latency_ms']} мс)" for p in probes))
    except Exception as exc:
        add("Подсистемы отвечают", False, f"{type(exc).__name__}: {exc}")

    _LAST_CHECKS = checks
    return checks


def snapshot(*, with_checks: bool = True) -> dict:
    checks = self_check() if with_checks else _LAST_CHECKS
    return {
        "boot_id": BOOT_ID, "started_at": STARTED_AT, "generated_at": iso_now(),
        "app_version": __version__, "profile": SETTINGS.profile,
        "python": sys.version.split()[0], "platform": platform.system() + " " + platform.release(),
        "data_dir": DATA_DIR, "web_dir": WEB_DIR,
        "network_enabled": SETTINGS.network_enabled, "paid_ai_allowed": SETTINGS.allow_paid_ai,
        "steps": list(_STEPS), "checks": checks, "assets": ui_assets(),
        "ok": all(c["ok"] for c in checks) and not any(s["status"] == "fail" for s in _STEPS),
        "note": "Журнал загрузки не содержит ключей и персональных данных.",
    }


def export(fmt: str = "txt", *, with_checks: bool = True) -> str:
    snap = snapshot(with_checks=with_checks)
    if fmt == "json":
        return json.dumps(snap, ensure_ascii=False, indent=2)
    lines = [f"ИЩЕЙКА НТР AI {snap['app_version']} — журнал загрузки {snap['boot_id']}",
             f"Начало: {snap['started_at']}   Профиль: {snap['profile']}   Python {snap['python']} ({snap['platform']})",
             f"Каталог данных: {snap['data_dir']}", "", "ШАГИ ЗАПУСКА"]
    for s in snap["steps"]:
        ms = "" if s["duration_ms"] is None else f" [{s['duration_ms']} мс]"
        lines.append(f"  {'OK  ' if s['status'] == 'ok' else 'FAIL'} {s['at']}  {s['step']}{ms}"
                     + (f" — {s['detail']}" if s["detail"] else ""))
    lines += ["", "САМОПРОВЕРКА"]
    for c in snap["checks"]:
        lines.append(f"  {'OK  ' if c['ok'] else 'FAIL'} {c['check']} — {c['detail']}")
    lines += ["", "РЕСУРСЫ ИНТЕРФЕЙСА"]
    for a in snap["assets"]:
        lines.append(f"  {'OK  ' if a['ok'] else 'FAIL'} {a['asset']} — {a['bytes']} Б, {a['ctype'] or 'нет файла'}")
    lines += ["", "ИТОГ: " + ("исправно" if snap["ok"] else "ЕСТЬ ОТКАЗЫ — см. строки FAIL")]
    return "\n".join(lines) + "\n"


def write_files() -> dict:
    """Сохранение журнала в каталог данных — доступен, даже если браузер не открылся."""
    out = {}
    try:
        SETTINGS.ensure_dirs()
        for fmt, name in (("txt", "boot-log.txt"), ("json", "boot-log.json")):
            path = os.path.join(DATA_DIR, name)
            with open(path, "w", encoding="utf-8") as f:
                f.write(export(fmt))
            out[fmt] = path
    except Exception:
        pass
    return out


def console_report() -> str:
    snap = snapshot()
    head = f"Загрузка {snap['boot_id']}: " + ("исправно" if snap["ok"] else "ЕСТЬ ОТКАЗЫ")
    lines = [head]
    for s in snap["steps"]:
        lines.append(f"  {'✓' if s['status'] == 'ok' else '✗'} {s['step']}"
                     + (f" — {s['detail']}" if s["detail"] else ""))
    for c in snap["checks"]:
        lines.append(f"  {'✓' if c['ok'] else '✗'} {c['check']} — {c['detail']}")
    return "\n".join(lines)
