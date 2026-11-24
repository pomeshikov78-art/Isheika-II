"""Испытания загрузки интерфейса и диагностики (замечание: «белый экран»).

STAT-01…05 — разбор путей к статическим ресурсам НЕ зависит от ОС (на Windows
os.path.normpath("/app.js") даёт "\\app.js", из-за чего каждый ресурс
подменялся index.html и браузер показывал пустой экран), типы содержимого,
отказ 404 вместо подмены HTML.
BOOT-01…07 — журнал загрузки: шаги, самопроверка, обнаружение отсутствующего
ресурса, публичный доступ, выгрузка, история, сохранение в каталог данных.
"""
from __future__ import annotations

import json
import os
import ntpath
import posixpath

from isheika import boot
from isheika.contracts import CoreError
from isheika.api import server as SRV
from isheika.config import WEB_DIR
from isheika.storage import db
from tests.base import BaseCase


def web_src(name: str) -> str:
    """Текст ресурса интерфейса (файл закрывается сразу — без ResourceWarning)."""
    with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
        return f.read()


def js_code(name: str) -> str:
    """Текст ресурса без комментариев: закомментированный код не должен
    считаться реализованным (иначе тест проходит на выключенной строке)."""
    import re
    src = web_src(name)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


class StaticTests(BaseCase):
    def test_STAT_01_path_resolution_is_os_independent(self):
        """STAT-01: URL разрешается одинаково при POSIX и NT правилах os.path."""
        cases = {"/": "index.html", "/app.js": "app.js", "\\": "index.html",
                 "\\app.js": "app.js", "/web/../app.js": "app.js",
                 "/screens_ops.js": "screens_ops.js", "/a/b/../c.css": "a/c.css"}
        for url, expect in cases.items():
            self.assertEqual(SRV.static_target(url), expect, url)
        # обе реализации normpath дают разный результат — разбор не должен от них зависеть
        self.assertNotEqual(ntpath.normpath("/app.js"), posixpath.normpath("/app.js"))
        self.assertEqual(SRV.static_target("/app.js"), SRV.static_target("\\app.js"))

    def test_STAT_02_traversal_and_absolute_paths(self):
        """STAT-02: выход за каталог интерфейса и абсолютные пути Windows отсекаются."""
        self.assertIsNone(SRV.static_target("C:\\Windows\\win.ini"))
        for url in ("/../secret.txt", "/..%2fsecret.txt", "/%2e%2e/secret.txt"):
            rel = SRV.static_target(url)
            self.assertFalse(rel.startswith(".."), url)
            full = os.path.realpath(os.path.join(WEB_DIR, *rel.split("/")))
            self.assertTrue(full.startswith(os.path.realpath(WEB_DIR)), full)

    def test_STAT_03_content_types_are_explicit(self):
        """STAT-03: типы задаются явно, а не берутся из реестра ОС."""
        self.assertTrue(SRV.static_ctype("/x/app.js").startswith("application/javascript"))
        self.assertTrue(SRV.static_ctype("/x/styles.css").startswith("text/css"))
        self.assertTrue(SRV.static_ctype("/x/index.html").startswith("text/html"))
        self.assertTrue(SRV.static_ctype("/x/a.json").startswith("application/json"))

    def test_STAT_04_missing_asset_is_404_not_html(self):
        """STAT-04: отсутствующий .js/.css — 404, а не подмена страницей (причина «белого экрана»)."""
        import inspect
        src = inspect.getsource(SRV.Handler._static)
        self.assertIn("Ресурс интерфейса не найден", src)
        self.assertIn("static_target", src)
        self.assertNotIn('lstrip("/")', src)      # прежний разбор, ломанный на Windows

    def test_STAT_05_all_declared_assets_exist(self):
        """STAT-05: каждый ресурс из index.html на месте и непустой."""
        assets = boot.ui_assets()
        names = {a["asset"] for a in assets}
        for required in ("index.html", "styles.css", "app.js", "charts.js", "screens_core.js",
                         "screens_registry.js", "screens_v11.js", "screens_ops.js", "screens_journal.js"):
            self.assertIn(required, names)
        for a in assets:
            self.assertTrue(a["ok"], a)
            self.assertGreater(a["bytes"], 0)


    def test_STAT_07_every_module_publishes_its_global(self):
        """STAT-07: каждый сценарий публикует свой объект в window.

        `const Charts = ...` создаёт лексическую привязку глобальной области, а не
        свойство window. Соседние сценарии объект видят, диагностика — нет:
        в журнале загрузки появлялся ложный «FAIL Объект Charts — не определён»,
        и экран журнала не скрывался поверх работающего интерфейса.
        """
        import re
        index = js_code("index.html")
        scripts = re.findall(r'<script src="([^"]+)"></script>', index)
        self.assertTrue(scripts, "в разметке нет подключаемых сценариев")
        expected = {"charts.js": "Charts", "app.js": "App"}
        for name in scripts:
            obj = expected.get(name, "Screens")     # screens_*.js расширяют общий реестр экранов
            src = js_code(name)
            self.assertTrue(re.search(r"window\." + obj + r"\s*=", src),
                            f"{name} не публикует window.{obj} — диагностика загрузки увидит «не определён»")

    def test_STAT_06_resource_exhaustion_answers_503(self):
        """STAT-06: нехватка потоков ОС даёт 503 с причиной, а не обрыв соединения."""
        import socket
        from http.server import ThreadingHTTPServer
        from unittest import mock

        srv = SRV.Server.__new__(SRV.Server)
        a, b = socket.socketpair()
        try:
            with mock.patch.object(ThreadingHTTPServer, "process_request",
                                   side_effect=RuntimeError("can't start new thread")):
                srv.process_request(a, ("127.0.0.1", 12345))
            b.settimeout(5)
            data = b.recv(8192)
            self.assertIn(b"503", data)
            self.assertIn(b"E_STATE", data)
        finally:
            b.close()
            try:
                a.close()
            except Exception:
                pass


class BootTests(BaseCase):
    def test_BOOT_01_steps_recorded_with_duration(self):
        """BOOT-01: шаг фиксирует результат, подробности и длительность."""
        before = len(boot.snapshot(with_checks=False)["steps"])
        with boot.step("Тестовый шаг") as info:
            info["detail"] = "проверка журнала"
        snap = boot.snapshot(with_checks=False)
        self.assertEqual(len(snap["steps"]), before + 1)
        last = snap["steps"][-1]
        self.assertEqual(last["step"], "Тестовый шаг")
        self.assertEqual(last["status"], "ok")
        self.assertGreaterEqual(last["duration_ms"], 0)
        self.assertTrue(db.one("SELECT * FROM ops_boot_log WHERE step='Тестовый шаг'"))

    def test_BOOT_02_failed_step_is_recorded_and_raised(self):
        """BOOT-02: отказ шага попадает в журнал и не проглатывается."""
        with self.assertRaises(RuntimeError):
            with boot.step("Тестовый отказ"):
                raise RuntimeError("проверка отказа")
        last = boot.snapshot(with_checks=False)["steps"][-1]
        self.assertEqual(last["status"], "fail")
        self.assertIn("RuntimeError", last["detail"])
        self.assertFalse(boot.snapshot(with_checks=False)["ok"])

    def test_BOOT_03_self_check_covers_subsystems(self):
        """BOOT-03: самопроверка охватывает данные, БД, реестры, ресурсы, маршруты, подсистемы."""
        checks = {c["check"]: c for c in boot.self_check()}
        for name in ("Каталог данных доступен на запись", "База данных целостна", "Реестры загружены",
                     "Ресурсы интерфейса на месте", "Маршруты API зарегистрированы", "Подсистемы отвечают"):
            self.assertIn(name, checks)
            self.assertTrue(checks[name]["ok"], checks[name])
        self.assertIn("quick_check=ok", checks["База данных целостна"]["detail"])

    def test_BOOT_04_missing_asset_detected(self):
        """BOOT-04: отсутствие ресурса интерфейса обнаруживается самопроверкой."""
        victim = os.path.join(WEB_DIR, "screens_ops.js")
        spare = victim + ".boot-test-bak"
        os.replace(victim, spare)
        try:
            assets = {a["asset"]: a for a in boot.ui_assets()}
            self.assertFalse(assets["screens_ops.js"]["ok"])
            checks = {c["check"]: c for c in boot.self_check()}
            self.assertFalse(checks["Ресурсы интерфейса на месте"]["ok"])
            self.assertIn("screens_ops.js", checks["Ресурсы интерфейса на месте"]["detail"])
        finally:
            os.replace(spare, victim)
        self.assertTrue({a["asset"]: a for a in boot.ui_assets()}["screens_ops.js"]["ok"])

    def test_BOOT_05_public_and_exportable(self):
        """BOOT-05: журнал доступен без токена и выгружается в txt/json."""
        self.assertIn("/api/v1/boot-log", SRV.PUBLIC_PATHS)
        raw = json.dumps([list(map(str, r[:2])) for r in SRV.ROUTES])
        self.assertIn("/api/v1/boot-log", raw)
        text = boot.export("txt")
        self.assertIn("ШАГИ ЗАПУСКА", text)
        self.assertIn("САМОПРОВЕРКА", text)
        self.assertIn("РЕСУРСЫ ИНТЕРФЕЙСА", text)
        data = json.loads(boot.export("json"))
        self.assertTrue(data["boot_id"] and data["steps"] and data["checks"])
        self.assertNotIn("password", boot.export("txt").lower())

    def test_BOOT_06_files_written_to_data_dir(self):
        """BOOT-06: журнал сохраняется файлами — доступен, даже если браузер не открылся."""
        files = boot.write_files()
        self.assertTrue(os.path.isfile(files["txt"]))
        self.assertTrue(os.path.isfile(files["json"]))
        with open(files["txt"], encoding="utf-8") as f:
            self.assertIn("журнал загрузки", f.read())

    def test_BOOT_07_history_keeps_previous_boots(self):
        """BOOT-07: история загрузок хранится в БД и отдаётся отдельным маршрутом."""
        boot.record("Тестовая история", "ok", "проверка")
        rows = db.query("SELECT * FROM ops_boot_log WHERE boot_id=?", (boot.BOOT_ID,))
        self.assertTrue(rows)
        raw = json.dumps([list(map(str, r[:2])) for r in SRV.ROUTES])
        self.assertIn("/api/v1/boot-log/history", raw)

    def test_BOOT_08_diagnostics_tolerate_lexical_globals(self):
        """BOOT-08: диагностика видит и window.X, и лексический global (ложный отказ)."""
        index = js_code("index.html")
        self.assertIn("B.mod = function", index)
        for obj in ("Charts", "Screens", "App"):
            self.assertIn("B.mod('" + obj + "'", index)
            self.assertIn("typeof " + obj + " !== 'undefined'", index)
        # прежняя проверка только по свойству window — источник ложного отказа
        self.assertNotIn("window.Charts ? 'ok'", index)

    def test_BOOT_09_failed_diagnostics_do_not_lock_the_ui(self):
        """BOOT-09: отказ диагностики закрывается — работоспособный интерфейс доступен."""
        index = js_code("index.html")
        self.assertIn('id="boot-continue"', index)
        self.assertIn("B.dismiss = function", index)
        self.assertIn("addEventListener('click', B.dismiss)", index)
        self.assertIn("if (B.dismissed)", index)          # повторный отказ не перехватывает экран
        self.assertIn("B.ready = function", index)        # кнопка показывается только когда App готов

    def test_BOOT_10_expected_scripts_match_markup(self):
        """BOOT-10: список ожидаемых сценариев в диагностике совпадает с разметкой."""
        import re
        index = js_code("index.html")
        declared = re.findall(r'<script src="([^"]+)"></script>', index)
        expected = re.search(r"var expect = \[([^\]]+)\]", index)
        self.assertIsNotNone(expected)
        listed = re.findall(r"'([^']+)'", expected.group(1))
        self.assertEqual(sorted(declared), sorted(listed))

    def test_BOOT_11_history_requires_logs_read(self):
        """BOOT-11: история загрузок требует logs.read; текущий журнал остаётся публичным."""
        import types
        req = types.SimpleNamespace(session={"role": "observer", "login": "observer"}, qs={})
        with self.assertRaises(CoreError) as ctx:
            SRV.r_boot_history(req, None, None)
        self.assertEqual(ctx.exception.error.code, "E_FORBIDDEN")
        for role in ("auditor", "analyst", "admin"):
            req = types.SimpleNamespace(session={"role": role, "login": role}, qs={})
            self.assertIn("items", SRV.r_boot_history(req, None, None))
        self.assertIn("/api/v1/boot-log", SRV.PUBLIC_PATHS)
        self.assertNotIn("/api/v1/boot-log/history", SRV.PUBLIC_PATHS)
