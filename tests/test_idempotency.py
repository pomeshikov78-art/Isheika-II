"""Испытания идемпотентности изменяющих запросов (ИД-22, ред. 1.5.1).

Основание — журнал с машины пользователя: `POST /api/v1/researches` завершался
E_NETWORK, клиент повторяет такой запрос трижды (он помечен ключом как безопасный),
а сервер заголовок `Idempotency-Key` игнорировал. Контрольный опыт на живом сервере
до правки: два POST с одним ключом → два разных исследования.

IDM-01 — повтор с тем же ключом и телом возвращает тот же объект (один в базе).
IDM-02 — ключ, использованный с другим телом, отклоняется.
IDM-03 — без ключа создаются два разных объекта (поведение не сломано).
IDM-04 — разные ключи на один и тот же запрос дают разные объекты.
IDM-05 — просроченный ключ не возвращает старый ответ.
IDM-06 — ключ действует в пределах актора и маршрута.
IDM-07 — сквозная проверка по HTTP: заголовок Idempotency-Key respected сервером.
"""
from __future__ import annotations

from isheika.api import idempotency as IDEM, service as S
from isheika.storage import db
from tests.base import BaseCase


class IdempotencyTests(BaseCase):
    def _body(self, query="тропосферная связь за горизонтом"):
        return {"query": query, "title": "Испытание идемпотентности", "countries": ["RU", "US"]}

    def test_IDM_01_replay_returns_same_object(self):
        body = self._body()
        route = "POST /api/v1/researches"
        before = db.count("core_researches")
        first = S.create_research(body, actor="tester")
        IDEM.store("k-1", actor="tester", route=route, body=body, response=first)
        again = IDEM.lookup("k-1", actor="tester", route=route, body=body)
        self.assertIsNotNone(again, "повтор не нашёл сохранённый ответ")
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(db.count("core_researches"), before + 1,
                         "повтор не должен создавать второй объект")

    def test_IDM_02_key_with_other_body_is_rejected(self):
        body = self._body()
        IDEM.store("k-2", actor="tester", route="POST /api/v1/researches", body=body,
                   response={"id": "res-x"})
        with self.assertRaises(Exception) as ctx:
            IDEM.lookup("k-2", actor="tester", route="POST /api/v1/researches",
                        body=self._body("совсем другой запрос"))
        self.assertEqual(getattr(ctx.exception, "error", None).code, "E_VALIDATION")

    def test_IDM_03_without_key_duplicates_are_allowed(self):
        a = S.create_research(self._body(), actor="tester")
        b = S.create_research(self._body(), actor="tester")
        self.assertNotEqual(a["id"], b["id"])
        self.assertIsNone(IDEM.lookup("", actor="tester", route="POST /api/v1/researches", body={}))

    def test_IDM_04_different_keys_are_different_actions(self):
        body = self._body()
        route = "POST /api/v1/researches"
        a = S.create_research(body, actor="tester")
        IDEM.store("act-1", actor="tester", route=route, body=body, response=a)
        b = S.create_research(body, actor="tester")
        IDEM.store("act-2", actor="tester", route=route, body=body, response=b)
        self.assertNotEqual(a["id"], b["id"], "два действия с одним запросом — два исследования")
        self.assertEqual(IDEM.lookup("act-1", actor="tester", route=route, body=body)["id"], a["id"])
        self.assertEqual(IDEM.lookup("act-2", actor="tester", route=route, body=body)["id"], b["id"])

    def test_IDM_05_expired_key_is_forgotten(self):
        body = self._body()
        route = "POST /api/v1/researches"
        IDEM.store("k-old", actor="tester", route=route, body=body, response={"id": "res-old"})
        db.execute("UPDATE ops_idempotency SET created_at=? WHERE key=?", ("2000-01-01T00:00:00Z", "k-old"))
        self.assertIsNone(IDEM.lookup("k-old", actor="tester", route=route, body=body))
        self.assertEqual(IDEM.prune(), 0)   # просроченная запись уже удалена при обращении

    def test_IDM_06_key_is_scoped_to_actor_and_route(self):
        body = self._body()
        IDEM.store("k-3", actor="tester", route="POST /api/v1/researches", body=body, response={"id": "x"})
        with self.assertRaises(Exception):
            IDEM.lookup("k-3", actor="other", route="POST /api/v1/researches", body=body)
        with self.assertRaises(Exception):
            IDEM.lookup("k-3", actor="tester", route="POST /api/v1/other", body=body)

    def test_IDM_07_http_header_replays_response(self):
        """IDM-07: два POST с одним ключом по HTTP → одно исследование."""
        import json as _json
        import threading
        import urllib.request
        from isheika.api import server as SRV

        httpd = SRV.Server(("127.0.0.1", 0), SRV.Handler)
        httpd.daemon_threads = True
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()
        base = "http://127.0.0.1:%d/api/v1" % httpd.server_address[1]

        def call(path, body, tok=None, hdr=None):
            req = urllib.request.Request(base + path, method="POST",
                                         data=_json.dumps(body).encode("utf-8"),
                                         headers={"Content-Type": "application/json",
                                                  **({"Authorization": "Bearer " + tok} if tok else {}),
                                                  **(hdr or {})})
            with urllib.request.urlopen(req, timeout=20) as r:
                return _json.loads(r.read().decode("utf-8")), dict(r.headers)

        try:
            login, _ = call("/auth/login", {"login": "analyst", "password": "dev:analyst"})
            tok = login["token"]
            body = {"query": "идемпотентность по HTTP", "title": "IDM-07", "countries": ["RU"]}
            a, ha = call("/researches", body, tok, {"Idempotency-Key": "http-key-1"})
            b, hb = call("/researches", body, tok, {"Idempotency-Key": "http-key-1"})
            self.assertEqual(a["id"], b["id"], "повтор по HTTP создал второе исследование")
            self.assertEqual(hb.get("Idempotency-Replayed"), "true")
            self.assertNotEqual(ha.get("Idempotency-Replayed"), "true")
            c, _ = call("/researches", body, tok, {"Idempotency-Key": "http-key-2"})
            self.assertNotEqual(a["id"], c["id"], "другой ключ — другое действие")
        finally:
            httpd.shutdown()
            httpd.server_close()
