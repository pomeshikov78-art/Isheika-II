"""Испытания отрисовки экранов при параллельных вызовах (редакция 1.4.2).

Основание — журнал действий с машины пользователя (ред. 1.4.0/1.4.1):
`render.dashboard` и `render.monitor` → «TypeError: Cannot set properties of null
(setting 'innerHTML')». Причина: afterLogin менял location.hash (render по
hashchange) и сам вызывал render — две отрисовки шли параллельно, вторая подменяла
разметку, первая писала в отсоединённый узел. Плюс слушатель SSE-событий в UI-23
снимался только при смене маршрута и переживал перерисовку.

RND-01…05 — требования к оболочке и экранам.
"""
from __future__ import annotations

import os
import re

from isheika.config import WEB_DIR
from tests.base import BaseCase


def web_src(name: str) -> str:
    with open(os.path.join(WEB_DIR, name), encoding="utf-8") as f:
        return f.read()


class RenderRaceTests(BaseCase):
    def setUp(self) -> None:
        super().setUp()
        self.app = web_src("app.js")

    def test_RND_01_renders_are_serialised(self):
        """RND-01: отрисовки идут по очереди, повторяющиеся запросы объединяются."""
        self.assertTrue(re.search(r"const RENDER = \{seq: 0, chain: Promise\.resolve\(\)", self.app))
        self.assertTrue(re.search(r"function render\(\) \{\s*const my = \+\+RENDER\.seq", self.app))
        self.assertTrue(re.search(r"my === RENDER\.seq \? drawScreen\(\) : null", self.app))
        self.assertIn("async function drawScreen()", self.app)

    def test_RND_02_stale_render_does_not_touch_dom(self):
        """RND-02: устаревшая отрисовка не пишет в DOM и не считается дефектом."""
        self.assertTrue(re.search(r"const stale = host => !host \|\| host\.isConnected === false", self.app))
        self.assertGreaterEqual(len(re.findall(r"if \(stale\(body\)\) return;", self.app)), 2)

    def test_RND_03_no_unguarded_innerhtml_writes(self):
        """RND-03: ни один экран не пишет innerHTML в узел, найденный без проверки."""
        bad = []
        for name in sorted(os.listdir(WEB_DIR)):
            if not name.endswith(".js"):
                continue
            src = web_src(name)
            for m in re.finditer(r"document\.getElementById\([^)]*\)\.innerHTML", src):
                bad.append(f"{name}: {m.group(0)}")
        self.assertFalse(bad, "небезопасная запись в узел: " + "; ".join(bad))
        self.assertTrue(re.search(r"function setHTML\(id, html\)", self.app))
        self.assertTrue(re.search(r"if \(!el\) return false;", self.app))

    def test_RND_04_screen_listeners_are_removed_on_rerender(self):
        """RND-04: слушатели событий экрана снимаются при любой перерисовке."""
        self.assertTrue(re.search(r"function onCleanup\(fn\)", self.app))
        self.assertTrue(re.search(r"function runCleanups\(\)", self.app))
        self.assertTrue(re.search(r"runCleanups\(\);", self.app.split("async function drawScreen()")[1][:400]))
        monitor = web_src("screens_registry.js")
        self.assertTrue(re.search(r"App\.onCleanup\(\(\) => window\.removeEventListener\('isheika:event', onEv\)\)", monitor))
        self.assertTrue(re.search(r"App\.setHTML\('m-events'", monitor),
                        "лента мониторинга должна искаться в момент записи")

    def test_RND_05_helpers_published(self):
        """RND-05: вспомогательные функции опубликованы для экранов."""
        tail = self.app.split("return {")[-1]
        for name in ("setHTML", "stale", "onCleanup"):
            self.assertIn(name, tail)
