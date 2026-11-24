#!/usr/bin/env python3
"""Сборка единого исполняемого файла «ИЩЕЙКА НТР AI» для Windows.

    python3 tools/build_exe.py                     # release/ISHEIKA-NTR-AI.exe
    python3 tools/build_exe.py --verify-wine       # + проверка запуска образа под wine64
    python3 tools/build_exe.py --no-download       # сборка только из кеша (без сети)

Результат — один файл `.exe`, который на машине пользователя:
  1. распаковывает во временный каталог встроенный CPython 3.11 (x64) и приложение;
  2. запускает `isheika.cmd` → сервер на 127.0.0.1:8000 и открывает браузер;
  3. хранит все данные вне временного каталога: %LOCALAPPDATA%\\IsheikaNTR-AI.

Формат файла: 7zSD.sfx (SFX-заголовок) + конфигурационный блок + 7z-архив.
Установка Python и какие-либо пакеты на целевой машине НЕ требуются: ядро
использует только стандартную библиотеку (sqlite3 входит в embedded-дистрибутив).

Зависимости сборки: Python 3.10+, консольный 7-Zip (`7z`/`7za`/`7zr`) в PATH.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import threading
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_NAME = "ISHEIKA-NTR-AI"
PY_VERSION = "3.11.9"
PY_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
PY_SHA256 = "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"
SFX_SHA256 = "18b4c189f195d55fe1e6c08d6a186d31c89d6c3c55afe122a55230078f7ea294"

EXCLUDE_DIRS = {"__pycache__", "node_modules", "var", ".cache", ".git", "release",
                ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build"}
EXCLUDE_EXT = {".pyc", ".pyo", ".db", ".db-journal", ".log", ".enc"}
APP_TOP = ["run.py", "isheika", "tests", "tools", "docs",
           "README.md", "ARCHITECTURE.md", "ROADMAP.md", "requirements-optional.txt"]

# ВАЖНО (проверено по исходнику SFXSetup.cpp из LZMA SDK):
#   RunProgram выполняется как CreateProcess(NULL, dirPrefix + RunProgram),
#   где dirPrefix по умолчанию ".\\" — поэтому команда с аргументами
#   ("cmd /c isheika.cmd") превращается в ".\\cmd" и даёт ошибку
#   «Не удается найти указанный файл». ExecuteFile идёт через ShellExecuteEx
#   БЕЗ префикса: cmd.exe находится в System32, рабочий каталог — каталог
#   распаковки, поэтому "isheika.cmd" находится корректно.
# Имя лаунчера НЕ должно совпадать с внутренней командой cmd.exe: файл
# "start.cmd" парсер cmd (проверено в wine) принимает за команду START с
# аргументом ".cmd" и выдаёт "ShellExecuteEx failed: File not found".
# Поэтому лаунчер называется isheika.cmd — коллизий нет.
# Имя сценария запуска. Не может совпадать с внутренней командой cmd.exe
# (start, run, call, ...): "start.cmd" cmd разбирает как START + ".cmd".
LAUNCH_SCRIPT = "isheika.cmd"

SFX_CONFIG = """;!@Install@!UTF-8!
Title="ИЩЕЙКА НТР AI {version}"
BeginPrompt="Запустить «ИЩЕЙКА НТР AI {version}»?\\n\\nПриложение будет распаковано во временный каталог, данные сохраняются в %LOCALAPPDATA%\\IsheikaNTR-AI."
Progress="yes"
ExecuteFile="cmd.exe"
ExecuteParameters="/c isheika.cmd"
;!@InstallEnd@!
"""

START_CMD = r"""@echo off
rem Единый файл запуска «ИЩЕЙКА НТР AI». Данные — вне временного каталога SFX.
setlocal
chcp 65001 >nul
title ИЩЕЙКА НТР AI — сервер
set "ROOT=%~dp0"
set "ISHEIKA_DATA=%LOCALAPPDATA%\IsheikaNTR-AI"
if not exist "%ISHEIKA_DATA%" mkdir "%ISHEIKA_DATA%"
set "ISHEIKA_PORT=__PORT__"
rem Порт принимается только числом: SFX дописывает свои ключи в командную строку.
rem Проверка средствами самого cmd (без findstr и внешних утилит).
rem Ветвление записано ПЛОСКО (goto), без вложенных скобок: парсер cmd в wine
rem не выполняет вложенный блок "if defined ... ( for /f ... )" и молча
rem теряет аргумент порта. Плоская форма работает и в Windows, и в wine.
set "ARG=%~1"
set "NONNUM="
if not defined ARG goto :launch
for /f "delims=0123456789" %%A in ("%ARG%") do set "NONNUM=1"
if defined NONNUM goto :launch
set "ISHEIKA_PORT=%ARG%"

:launch

echo ============================================================
echo   ИЩЕЙКА НТР AI — аналитика научно-технологического развития
echo   Данные:    %ISHEIKA_DATA%
echo   Интерфейс: http://127.0.0.1:%ISHEIKA_PORT%/
echo   Вход:      admin / dev:admin   (роли: lead, analyst, expert, observer, auditor)
echo   Остановка: Ctrl+C или закройте это окно
echo ============================================================
echo.

"%ROOT%python\python.exe" "%ROOT%app\run.py" --host 127.0.0.1 --port %ISHEIKA_PORT% --port-auto --open-browser
if errorlevel 1 goto :failed
goto :finish

:failed
echo.
echo Сервер завершился с ошибкой. Попробуйте другой порт: isheika.cmd 8080
echo.
pause

:finish
endlocal
"""

READ_ME = """ИЩЕЙКА НТР AI {version} — единый файл запуска (Windows 10/11 x64)
=====================================================================

ЗАПУСК
  Двойной щелчок по ISHEIKA-NTR-AI.exe → «Да» в запросе запуска.
  Откроется окно сервера и браузер на http://127.0.0.1:8000/.
  Если порт 8000 занят, программа автоматически берёт следующий свободный
  и открывает браузер на нём. Задать порт вручную: isheika.cmd 8080
  (в каталоге распаковки) или сборка с tools/build_exe.py --port 8080.

ВХОД (профиль DEV)
  admin / dev:admin        администратор
  lead / dev:lead          руководитель
  analyst / dev:analyst    аналитик
  expert / dev:expert      эксперт
  observer / dev:observer  наблюдатель
  auditor / dev:auditor    аудитор
  Пароли DEV-профиля подлежат смене при переводе в PILOT/PROD.

ДАННЫЕ
  %LOCALAPPDATA%\\IsheikaNTR-AI  — база SQLite, кеш, файлы отчётов,
  зашифрованное хранилище ключей. Временный каталог распаковки удаляется
  после остановки сервера, данные сохраняются.

РЕЖИМЫ
  По умолчанию разрешены только бесплатные официальные API источников;
  платные вызовы ИИ заблокированы политикой и требуют явного согласия.
  Полностью офлайн-режим: добавьте --no-network в строку запуска python
  в isheika.cmd (имитационный коннектор, документы помечаются «имитация»).

ЖУРНАЛ ЗАГРУЗКИ (диагностика)
  Каждый шаг запуска и самопроверка печатаются в окно сервера и сохраняются:
    %LOCALAPPDATA%\\IsheikaNTR-AI\\boot-log.txt   (и boot-log.json)
  В браузере: http://127.0.0.1:8000/api/v1/boot-log — журнал без входа.
  Экран загрузки показывает журнал сам; при отказе появляется строка FAIL
  с причиной и кнопки «Повторить загрузку» / «Скачать журнал».
  После входа журнал открывается кнопкой 🧾 в верхней панели.

ЕСЛИ БРАУЗЕР ПОКАЗАЛ ПУСТОЙ ЭКРАН
  Откройте http://127.0.0.1:8000/api/v1/boot-log и посмотрите строки FAIL:
  там указано, какой ресурс или подсистема не отвечает. Ранее встречался
  дефект разбора путей на Windows (вместо сценариев отдавалась страница) —
  исправлен; сборка сверяет каждый ресурс внутри образа по размеру и типу.

ЕСЛИ ФАЙЛ НЕ ЗАПУСКАЕТСЯ
  Сообщение «Не удается найти указанный файл» от 7-Zip означает, что модуль
  распаковки не смог запустить сценарий. В этой сборке запуск идёт через
  ShellExecute (ExecuteFile="cmd.exe"), что устраняет причину. Если запуск
  SFX запрещён политикой безопасности или антивирусом:
    1) возьмите ISHEIKA-NTR-AI-portable.zip, распакуйте в любой каталог;
    2) запустите isheika.cmd (можно с номером порта: isheika.cmd 8080).
  Каталог с данными: %LOCALAPPDATA%\IsheikaNTR-AI — его можно удалить для
  полного сброса состояния.

РЕЗЕРВНЫЕ КОПИИ И ДОСТУПНОСТЬ
  Экран «Эксплуатация и SLO» (UI-31): доступность за 24 ч / 7 сут / 30 сут
  (цель 98 %), алерты с основаниями, реестр резервных копий.
  В каталоге распаковки (сервер остановлен):
    python\\python.exe app\\run.py --backup            копия + проверка
    python\\python.exe app\\run.py --list-backups      реестр копий
    python\\python.exe app\\run.py --restore ID --yes  восстановление
  Копии: %LOCALAPPDATA%\\IsheikaNTR-AI\\backups. Мастер-ключ шифрования
  в копию не включается — храните его отдельно. Регламент: app\\docs\\RECOVERY.md.

САМОПРОВЕРКА (необязательно)
  В каталоге распаковки:
    python\\python.exe -m unittest discover -s app\\tests -t app
    python\\python.exe app\\tools\\api_check.py

СОСТАВ ОБРАЗА
  python\\  — встраиваемый CPython {pyver} (x64), только стандартная библиотека
  app\\     — ядро, API, веб-интерфейс, реестры источников, тесты, документация
  isheika.cmd — запуск сервера (браузер открывает сама программа)

ИСХОДНЫЕ ТЕКСТЫ И СБОРКА
  Проект: каталог isheika/ репозитория. Сборка: python3 tools/build_exe.py
  SFX-модуль 7zSD.sfx — 7-Zip / LZMA SDK (Igor Pavlov), GNU LGPL 2.1+,
  см. tools/vendor/README.md. CPython — PSF License.
"""


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sevenzip() -> str:
    for name in ("7z", "7za", "7zr", "7zz"):
        p = shutil.which(name)
        if p:
            return p
    raise SystemExit("Не найден 7-Zip (7z/7za/7zr/7zz) в PATH — он нужен для упаковки образа.")


def fetch_python(cache: str, allow_download: bool) -> str:
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, os.path.basename(PY_URL))
    if os.path.exists(path) and sha256(path) == PY_SHA256:
        return path
    if not allow_download:
        raise SystemExit(f"В кеше нет {path}, а загрузка запрещена (--no-download).")
    print(f"· загрузка {PY_URL}")
    req = urllib.request.Request(PY_URL, headers={"User-Agent": "IsheikaNTR-AI-build/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        shutil.copyfileobj(r, f)
    got = sha256(path)
    if got != PY_SHA256:
        raise SystemExit(f"Контрольная сумма дистрибутива Python не совпала: {got}")
    return path


def copy_app(dst: str) -> int:
    n = 0
    for top in APP_TOP:
        src = os.path.join(ROOT, top)
        if not os.path.exists(src):
            continue
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dst, top))
            n += 1
            continue
        for base, dirs, files in os.walk(src):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS)
            rel = os.path.relpath(base, ROOT)
            out = os.path.join(dst, rel)
            os.makedirs(out, exist_ok=True)
            for name in sorted(files):
                if os.path.splitext(name)[1] in EXCLUDE_EXT:
                    continue
                shutil.copy2(os.path.join(base, name), os.path.join(out, name))
                n += 1
    return n


def app_version() -> str:
    try:
        sys.path.insert(0, ROOT)
        import isheika
        return isheika.__version__
    except Exception:
        return "1.4.1"


def build(args) -> dict:
    sz = sevenzip()
    sfx = args.sfx or os.path.join(ROOT, "tools", "vendor", "7zSD.sfx")
    if not os.path.exists(sfx):
        raise SystemExit(f"SFX-модуль не найден: {sfx}")
    if sha256(sfx) != SFX_SHA256:
        print(f"! внимание: SHA-256 SFX-модуля отличается от эталонного ({sha256(sfx)[:16]}…)")
    py_zip = fetch_python(args.cache, not args.no_download)
    version = args.app_version or app_version()

    work = tempfile.mkdtemp(prefix="isheika-exe-")
    payload = os.path.join(work, "payload")
    os.makedirs(payload)
    try:
        # 1. интерпретатор
        pydir = os.path.join(payload, "python")
        os.makedirs(pydir)
        with zipfile.ZipFile(py_zip) as z:
            z.extractall(pydir)
        with open(os.path.join(pydir, f"python{PY_VERSION.split('.')[0]}{PY_VERSION.split('.')[1]}._pth"),
                  "w", encoding="utf-8") as f:
            f.write("python311.zip\n.\n..\\app\n..\\app\\Lib\\site-packages\n\nimport site\n")

        # 2. приложение
        appdir = os.path.join(payload, "app")
        os.makedirs(appdir)
        count = copy_app(appdir)

        # 3. запуск и памятка
        start = START_CMD.replace("__PORT__", str(args.port))
        for name, text in ((LAUNCH_SCRIPT, start),
                           ("ЗАПУСК.txt", READ_ME.format(version=version, pyver=PY_VERSION))):
            with open(os.path.join(payload, name), "w", encoding="utf-8", newline="\r\n") as f:
                f.write(text)
        with open(os.path.join(payload, "VERSION.txt"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(f"ISHEIKA-NTR-AI {version}\nCPython {PY_VERSION} (embeddable, x64)\n"
                    f"Собрано {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n")

        # 4. архив
        arc = os.path.join(work, "payload.7z")
        entries = sorted(os.listdir(payload))
        subprocess.run([sz, "a", "-t7z", "-mx=7", "-mmt=on", "-bso0", "-bsp0", arc] + entries,
                       cwd=payload, check=True)

        # 5. SFX + config + архив
        out = os.path.abspath(args.out)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        cfg = SFX_CONFIG.format(version=version).encode("utf-8")
        with open(out, "wb") as f:
            f.write(open(sfx, "rb").read())
            f.write(cfg)
            f.write(open(arc, "rb").read())
        info = {
            "artifact": out, "app_version": version, "python": PY_VERSION,
            "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "size_bytes": os.path.getsize(out), "sha256": sha256(out),
            "sfx": {"file": sfx, "sha256": sha256(sfx), "size_bytes": os.path.getsize(sfx)},
            "payload": {"files_in_app": count, "archive_bytes": os.path.getsize(arc),
                        "config_bytes": len(cfg), "top_level": entries},
            "default_port": args.port,
            "data_dir": "%LOCALAPPDATA%\\IsheikaNTR-AI",
            "sevenzip": sz,
        }
        # Запасной вариант поставки: portable-архив с тем же содержимым.
        # Нужен, если политика безопасности запрещает запуск SFX из загрузок.
        zip_path = os.path.splitext(out)[0] + "-portable.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for base, _dirs, files in os.walk(payload):
                for name in sorted(files):
                    full = os.path.join(base, name)
                    z.write(full, os.path.relpath(full, payload))
        info["portable_zip"] = {"file": zip_path, "size_bytes": os.path.getsize(zip_path),
                                "sha256": sha256(zip_path),
                                "note": "распаковать и запустить isheika.cmd — тот же образ без SFX"}
        info["structure"] = check_structure(out)
        print(f"✓ {out}  {info['size_bytes'] / 1048576:.1f} МБ  sha256={info['sha256'][:16]}…")
        print(f"✓ {zip_path}  {info['portable_zip']['size_bytes'] / 1048576:.1f} МБ  (запасной вариант)")

        if args.verify_wine:
            info["wine_check"] = verify_wine(payload, args.port + 11)
        if args.verify_launch:
            info["wine_launch"] = verify_launch(payload, args.port + 21)
        if args.verify_tests:
            info["wine_tests"] = verify_tests(payload)
        if args.verify_linux:
            info["linux_verification"] = verify_linux(payload, args.port + 31)
        with open(out + ".sha256", "w", encoding="utf-8") as f:
            f.write(f"{info['sha256']}  {os.path.basename(out)}\n")
        with open(os.path.join(os.path.dirname(out), "BUILD-INFO.json"), "w", encoding="utf-8") as f:
            json.dump(info, f, ensure_ascii=False, indent=2)
        if args.keep_work:
            info["work_dir"] = work
            print(f"· рабочий каталог сохранён: {work}")
            work = None
        return info
    finally:
        if work and not args.keep_work:
            shutil.rmtree(work, ignore_errors=True)


def check_structure(path: str) -> dict:
    """Статическая проверка файла: PE-заголовок + конфигурационный блок + 7z-архив."""
    with open(path, "rb") as f:
        blob = f.read()
    i = blob.find(b";!@Install@!UTF-8!")
    j = blob.find(b";!@InstallEnd@!")
    off = j + len(b";!@InstallEnd@!")
    while blob[off:off + 1] in (b"\n", b"\r"):
        off += 1
    pe = int.from_bytes(blob[0x3c:0x40], "little")
    return {
        "mz": blob[:2] == b"MZ", "pe": blob[pe:pe + 4] == b"PE\0\0",
        "machine": hex(int.from_bytes(blob[pe + 4:pe + 6], "little")),
        "config_offset": i, "config_present": 0 < i < j,
        "launch": ("ExecuteFile" if 'ExecuteFile="cmd.exe"' in blob[i:j].decode("utf-8")
                   else "RunProgram" if "RunProgram=" in blob[i:j].decode("utf-8") else "нет"),
        "launch_ok": 'ExecuteFile="cmd.exe"' in blob[i:j].decode("utf-8")
                     and 'ExecuteParameters="/c isheika.cmd"' in blob[i:j].decode("utf-8"),
        "archive_offset": off, "archive_signature_ok": blob[off:off + 6] == b"7z\xbc\xaf\x27\x1c",
    }


def _spawn(cmd: list, cwd: str, env: dict, tag: str):
    """Запуск проверяемого процесса: pipe + фоновый сбор вывода, своя группа.

    Два ограничения окружения учтены вместе:
      * stdout в ФАЙЛ wine не принимает — python.exe падает на
        init_sys_streams (WinError 6), поэтому только pipe;
      * читать pipe после остановки нельзя блокирующе: wine порождает
        дочерние процессы (cmd → python.exe), переживающие terminate()
        родителя и держащие write-конец открытым. Вывод собирает поток,
        остановка идёт по всей группе процессов.
    """
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            text=True, errors="replace", start_new_session=True)
    buf: list = []

    def _pump():
        try:
            for line in proc.stdout:
                buf.append(line)
        except Exception:
            pass

    th = threading.Thread(target=_pump, name=f"verify-{tag}", daemon=True)
    th.start()
    return proc, buf, th


def _stop_read(proc, buf: list, th, limit: int = 1500) -> str:
    """Останов всей группы процессов и чтение накопленного вывода (без блокировок)."""
    import signal
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=15)
            break
        except Exception:
            continue
    th.join(timeout=5)
    try:
        proc.stdout.close()
    except Exception:
        pass
    return "".join(buf).replace("\r", "")[-limit:]


def ui_asset_names() -> list:
    """Ресурсы, объявленные в index.html (внешние сценарии и стили)."""
    import re
    web = os.path.join(ROOT, "isheika", "web")
    with open(os.path.join(web, "index.html"), encoding="utf-8") as f:
        html = f.read()
    markup = re.sub(r"(<script[^>]*>)[\s\S]*?</script>", r"\1</script>", html)
    names = ["index.html"]
    for ref in re.findall(r'(?:src|href)\s*=\s*"([^"]+)"', markup):
        ref = ref.split("?", 1)[0].split("#", 1)[0].strip()
        if (not ref or ref.startswith(("http", "data:", "//", "api/", "mailto:"))
                or any(ch in ref for ch in " '+<>") or ref in names):
            continue
        names.append(ref)
    return names


def verify_wine(payload: str, port: int) -> dict:
    """Проверка образа: Windows-интерпретатор запускает приложение и отвечает по API."""
    wine = shutil.which("wine64") or shutil.which("wine") or "/usr/lib/wine/wine64"
    if not os.path.exists(wine):
        return {"performed": False, "reason": "wine не найден — проверка образа пропущена"}
    env = dict(os.environ, WINEPREFIX=os.path.join(tempfile.gettempdir(), "wineprefix"),
               WINEDEBUG="-all", ISHEIKA_DATA=os.path.join(tempfile.gettempdir(), "isheika-exe-data"))
    pyexe = os.path.join(payload, "python", "python.exe")
    ver = subprocess.run([wine, pyexe, "-c", "import sys,sqlite3;print(sys.version.split()[0]);print(sqlite3.sqlite_version)"],
                         env=env, capture_output=True, text=True, errors="replace", timeout=300, stdin=subprocess.DEVNULL)
    proc, buf, th = _spawn([wine, pyexe, os.path.join(payload, "app", "run.py"),
                              "--host", "127.0.0.1", "--port", str(port), "--no-network"],
                             payload, env, "wine")
    result = {"performed": True, "python": ver.stdout.strip().replace("\r", "").split("\n"),
              "port": port, "api": None, "ui": None}
    try:
        import time
        import urllib.request
        base = f"http://127.0.0.1:{port}"
        for _ in range(90):
            try:
                with urllib.request.urlopen(base + "/api/v1/system", timeout=2) as r:
                    result["api"] = r.status
                break
            except Exception:
                if proc.poll() is not None:
                    break
                time.sleep(1)
        if result["api"]:
            body = json.dumps({"login": "admin", "password": "dev:admin"}).encode()
            req = urllib.request.Request(base + "/api/v1/auth/login", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                tok = json.loads(r.read())["token"]
            for path, key in (("/api/v1/researches", "items"), ("/api/v1/methodologies", "items"),
                              ("/api/v1/sources", "items"), ("/", None)):
                req = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + tok})
                with urllib.request.urlopen(req, timeout=15) as r:
                    data = r.read()
                result.setdefault("checks", []).append(
                    {"path": path, "status": r.status, "bytes": len(data)})
        # Ресурсы интерфейса: размер и тип обязаны совпадать с исходными файлами.
        # На Windows разбор пути давал подмену любого ресурса страницей index.html
        # («белый экран» в браузере) — эта проверка ловит такой дефект в сборке.
        result["assets"] = []
        for name in ui_asset_names():
            with urllib.request.urlopen(base + "/" + name, timeout=20) as r:
                data = r.read()
                ctype = r.headers.get("Content-Type", "")
                status = r.status
            src = os.path.join(ROOT, "isheika", "web", name)
            expected = os.path.getsize(src)
            is_html = name.endswith(".html")
            good = (status == 200 and len(data) == expected
                    and (ctype.startswith("text/html") if is_html else not ctype.startswith("text/html")))
            result["assets"].append({"asset": name, "http": status, "bytes": len(data),
                                     "expected_bytes": expected, "ctype": ctype, "ok": good})
    finally:
        result["log_tail"] = _stop_read(proc, buf, th)
    assets = result.get("assets", [])
    bad_assets = [a["asset"] for a in assets if not a["ok"]]
    result["ok"] = bool(result["api"] == 200 and all(c["status"] == 200 for c in result.get("checks", []))
                        and assets and not bad_assets)
    print(("✓" if result["ok"] else "!") + " проверка образа под wine: " + json.dumps(
        {k: result[k] for k in ("python", "api", "ok")}, ensure_ascii=False)
        + f"; ресурсов {len(assets) - len(bad_assets)}/{len(assets)}"
        + (("; ОТКАЗ: " + ", ".join(bad_assets)) if bad_assets else ""))
    return result


def verify_launch(payload: str, port: int) -> dict:
    """Проверка ЦЕПОЧКИ запуска образа: cmd.exe /c isheika.cmd → python.exe → сервер.

    Именно так файл запускается SFX-модулем (ExecuteFile="cmd.exe",
    ExecuteParameters="/c isheika.cmd"): рабочий каталог — каталог распаковки.
    """
    wine = shutil.which("wine64") or shutil.which("wine") or "/usr/lib/wine/wine64"
    if not os.path.exists(wine):
        return {"performed": False, "reason": "wine не найден"}
    data = os.path.join(tempfile.gettempdir(), "isheika-exe-launch-data")
    env = dict(os.environ, WINEPREFIX=os.path.join(tempfile.gettempdir(), "wineprefix"),
               WINEDEBUG="-all", ISHEIKA_DATA=data,
               LOCALAPPDATA=os.path.join(tempfile.gettempdir(), "isheika-exe-appdata"))
    proc, buf, th = _spawn([wine, "cmd", "/c", LAUNCH_SCRIPT, str(port)], payload, env, "launch")
    out = {"performed": True, "command": "cmd.exe /c " + LAUNCH_SCRIPT + " " + str(port), "port": port,
           "http": None, "ui": None, "checks": []}
    try:
        import time
        import urllib.request
        base = f"http://127.0.0.1:{port}"
        for _ in range(120):
            try:
                with urllib.request.urlopen(base + "/api/v1/system", timeout=2) as r:
                    out["http"] = r.status
                break
            except Exception:
                if proc.poll() is not None:
                    break
                time.sleep(1)
        if out["http"]:
            with urllib.request.urlopen(base + "/", timeout=15) as r:
                out["ui"] = r.status
                out["ui_bytes"] = len(r.read())
            body = json.dumps({"login": "admin", "password": "dev:admin"}).encode()
            req = urllib.request.Request(base + "/api/v1/auth/login", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                tok = json.loads(r.read())["token"]
            for path in ("/api/v1/researches", "/api/v1/methodologies", "/api/v1/document-graph"):
                rq = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + tok})
                with urllib.request.urlopen(rq, timeout=20) as r:
                    out["checks"].append({"path": path, "status": r.status})
    finally:
        out["log_tail"] = _stop_read(proc, buf, th, 1200)
    out["ok"] = bool(out["http"] == 200 and out["ui"] == 200
                     and all(c["status"] == 200 for c in out["checks"]))
    print(("✓" if out["ok"] else "!") + " цепочка запуска (cmd.exe /c isheika.cmd): "
          + json.dumps({k: out[k] for k in ("http", "ui", "ok")}, ensure_ascii=False))
    return out


def verify_tests(payload: str) -> dict:
    """Прогон приёмочных тестов ВНУТРИ образа на Windows-интерпретаторе."""
    wine = shutil.which("wine64") or shutil.which("wine") or "/usr/lib/wine/wine64"
    if not os.path.exists(wine):
        return {"performed": False, "reason": "wine не найден"}
    env = dict(os.environ, WINEPREFIX=os.path.join(tempfile.gettempdir(), "wineprefix"),
               WINEDEBUG="-all", ISHEIKA_DATA=os.path.join(tempfile.gettempdir(), "isheika-exe-testdata"))
    r = subprocess.run([wine, os.path.join(payload, "python", "python.exe"),
                        "-X", "utf8", "-m", "unittest", "discover", "-s", "app/tests", "-t", "app"],
                       cwd=payload, env=env, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=1800, errors="replace")
    text = (r.stderr or r.stdout or "").strip().replace("\r", "")
    lines = text.split("\n")
    tail = lines[-4:]
    # имена упавших испытаний — чтобы отказ был диагностируемым, а не «errors=1»
    failed = [l for l in lines if l.startswith(("FAIL:", "ERROR:"))][:10]
    out = {"performed": True, "returncode": r.returncode, "tail": tail, "ok": r.returncode == 0}
    if failed:
        out["failed_tests"] = failed
    print(("✓" if out["ok"] else "!") + " тесты внутри образа: " + " | ".join(tail))
    return out


def verify_linux(payload: str, port: int) -> dict:
    """Проверка образа на Linux без wine — воспроизводимая, а не вписанная вручную.

    Проверяется всё, что не зависит от ОС: побайтовое совпадение ресурсов образа
    с исходными, типы содержимого, отдача интерфейса, журнал загрузки и
    самопроверка, 404 на отсутствующий ресурс, приёмочные тесты из каталога `app`
    самого образа. Интерпретатор в образе — Windows-сборка того же CPython 3.11,
    поэтому код приложения исполняется системным python3.

    Цепочку `cmd.exe /c isheika.cmd` проверяет --verify-launch (нужен wine):
    здесь она не подменяется и в отчёте помечается как не выполненная.
    """
    import time
    import urllib.error
    import urllib.request

    data = tempfile.mkdtemp(prefix="isheika-linux-data-")
    env = dict(os.environ, ISHEIKA_DATA=data, PYTHONUTF8="1")
    proc, buf, th = _spawn([sys.executable, os.path.join("app", "run.py"),
                            "--host", "127.0.0.1", "--port", str(port), "--no-network"],
                           payload, env, "linux")
    base = f"http://127.0.0.1:{port}"
    out: dict = {"performed": True, "interpreter": sys.executable, "python": sys.version.split()[0],
                 "port": port, "http": None, "ui": None, "assets": [], "launch_chain": "не проверялась (нужен wine)"}

    def fetch(path: str):
        with urllib.request.urlopen(base + path, timeout=30) as r:
            return r.status, r.read(), r.headers.get("Content-Type", "")

    try:
        for _ in range(120):
            try:
                out["http"] = fetch("/api/v1/system")[0]
                break
            except Exception:
                if proc.poll() is not None:
                    break
                time.sleep(1)
        if out["http"] != 200:
            out["ok"] = False
            out["reason"] = "приложение из образа не ответило по HTTP"
            return out

        status, body, ctype = fetch("/")
        out["ui"] = status
        out["ui_bytes"] = len(body)
        out["ui_ctype"] = ctype

        # ресурсы: образ == исходники, отданное == образ, тип соответствует расширению
        for name in ui_asset_names():
            src = os.path.join(ROOT, "isheika", "web", name)
            packed = os.path.join(payload, "app", "isheika", "web", name)
            with open(src, "rb") as f:
                want = f.read()
            with open(packed, "rb") as f:
                got = f.read()
            code, served, ct = fetch("/" + name)
            expect_ct = ("text/html" if name.endswith(".html") else
                         "text/css" if name.endswith(".css") else
                         "application/javascript" if name.endswith(".js") else "")
            out["assets"].append({
                "asset": name, "bytes": len(served), "ctype": ct,
                "identical_to_source": want == got == served,
                "ctype_ok": (not expect_ct) or ct.startswith(expect_ct),
                "status": code,
            })
        out["assets_ok"] = sum(1 for a in out["assets"]
                               if a["identical_to_source"] and a["ctype_ok"] and a["status"] == 200)
        out["assets_total"] = len(out["assets"])

        code, body, _ = fetch("/api/v1/boot-log")
        boot = json.loads(body.decode("utf-8"))
        out["boot_log_ok"] = bool(boot.get("ok"))
        out["boot_checks"] = len(boot.get("checks") or [])
        out["app_version"] = boot.get("app_version")
        try:
            fetch("/no-such-asset.js")
            out["missing_asset_status"] = 200
        except urllib.error.HTTPError as e:
            out["missing_asset_status"] = e.code
    finally:
        out["log_tail"] = _stop_read(proc, buf, th, 1200)

    # приёмочные тесты из каталога app самого образа (изолированный каталог данных)
    tdata = tempfile.mkdtemp(prefix="isheika-linux-tests-")
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "unittest", "discover",
                        "-s", os.path.join("app", "tests"), "-t", "app"],
                       cwd=payload, env=dict(env, ISHEIKA_DATA=tdata),
                       capture_output=True, text=True, stdin=subprocess.DEVNULL,
                       timeout=1800, errors="replace")
    text = (r.stderr or r.stdout or "").strip().replace("\r", "")
    lines = text.split("\n")
    out["unit_tests"] = {"returncode": r.returncode, "tail": lines[-4:], "ok": r.returncode == 0}
    failed = [l for l in lines if l.startswith(("FAIL:", "ERROR:"))][:10]
    if failed:
        out["unit_tests"]["failed_tests"] = failed
    shutil.rmtree(data, ignore_errors=True)
    shutil.rmtree(tdata, ignore_errors=True)

    out["ok"] = bool(out["http"] == 200 and out["ui"] == 200
                     and out["assets_ok"] == out["assets_total"]
                     and out.get("boot_log_ok") and out.get("missing_asset_status") == 404
                     and out["unit_tests"]["ok"])
    print(("✓" if out["ok"] else "!") + " проверка образа на Linux: "
          + json.dumps({"http": out["http"], "ui": out["ui"],
                        "assets": f"{out['assets_ok']}/{out['assets_total']}",
                        "boot_log": out.get("boot_log_ok"),
                        "tests": " | ".join(out["unit_tests"]["tail"][-2:])}, ensure_ascii=False))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Сборка единого .exe «ИЩЕЙКА НТР AI»")
    ap.add_argument("--out", default=os.path.join(ROOT, "release", APP_NAME + ".exe"))
    ap.add_argument("--cache", default=os.path.join(ROOT, ".cache", "build"))
    ap.add_argument("--sfx", default=None)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--app-version", default=None)
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--verify-wine", action="store_true", help="запустить образ под wine64 и проверить API")
    ap.add_argument("--verify-tests", action="store_true", help="прогнать приёмочные тесты внутри образа")
    ap.add_argument("--verify-launch", action="store_true",
                    help="проверить цепочку запуска cmd.exe /c isheika.cmd внутри образа")
    ap.add_argument("--verify-linux", action="store_true",
                    help="проверить образ системным Python на Linux (без wine): ресурсы, "
                         "типы, журнал загрузки, 404, приёмочные тесты из образа")
    args = ap.parse_args()
    build(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
