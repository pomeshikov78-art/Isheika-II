"""Испытания упаковки единого файла запуска (задача 2).

PKG-01…PKG-05 защищают от повторения дефекта, из-за которого SFX показывал
«Не удается найти указанный файл»: модуль 7zSD.sfx выполняет RunProgram как
CreateProcess(NULL, dirPrefix + RunProgram) с dirPrefix = ".\\", поэтому команда
с аргументами ("cmd /c start.cmd") превращалась в путь ".\\cmd".
Запуск обязан идти через ExecuteFile (ShellExecuteEx, без префикса).
"""
from __future__ import annotations

import importlib.util
import os
import socket
import sys

from isheika.api import server as SRV
from isheika.contracts import CoreError
from tests.base import BaseCase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _build_module():
    spec = importlib.util.spec_from_file_location("build_exe", os.path.join(ROOT, "tools", "build_exe.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_exe"] = mod
    spec.loader.exec_module(mod)
    return mod


BX = _build_module()


class PKGTests(BaseCase):
    def test_PKG_01_sfx_launch_uses_shellexecute(self):
        """PKG-01: запуск через ExecuteFile; RunProgram с аргументами запрещён."""
        cfg = BX.SFX_CONFIG.format(version="1.2.0")
        self.assertIn(';!@Install@!UTF-8!', cfg)
        self.assertIn(';!@InstallEnd@!', cfg)
        self.assertIn('ExecuteFile="cmd.exe"', cfg)
        self.assertIn('ExecuteParameters="/c isheika.cmd"', cfg)
        self.assertNotIn("RunProgram", cfg)          # префикс ".\" ломает команду с аргументами
        self.assertNotIn("Directory=", cfg)

    def test_PKG_02_launch_cmd_contract(self):
        """PKG-02: сценарий запуска ведёт к python.exe, данные вне temp, порт проверяется."""
        cmd = BX.START_CMD
        self.assertIn("%ROOT%python\\python.exe", cmd)
        self.assertIn("%ROOT%app\\run.py", cmd)
        self.assertIn("--open-browser", cmd)
        self.assertIn("--port-auto", cmd)
        self.assertIn('set "ISHEIKA_DATA=%LOCALAPPDATA%\\IsheikaNTR-AI"', cmd)
        self.assertIn('for /f "delims=0123456789"', cmd)   # числовая проверка порта без findstr
        # ветвление плоское: вложенные блоки cmd в wine не выполняет (порт терялся)
        self.assertNotIn("if defined ARG (", cmd)
        self.assertNotIn("if errorlevel 1 (", cmd)
        self.assertIn(":launch", cmd)
        self.assertIn("goto :failed", cmd)
        self.assertIn("__PORT__", cmd)                     # подставляется сборщиком
        self.assertNotIn("open-browser.cmd", cmd)
        # имя сценария не должно совпадать с внутренней командой cmd.exe:
        # "start.cmd" разбирается как START + ".cmd" → File not found
        internal = {"start", "run", "call", "cmd", "echo", "set", "if", "for", "goto",
                    "type", "copy", "del", "dir", "exit", "pause", "rem", "shift", "title"}
        stem = os.path.splitext(BX.LAUNCH_SCRIPT)[0].lower()
        self.assertNotIn(stem, internal)
        self.assertIn('ExecuteParameters="/c ' + BX.LAUNCH_SCRIPT + '"',
                      BX.SFX_CONFIG.format(version="1.2.0"))

    def test_PKG_03_structure_parser(self):
        """PKG-03: разбор файла — PE + конфигурация + сигнатура 7z."""
        import tempfile
        sfx = os.path.join(ROOT, "tools", "vendor", "7zSD.sfx")
        with open(sfx, "rb") as f:
            blob = f.read()
        cfg = BX.SFX_CONFIG.format(version="9.9.9").encode("utf-8")
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as f:
            f.write(blob + cfg + b"7z\xbc\xaf\x27\x1c" + b"\x00" * 64)
            path = f.name
        try:
            st = BX.check_structure(path)
            self.assertTrue(st["mz"] and st["pe"])
            self.assertTrue(st["config_present"])
            self.assertEqual(st["launch"], "ExecuteFile")
            self.assertTrue(st["launch_ok"])
            self.assertTrue(st["archive_signature_ok"])
            self.assertEqual(st["config_offset"], len(blob))
        finally:
            os.unlink(path)

    def test_PKG_04_cli_flags_present(self):
        """PKG-04: точка входа поддерживает флаги, которые использует isheika.cmd."""
        with open(os.path.join(ROOT, "run.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("--open-browser", src)
        self.assertIn("--port-auto", src)
        import inspect
        sig = inspect.signature(SRV.main)
        self.assertIn("open_browser", sig.parameters)
        self.assertIn("port_auto", sig.parameters)

    def test_PKG_05_port_fallback(self):
        """PKG-05: занятый порт → следующий свободный; без port_auto — понятная ошибка."""
        busy = socket.socket()
        busy.bind(("127.0.0.1", 0))
        port = busy.getsockname()[1]
        busy.listen(1)
        try:
            with self.assertRaises(CoreError):
                SRV.serve_auto(host="127.0.0.1", port=port, port_auto=False)
            httpd = SRV.serve_auto(host="127.0.0.1", port=port, port_auto=True, attempts=5)
            try:
                self.assertNotEqual(httpd.server_address[1], port)
                self.assertGreater(httpd.server_address[1], port)
            finally:
                httpd.server_close()
        finally:
            busy.close()
