"""Адаптер FastAPI (промышленный транспорт по ТЗ-05 §9.2).

Сервисный слой не меняется: маршруты берутся из таблицы ROUTES stdlib-сервера.
Запуск (после установки зависимостей из requirements-optional.txt):

    uvicorn isheika.api.adapters_fastapi:app --host 0.0.0.0 --port 8000

Файл намеренно не импортируется ядром: отсутствие FastAPI не мешает работе
автономного профиля.
"""
from __future__ import annotations

import json
import os
import re

try:
    from fastapi import FastAPI, Request, Response
    from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
except ImportError as e:  # pragma: no cover
    raise SystemExit("FastAPI не установлен. Установите зависимости: pip install -r requirements-optional.txt") from e

from ..config import SETTINGS, WEB_DIR
from ..contracts import CoreError
from ..storage import db
from ..registry import loader
from ..workflow import events, pipeline  # noqa: F401
from . import service as S
from .server import ROUTES, PUBLIC_PATHS

db.init_db()
loader.seed_all()
app = FastAPI(title="ИЩЕЙКА НТР AI", version="1.2.0")


@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    response = await call_next(request)
    return response


def _make_handler(fn, pattern):
    async def handler(request: Request):
        body = {}
        if request.method in ("POST", "PUT", "PATCH"):
            try:
                body = await request.json()
            except Exception:
                body = {}
        path = request.url.path
        m = pattern.match(path)

        class Req:
            pass

        req = Req()
        req.qs = dict(request.query_params)
        try:
            if path not in PUBLIC_PATHS:
                auth = request.headers.get("authorization", "")
                token = auth[7:] if auth.startswith("Bearer ") else req.qs.get("token")
                req.session = S.session(token)
            else:
                req.session = None
            result = fn(req, m, body)
            return JSONResponse(json.loads(json.dumps(result, ensure_ascii=False, default=str)))
        except CoreError as e:
            code = {"E_AUTH": 401, "E_FORBIDDEN": 403, "E_NOT_FOUND": 404, "E_VALIDATION": 422,
                    "E_POLICY": 403, "E_QUOTA": 429, "E_RATE_LIMIT": 429}.get(e.error.code, 400)
            return JSONResponse({"error": e.error.to_dict()}, status_code=code)

    return handler


for method, pattern, fn in ROUTES:
    # преобразование regexp-маршрутов в синтаксис FastAPI
    path = pattern.pattern.strip("^$")
    path = re.sub(r"\(\[\^/\]\+\)", "{arg}", path)
    app.add_api_route(path, _make_handler(fn, pattern), methods=[method])


@app.get("/api/v1/events/stream")
async def sse(request: Request, token: str | None = None, research_id: str | None = None):
    S.session(token)
    q = events.subscribe()

    def gen():
        try:
            for chunk in events.stream(q):
                yield chunk
        finally:
            events.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/v1/reports/{report_id}/file")
async def report_file(report_id: str, fmt: str = "html", token: str | None = None):
    sess = S.session(token)
    S.require(sess, "research.read")
    path = S.report_file(report_id, fmt)
    return FileResponse(path, filename=os.path.basename(path))


if os.path.isdir(WEB_DIR):
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="ui")
