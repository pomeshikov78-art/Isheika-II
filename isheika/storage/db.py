"""Доступ к БД. Профиль DEV — SQLite (ТЗ-01 §7), PILOT/PROD — PostgreSQL.

Слой SQL написан так, чтобы миграция на PostgreSQL требовала замены драйвера
и типов (JSONB/UUID/TIMESTAMPTZ), а не переписывания запросов.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Iterable

from ..config import SETTINGS
from ..contracts import iso_now, new_id

_LOCK = threading.RLock()
_LOCAL = threading.local()
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def connect() -> sqlite3.Connection:
    conn = getattr(_LOCAL, "conn", None)
    if conn is None:
        SETTINGS.ensure_dirs()
        conn = sqlite3.connect(SETTINGS.db_path, timeout=30, isolation_level=None,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        _LOCAL.conn = conn
    return conn


def close() -> None:
    """Закрытие соединения текущего потока (нужно при восстановлении из копии)."""
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        try:
            conn.close()
        finally:
            _LOCAL.conn = None


def init_db() -> None:
    """Создание схемы + применение миграций редакции v1.1 (см. storage/migrate.py)."""
    from . import migrate
    with _LOCK:
        conn = connect()
        conn.execute("""CREATE TABLE IF NOT EXISTS meta_migrations (
                            version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)""")
        legacy = migrate.is_legacy(conn)
        if not legacy:
            with open(SCHEMA_PATH, encoding="utf-8") as f:
                conn.executescript(f.read())
        conn.execute("INSERT OR IGNORE INTO meta_migrations(version, applied_at) VALUES (?,?)",
                     ("0001_init", iso_now()))
        migrate.apply_all(conn)
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            conn.executescript(f.read())


def query(sql: str, params: Iterable[Any] = ()) -> list[dict]:
    cur = connect().execute(sql, tuple(params))
    return [dict(r) for r in cur.fetchall()]


def one(sql: str, params: Iterable[Any] = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    with _LOCK:
        connect().execute(sql, tuple(params))


def insert(table: str, data: dict) -> str:
    """Вставка словаря; dict/list сериализуются в JSON-текст."""
    row = {k: _enc(v) for k, v in data.items()}
    if "id" in row and not row["id"]:
        row["id"] = new_id()
    cols = ", ".join(row.keys())
    marks = ", ".join("?" for _ in row)
    with _LOCK:
        connect().execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))
    return row.get("id", "")


def upsert(table: str, data: dict, key: str | tuple = "id") -> None:
    row = {k: _enc(v) for k, v in data.items()}
    keys = (key,) if isinstance(key, str) else tuple(key)
    cols = ", ".join(row.keys())
    marks = ", ".join("?" for _ in row)
    conflict = ", ".join(keys)
    updates = ", ".join(f"{k}=excluded.{k}" for k in row if k not in keys)
    if not updates:
        updates = f"{keys[0]}=excluded.{keys[0]}"
    with _LOCK:
        connect().execute(
            f"INSERT INTO {table} ({cols}) VALUES ({marks}) ON CONFLICT({conflict}) DO UPDATE SET {updates}",
            tuple(row.values()))


def update(table: str, key_col: str, key_val: Any, data: dict) -> None:
    row = {k: _enc(v) for k, v in data.items()}
    sets = ", ".join(f"{k}=?" for k in row)
    with _LOCK:
        connect().execute(f"UPDATE {table} SET {sets} WHERE {key_col}=?",
                          tuple(row.values()) + (key_val,))


def _enc(v: Any) -> Any:
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return 1 if v else 0
    return v


def dec(row: dict | None, *fields: str) -> dict | None:
    """Декодирование JSON-полей строки."""
    if row is None:
        return None
    out = dict(row)
    for f in fields:
        if f in out and isinstance(out[f], str):
            try:
                out[f] = json.loads(out[f])
            except Exception:
                pass
    return out


def count(table: str, where: str = "1=1", params: Iterable[Any] = ()) -> int:
    r = one(f"SELECT COUNT(*) AS c FROM {table} WHERE {where}", params)
    return int(r["c"]) if r else 0


class transaction:
    """Контекст транзакции (ТЗ-06 §9.1)."""

    def __enter__(self):
        _LOCK.acquire()
        self.conn = connect()
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.execute("COMMIT")
            else:
                self.conn.execute("ROLLBACK")
        finally:
            _LOCK.release()
        return False
