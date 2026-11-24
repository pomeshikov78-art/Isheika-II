"""Идемпотентность изменяющих запросов (ИД-22, редакция 1.5.1).

Основание — журнал с машины пользователя: `POST /api/v1/researches` падал с
E_NETWORK, клиент повторяет такой запрос (он помечен ключом идемпотентности как
безопасный), а сервер ключ `Idempotency-Key` **игнорировал** — повтор создавал
второе исследование. Заголовок был объявлен в OpenAPI, но не реализован.

Правила:
  * ключ действует в пределах пары (актор, маршрут) и хранится `TTL_HOURS`;
  * повтор с тем же телом возвращает СОХРАНЁННЫЙ ответ, обработчик не вызывается;
  * повтор с другим телом — ошибка E_VALIDATION (ключ переиспользован неверно);
  * ключ уникален для действия, а не для текста запроса: два исследования с
    одинаковым запросом — это два разных действия и два разных ключа.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

from ..contracts import CoreError, iso_now
from ..storage import db

TTL_HOURS = 24
MAX_KEY = 120


def _hash(body) -> str:
    return hashlib.sha256(json.dumps(body or {}, sort_keys=True, ensure_ascii=False,
                                     default=str).encode("utf-8")).hexdigest()[:32]


def lookup(key: str, *, actor: str | None, route: str, body) -> dict | None:
    """Сохранённый ответ по ключу либо None. Несовпадение тела — ошибка."""
    key = (key or "").strip()[:MAX_KEY]
    if not key:
        return None
    row = db.one("SELECT * FROM ops_idempotency WHERE key=?", (key,))
    if row is None:
        return None
    if row["route"] != route or (row["actor"] or "") != (actor or ""):
        raise CoreError("E_VALIDATION", "Ключ идемпотентности уже использован для другого запроса")
    if row["body_hash"] != _hash(body):
        raise CoreError("E_VALIDATION", "Ключ идемпотентности использован с другим телом запроса")
    border = (datetime.now(timezone.utc) - timedelta(hours=TTL_HOURS)).isoformat(timespec="seconds")
    if (row["created_at"] or "") < border:
        db.execute("DELETE FROM ops_idempotency WHERE key=?", (key,))
        return None
    try:
        return json.loads(row["response"])
    except Exception:  # noqa: BLE001 — битая запись не должна ронять запрос
        return None


def store(key: str, *, actor: str | None, route: str, body, response) -> None:
    key = (key or "").strip()[:MAX_KEY]
    if not key or response is None:
        return
    db.upsert("ops_idempotency", {
        "key": key, "actor": actor or "", "route": route, "body_hash": _hash(body),
        "response": json.dumps(response, ensure_ascii=False, default=str),
        "created_at": iso_now()}, key="key")


def prune(*, hours: int = TTL_HOURS) -> int:
    border = (datetime.now(timezone.utc) - timedelta(hours=int(hours))).isoformat(timespec="seconds")
    before = db.count("ops_idempotency")
    db.execute("DELETE FROM ops_idempotency WHERE created_at<?", (border,))
    return before - db.count("ops_idempotency")
