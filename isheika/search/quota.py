"""Планировщик квот (Прил. А §12.2 — обязателен).

Реализовано:
  * токен-бакет на домен (rps);
  * дневной/месячный счётчик обращений;
  * недельный счётчик байт для EPO OPS с жёстким стопом на 90 %;
  * ночное окно 19:00–07:00 GMT для тяжёлых патентных выгрузок;
  * чтение фактических остатков из заголовков/полей ответа.
Неизвестный лимит не подменяется выдуманным числом: limit=None => «неизвестно».
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from ..contracts import CoreError, iso_now, new_id
from ..storage import db

_LOCK = threading.RLock()
_BUCKETS: dict[str, tuple[float, float]] = {}   # domain -> (tokens, last_ts)


def _window_key(window: str) -> str:
    now = datetime.now(timezone.utc)
    if window == "day":
        return now.strftime("%Y-%m-%d")
    if window == "month":
        return now.strftime("%Y-%m")
    if window == "hour":
        return now.strftime("%Y-%m-%dT%H")
    if window in ("week", "week_bytes"):
        return now.strftime("%G-W%V")
    return "all"


def usage(scope: str, key: str, window: str) -> dict:
    wk = _window_key(window)
    row = db.one("SELECT used, limit_value FROM audit_quota_usage WHERE scope=? AND key=? AND window=?",
                 (scope, key, wk))
    return {"scope": scope, "key": key, "window": wk,
            "used": row["used"] if row else 0.0,
            "limit": row["limit_value"] if row else None}


def set_limit(scope: str, key: str, window: str, limit: float | None) -> None:
    wk = _window_key(window)
    db.upsert("audit_quota_usage", {"id": new_id("q-"), "scope": scope, "key": key, "window": wk,
                                    "used": usage(scope, key, window)["used"], "limit_value": limit,
                                    "updated_at": iso_now()}, key=("scope", "key", "window"))


def add_usage(scope: str, key: str, window: str, amount: float = 1.0, limit: float | None = None) -> None:
    with _LOCK:
        cur = usage(scope, key, window)
        wk = _window_key(window)
        db.upsert("audit_quota_usage", {"id": new_id("q-"), "scope": scope, "key": key, "window": wk,
                                        "used": cur["used"] + amount,
                                        "limit_value": limit if limit is not None else cur["limit"],
                                        "updated_at": iso_now()}, key=("scope", "key", "window"))


def check_counter(scope: str, key: str, window: str, limit: float | None, amount: float = 1.0) -> None:
    if limit is None:
        return
    if usage(scope, key, window)["used"] + amount > limit:
        raise CoreError("E_QUOTA", f"Квота исчерпана: {key} ({window})", retryable=False,
                        scope=scope, key=key, window=window, limit=limit)


def wait_token(domain: str, rps: float | None) -> float:
    """Токен-бакет на домен. Возвращает фактическое время ожидания, с."""
    if not rps or rps <= 0:
        return 0.0
    waited = 0.0
    with _LOCK:
        tokens, last = _BUCKETS.get(domain, (rps, time.monotonic()))
        now = time.monotonic()
        tokens = min(rps, tokens + (now - last) * rps)
        if tokens < 1.0:
            need = (1.0 - tokens) / rps
            waited = need
        _BUCKETS[domain] = (tokens, now)
    if waited > 0:
        time.sleep(waited)
        with _LOCK:
            tokens, last = _BUCKETS.get(domain, (rps, time.monotonic()))
            _BUCKETS[domain] = (tokens, time.monotonic())
    with _LOCK:
        tokens, last = _BUCKETS[domain]
        _BUCKETS[domain] = (max(0.0, tokens - 1.0), last)
    return waited


def in_night_window() -> bool:
    """Рекомендация EPO: тяжёлые выгрузки 19:00–07:00 GMT."""
    h = datetime.now(timezone.utc).hour
    return h >= 19 or h < 7


def enforce_connector_policy(conn: dict, *, heavy: bool = False) -> None:
    """Проверка политик коннектора перед обращением."""
    limits = conn.get("limits") or {}
    policy = conn.get("quota_policy") or {}
    window = policy.get("window", "second")
    code = conn["code"]

    if window == "week_bytes":
        hard = limits.get("hard_stop_bytes")
        check_counter("bytes", code, "week_bytes", hard)
        if heavy and policy.get("night_window_gmt") and not in_night_window():
            raise CoreError("E_POLICY", "Тяжёлая патентная выгрузка разрешена только 19:00–07:00 GMT",
                            retryable=True, connector=code)
    elif window == "day":
        check_counter("calls", code, "day", limits.get("per_day"))
    elif window == "month":
        check_counter("calls", code, "month", limits.get("per_month"))
    elif window == "hour":
        check_counter("calls", code, "hour", limits.get("per_hour"))


def record_response(conn: dict, *, bytes_read: int = 0, headers: dict | None = None,
                    body_json: dict | None = None) -> dict:
    """Учёт фактического расхода и чтение остатков квоты из ответа."""
    code = conn["code"]
    policy = conn.get("quota_policy") or {}
    window = policy.get("window", "second")
    observed: dict = {}
    if window == "week_bytes":
        add_usage("bytes", code, "week_bytes", bytes_read, (conn.get("limits") or {}).get("bytes_per_week"))
    elif window in ("day", "month", "hour"):
        add_usage("calls", code, window, 1, (conn.get("limits") or {}).get("per_" + window))
    headers = {k.lower(): v for k, v in (headers or {}).items()}
    for h in policy.get("read_headers", []):
        if h.lower() in headers:
            observed[h] = headers[h.lower()]
    field = policy.get("read_field")
    if field and isinstance(body_json, dict) and field in body_json:
        observed[field] = body_json[field]
    if observed:
        db.execute("UPDATE registry_connectors SET health_status=?, last_checked_at=? WHERE code=?",
                   ("active", iso_now(), code))
    return observed


def snapshot() -> list[dict]:
    return db.query("SELECT scope, key, [window], used, limit_value AS [limit], updated_at FROM audit_quota_usage ORDER BY key")
