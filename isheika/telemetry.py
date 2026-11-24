"""Трассировка запросов и заданий (ROADMAP P6, ТЗ-05 §11).

Каждый входящий HTTP-запрос получает `request_id`; вся цепочка действий внутри
него (события, вызовы внешних API, расчёты, запуск заданий) помечается общим
`correlation_id`. Фоновый поток исследования наследует correlation_id запуска,
поэтому журнал восстанавливает полный путь: запрос → задание → этап → источник
→ документ → расчёт → отчёт.

Идентификаторы не содержат персональных данных и не заменяют аудит: они лишь
связывают записи журнала между слоями. Пробрасываются в заголовках
`X-Request-ID` / `X-Correlation-ID` (входящие значения принимаются, если заданы).
"""
from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager

from .contracts import new_id

_REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_CORRELATION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)

_SAFE = re.compile(r"^[A-Za-z0-9._:\-]{6,80}$")


def sanitize(value: str | None) -> str | None:
    """Внешний идентификатор принимается только в безопасном формате (защита от инъекций в журнал)."""
    if not value:
        return None
    v = str(value).strip()
    return v if _SAFE.match(v) else None


def request_id() -> str | None:
    return _REQUEST_ID.get()


def correlation_id() -> str | None:
    return _CORRELATION_ID.get()


def current() -> dict:
    return {"request_id": _REQUEST_ID.get(), "correlation_id": _CORRELATION_ID.get()}


@contextmanager
def scope(*, request: str | None = None, correlation: str | None = None):
    """Контекст трассировки на время обработки запроса или этапа."""
    rid = sanitize(request) or new_id("req-")
    cid = sanitize(correlation) or rid
    t1, t2 = _REQUEST_ID.set(rid), _CORRELATION_ID.set(cid)
    try:
        yield {"request_id": rid, "correlation_id": cid}
    finally:
        _REQUEST_ID.reset(t1)
        _CORRELATION_ID.reset(t2)


def stamp(payload: dict | None = None) -> dict:
    """Метки трассировки для записи в журнал/событие/вызов внешнего API."""
    out = dict(payload or {})
    cur = current()
    if cur["request_id"] and "request_id" not in out:
        out["request_id"] = cur["request_id"]
    if cur["correlation_id"] and "correlation_id" not in out:
        out["correlation_id"] = cur["correlation_id"]
    return out
