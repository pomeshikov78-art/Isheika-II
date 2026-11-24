#!/usr/bin/env python3
"""Сборка единого исполняемого файла «ИЩЕЙКА НТР AI» для Windows.

    python3 tools/build_exe.py                     # release/ISHEIKA-NTR-AI.exe
    python3 tools/build_exe.py --verify-wine       # + проверка запуска образа под wine64
    python3 tools/build_exe.py --no-download       # сборка только из кеша (без сети)

Результат — один файл `.exe`, который на машине пользователя:
  1. распаковывает во временный каталог встроенный CPython 3.11 (x64) и приложение;
  2. запускает `start.cmd` → сервер на 127.0.0.1:8000 и открывает браузер;
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

SFX_CONFIG = """;!@Install@!UTF-8!
Title="ИЩЕЙКА НТР AI {version}"
BeginPrompt="Запустить «ИЩЕЙКА НТР AI {version}»?\\n\\nПриложение будет распаковано во временный каталог, данные сохраняются в %LOCALAPPDATA%\\IsheikaNTR-AI."
Progress="yes"
RunProgram="cmd /c start.cmd"
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
set "ISHEIKA_PORT=8000"
if not "%~1"=="" set "ISHEIKA_PORT=%~1"

echo ============================================================
echo   ИЩЕЙКА НТР AI — аналитика научно-технологического развития
echo   Данные:    %ISHEIKA_DATA%
echo   Интерфейс: http://127.0.0.1:%ISHEIKA_PORT%/
echo   Вход:      admin / dev:admin   (роли: lead, analyst, expert, observer, auditor)
echo   Остановка: Ctrl+C или закройте это окно
echo ============================================================
echo.

start "" /min "%ROOT%open-browser.cmd" %ISHEIKA_PORT%
"%ROOT%python\python.exe" "%ROOT%app\run.py" --host 127.0.0.1 --port %ISHEIKA_PORT% %2 %3 %4 %5
if errorlevel 1 (
  echo.
  echo Сервер завершился с ошибкой. Если порт %ISHEIKA_PORT% занят, запустите:
  echo     start.cmd 8080
  echo.
  pause
)
endlocal
"""

OPEN_BROWSER_CMD = r"""@echo off
rem Ожидание готовности сервера, затем открытие интерфейса в браузере по умолчанию.
setlocal
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"
timeout /t 4 /nobreak >nul
start "" "http://127.0.0.1:%PORT%/"
endlocal
"""

READ_ME = """ИЩЕЙКА НТР AI {version} — единый файл запуска (Windows 10/11 x64)
=====================================================================

ЗАПУСК
  Двойной щелчок по ISHEIKA-NTR-AI.exe → «Да» в запросе запуска.
  Откроется окно сервера и браузер на http://127.0.0.1:8000/.
  Другой порт: ISHEIKA-NTR-AI.exe не принимает аргументы; после распаковки
  можно запустить start.cmd 8080 из временного каталога, либо собрать
  файл с другим портом (tools/build_exe.py --port).

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
  в start.cmd (имитационный коннектор, документы помечаются «имитация»).

САМОПРОВЕРКА (необязательно)
  В каталоге распаковки:
    python\\python.exe -m unittest discover -s app\\tests -t app
    python\\python.exe app\\tools\\api_check.py

СОСТАВ ОБРАЗА
  python\\  — встраиваемый CPython {pyver} (x64), только стандартная библиотека
  app\\     — ядро, API, веб-интерфейс, реестры источников, тесты, документация
  start.cmd, open-browser.cmd — запуск сервера и открытие браузера

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
    for name in ("7z", "7za", "7zr"):
        p = shutil.which(name)
        if p:
            return p
    raise SystemExit("Не найден 7-Zip (7z/7za/7zr) в PATH — он нужен для упаковки образа.")


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
                if os.path.splitext(name)[1] in EXCLUDE_EXT or name.endswith(".sfx"):
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
        return "1.2.0"


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
        start = START_CMD.replace("set \"ISHEIKA_PORT=8000\"", f'set "ISHEIKA_PORT={args.port}"')
        for name, text in (("start.cmd", start), ("open-browser.cmd", OPEN_BROWSER_CMD),
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
        info["structure"] = check_structure(out)
        print(f"✓ {out}  {info['size_bytes'] / 1048576:.1f} МБ  sha256={info['sha256'][:16]}…")

        if args.verify_wine:
            info["wine_check"] = verify_wine(payload, args.port + 11)
        if args.verify_tests:
            info["wine_tests"] = verify_tests(payload)
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
        "run_program": 'RunProgram="cmd /c start.cmd"' in blob[i:j].decode("utf-8"),
        "archive_offset": off, "archive_signature_ok": blob[off:off + 6] == b"7z\xbc\xaf\x27\x1c",
    }


def verify_wine(payload: str, port: int) -> dict:
    """Проверка образа: Windows-интерпретатор запускает приложение и отвечает по API."""
    wine = shutil.which("wine64") or shutil.which("wine") or "/usr/lib/wine/wine64"
    if not os.path.exists(wine):
        return {"performed": False, "reason": "wine не найден — проверка образа пропущена"}
    env = dict(os.environ, WINEPREFIX=os.path.join(tempfile.gettempdir(), "wineprefix"),
               WINEDEBUG="-all", ISHEIKA_DATA=os.path.join(tempfile.gettempdir(), "isheika-exe-data"))
    pyexe = os.path.join(payload, "python", "python.exe")
    ver = subprocess.run([wine, pyexe, "-c", "import sys,sqlite3;print(sys.version.split()[0]);print(sqlite3.sqlite_version)"],
                         env=env, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
    proc = subprocess.Popen([wine, pyexe, os.path.join(payload, "app", "run.py"),
                             "--host", "127.0.0.1", "--port", str(port), "--no-network"],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, text=True)
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
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except Exception:
            proc.kill()
    try:
        result["log_tail"] = (proc.stdout.read() or "")[-1500:] if proc.stdout else ""
    except Exception:
        result["log_tail"] = ""
    result["ok"] = bool(result["api"] == 200 and all(c["status"] == 200 for c in result.get("checks", [])))
    print(("✓" if result["ok"] else "!") + " проверка образа под wine: " + json.dumps(
        {k: result[k] for k in ("python", "api", "ok")}, ensure_ascii=False))
    return result


def verify_tests(payload: str) -> dict:
    """Прогон приёмочных тестов ВНУТРИ образа на Windows-интерпретаторе."""
    wine = shutil.which("wine64") or shutil.which("wine") or "/usr/lib/wine/wine64"
    if not os.path.exists(wine):
        return {"performed": False, "reason": "wine не найден"}
    env = dict(os.environ, WINEPREFIX=os.path.join(tempfile.gettempdir(), "wineprefix"),
               WINEDEBUG="-all", ISHEIKA_DATA=os.path.join(tempfile.gettempdir(), "isheika-exe-testdata"))
    r = subprocess.run([wine, os.path.join(payload, "python", "python.exe"),
                        "-m", "unittest", "discover", "-s", "app/tests", "-t", "app"],
                       cwd=payload, env=env, capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=1800)
    tail = (r.stderr or r.stdout or "").strip().replace("\r", "").split("\n")[-4:]
    out = {"performed": True, "returncode": r.returncode, "tail": tail, "ok": r.returncode == 0}
    print(("✓" if out["ok"] else "!") + " тесты внутри образа: " + " | ".join(tail))
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
    args = ap.parse_args()
    build(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
