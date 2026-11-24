"""Сквозной журнал действий времени работы (редакция 1.4.0, задача пользователя).

Назначение: по журналу должно быть возможно найти **ошибку, дефект и противоречие**,
а не только увидеть, что «что-то пошло не так». Поэтому запись журнала содержит:

* кто и что сделал (`actor`, `role`, `kind`, `action`, `entity_kind`/`entity_id`);
* чем закончилось (`outcome`, `http_status`, `error_code`, `duration_ms`);
* где искать (`request_id`, `correlation_id`, `job_id`, `research_id`, `boot_id`);
* почему сломалось (`error_type`, `stack` — полный traceback, а не первые 800 символов);
* подпись дефекта (`fingerprint`) — одинаковые падения группируются в один дефект.

Источники записей: `server` (HTTP-запросы и доменные действия), `workflow` (этапы),
`connector` (внешние API), `ai`, `scheduler` и `browser` (ошибки интерфейса, которые
раньше жили только в памяти вкладки и терялись при перезагрузке).

Гарантии:
* журналирование **никогда не роняет** предметную операцию: сбой записи уходит в
  резервный файл `journal-fallback.log` и счётчик `FAILED_WRITES`;
* секреты в журнал не попадают: значения ключей `password/token/api_key/secret/...`
  и строки вида `Bearer …` заменяются маской на любой глубине вложенности;
* объём ограничен политикой хранения (`journal_retention_days`, `journal_max_rows`).

Журнал не подменяет аудит (`audit_log`) и события (`workflow_events`): аудит
отвечает на вопрос «кто изменил предметные данные», события — «что произошло в
исследовании», журнал — «что делала система и где она сломалась».
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import telemetry
from .config import DATA_DIR, SETTINGS
from .contracts import CoreError, iso_now, new_id
from .storage import db

LEVELS = ("debug", "info", "warn", "error", "critical")
LEVEL_RANK = {name: i for i, name in enumerate(LEVELS)}
KINDS = ("action", "api", "workflow", "connector", "ai", "analytics", "storage",
         "security", "ui", "system")
SOURCES = ("server", "browser", "workflow", "connector", "scheduler", "test")

# Ключи, значения которых не должны попасть в журнал ни в каком виде.
SECRET_KEYS = re.compile(r"(password|passwd|secret|token|api[_-]?key|authorization|cookie|credential|private[_-]?key)",
                         re.I)
BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-+/=]{6,}", re.I)
URL_KEY = re.compile(r"([?&](?:api[_-]?key|key|token|access_token)=)[^&\s\"']+", re.I)
MASK = "***скрыто***"
MAX_TEXT = 2000
MAX_DETAIL = 8000

FAILED_WRITES = 0
_LOCK = threading.RLock()
_CLIENT_BUDGET: dict[str, list[float]] = {}


# ------------------------------------------------------------------ очистка данных
def redact(value, depth: int = 0):
    """Маскировка секретов и ограничение объёма (рекурсивно, с защитой от циклов)."""
    if depth > 6:
        return "…глубина вложенности ограничена…"
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:60]:
            key = str(k)
            out[key] = MASK if SECRET_KEYS.search(key) else redact(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v, depth + 1) for v in list(value)[:60]]
    if isinstance(value, str):
        s = BEARER.sub(r"\1" + MASK, value)
        s = URL_KEY.sub(r"\1" + MASK, s)
        s = "".join(ch for ch in s if ch >= " " or ch in "\n\t")
        return s if len(s) <= MAX_TEXT else s[:MAX_TEXT] + "…усечено…"
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact(str(value), depth + 1)


def _text(value, limit: int = MAX_TEXT) -> str:
    s = str(value if value is not None else "")
    s = BEARER.sub(r"\1" + MASK, s)
    s = URL_KEY.sub(r"\1" + MASK, s)
    return s if len(s) <= limit else s[:limit] + "…усечено…"


def fingerprint(kind: str, action: str, error_type: str = "", error_code: str = "",
                message: str = "", stack: str = "") -> str:
    """Подпись дефекта: одинаковые падения дают одинаковую подпись.

    Из сообщения убираются идентификаторы, числа и пути — иначе каждое падение
    с новым UUID считалось бы новым дефектом и группировка теряла смысл.
    """
    norm = re.sub(r"[0-9a-f]{8}-[0-9a-f-]{4,}", "<id>", str(message).lower())
    norm = re.sub(r"\b(?:res|doc|rep|job|req|aud|ev|rel|cid|bkp|alr)-[0-9a-z-]+", "<id>", norm)
    norm = re.sub(r"\d+", "<n>", norm)
    norm = re.sub(r"\s+", " ", norm).strip()[:200]
    frame = ""
    for line in reversed((stack or "").splitlines()):
        if line.strip().startswith("File "):
            frame = re.sub(r", line \d+", "", line.strip())
            break
    basis = "|".join([kind or "", action or "", error_type or "", error_code or "", norm, frame])
    return hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()[:16]


# ------------------------------------------------------------------ запись
def record(level: str, kind: str, action: str, message: str = "", *,
           actor: str | None = None, role: str | None = None, source: str = "server",
           outcome: str = "ok", http_status: int | None = None, duration_ms: float | None = None,
           research_id: str | None = None, entity_kind: str | None = None,
           entity_id: str | None = None, job_id: str | None = None,
           error_code: str | None = None, error_type: str | None = None,
           stack: str | None = None, detail: dict | None = None,
           client: dict | None = None, boot_id: str | None = None) -> str | None:
    """Одна запись журнала. Никогда не возбуждает исключение."""
    global FAILED_WRITES
    if not SETTINGS.journal_enabled:
        return None
    lvl = level if level in LEVEL_RANK else "info"
    floor = LEVEL_RANK.get(SETTINGS.journal_level, 1)
    if LEVEL_RANK[lvl] < floor:
        return None
    knd = kind if kind in KINDS else "system"
    src = source if source in SOURCES else "server"
    trace = telemetry.current()
    detail_json = json.dumps(redact(detail or {}), ensure_ascii=False, default=str)[:MAX_DETAIL]
    row = {
        "id": new_id("jrn-"),
        "at": iso_now(),
        "level": lvl,
        "kind": knd,
        "action": _text(action, 160),
        "message": _text(message),
        "actor": _text(actor, 80) or None,
        "role": _text(role, 40) or None,
        "source": src,
        "outcome": _text(outcome, 24),
        "http_status": http_status,
        "duration_ms": round(float(duration_ms), 3) if duration_ms is not None else None,
        "research_id": research_id,
        "entity_kind": _text(entity_kind, 40) or None,
        "entity_id": _text(entity_id, 80) or None,
        "job_id": job_id,
        "request_id": trace["request_id"],
        "correlation_id": trace["correlation_id"],
        "boot_id": boot_id,
        "error_code": _text(error_code, 40) or None,
        "error_type": _text(error_type, 80) or None,
        "stack": _text(stack, 6000) or None,
        "fingerprint": fingerprint(knd, action, error_type or "", error_code or "", message, stack or "")
        if lvl in ("error", "critical") else None,
        "detail": detail_json,
        "client": json.dumps(redact(client or {}), ensure_ascii=False, default=str)[:2000],
    }
    try:
        db.insert("ops_journal", row)
        return row["id"]
    except Exception as exc:  # noqa: BLE001 — журнал не имеет права ронять операцию
        with _LOCK:
            FAILED_WRITES += 1
        _fallback(row, exc)
        return None


def _fallback(row: dict, exc: Exception) -> None:
    """Резервный файл: сбой БД не должен означать потерю свидетельства об ошибке."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        path = os.path.join(DATA_DIR, "journal-fallback.log")
        if os.path.exists(path) and os.path.getsize(path) > 5_000_000:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"write_error": str(exc)[:200], **row}, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def error(exc: BaseException, kind: str, action: str, *, message: str = "", level: str = "error",
          **fields) -> str | None:
    """Запись об исключении: тип, код, полный traceback, подпись дефекта."""
    code = exc.error.code if isinstance(exc, CoreError) else fields.pop("error_code", None) or "E_INTERNAL"
    return record(level, kind, action, message or str(exc), error_code=code,
                  error_type=type(exc).__name__, stack="".join(
                      traceback.format_exception(type(exc), exc, exc.__traceback__)),
                  outcome="fail", **fields)


@contextmanager
def capture(kind: str, action: str, *, actor: str | None = None, level: str = "info", **fields):
    """Обёртка действия: длительность, исход и traceback при отказе.

        with journal.capture("action", "report.generate", research_id=rid):
            ...
    Исключение пробрасывается дальше — журнал наблюдает, а не глушит.
    """
    t0 = time.perf_counter()
    try:
        yield
    except BaseException as exc:
        error(exc, kind, action, actor=actor,
              duration_ms=(time.perf_counter() - t0) * 1000, **fields)
        raise
    else:
        record(level, kind, action, actor=actor, outcome="ok",
               duration_ms=(time.perf_counter() - t0) * 1000, **fields)


# ------------------------------------------------------------------ чтение
def _filters(level: str | None = None, kind: str | None = None, actor: str | None = None,
             source: str | None = None, research_id: str | None = None,
             correlation_id: str | None = None, request_id: str | None = None,
             outcome: str | None = None, q: str | None = None,
             since: str | None = None, until: str | None = None,
             fingerprint_: str | None = None) -> tuple[str, list]:
    sql, params = " FROM ops_journal WHERE 1=1", []
    if level:
        if level in LEVEL_RANK:
            sql += " AND level IN (%s)" % ",".join("?" * len(LEVELS[LEVEL_RANK[level]:]))
            params += list(LEVELS[LEVEL_RANK[level]:])
        else:
            sql += " AND level=?"; params.append(level)
    for col, val in (("kind", kind), ("actor", actor), ("source", source),
                     ("research_id", research_id), ("correlation_id", correlation_id),
                     ("request_id", request_id), ("outcome", outcome), ("fingerprint", fingerprint_)):
        if val:
            sql += f" AND {col}=?"; params.append(val)
    if since:
        sql += " AND at>=?"; params.append(since)
    if until:
        sql += " AND at<=?"; params.append(until)
    if q:
        sql += " AND (action LIKE ? OR message LIKE ? OR error_code LIKE ? OR entity_id LIKE ?)"
        params += [f"%{q}%"] * 4
    return sql, params


def query(*, limit: int = 200, offset: int = 0, **filters) -> dict:
    limit = max(1, min(int(limit or 200), 2000))
    offset = max(0, int(offset or 0))
    where, params = _filters(**filters)
    rows = db.query("SELECT *" + where + " ORDER BY at DESC, rowid DESC LIMIT ? OFFSET ?",
                    params + [limit, offset])
    total = (db.one("SELECT COUNT(*) AS n" + where, params) or {}).get("n", 0)
    return {"items": [db.dec(r, "detail", "client") for r in rows], "total": total,
            "limit": limit, "offset": offset,
            "levels": list(LEVELS), "kinds": list(KINDS),
            "retention_days": SETTINGS.journal_retention_days,
            "failed_writes": FAILED_WRITES}


def entry(journal_id: str) -> dict:
    row = db.one("SELECT * FROM ops_journal WHERE id=?", (journal_id,))
    if not row:
        raise CoreError("E_NOT_FOUND", "Запись журнала не найдена")
    item = db.dec(row, "detail", "client")
    cid = item.get("correlation_id")
    item["context"] = []
    if cid:
        item["context"] = [db.dec(r, "detail", "client") for r in db.query(
            """SELECT id, at, level, kind, action, message, outcome, error_code, duration_ms
               FROM ops_journal WHERE correlation_id=? ORDER BY at, rowid LIMIT 200""", (cid,))]
    return item


def errors(*, limit: int = 50, since: str | None = None) -> dict:
    """Дефекты, сгруппированные по подписи: сколько раз, когда впервые и в последний раз."""
    where, params = _filters(level="error", since=since)
    rows = db.query("""SELECT fingerprint, kind, action, error_code, error_type,
                              COUNT(*) AS occurrences, MIN(at) AS first_seen, MAX(at) AS last_seen,
                              COUNT(DISTINCT research_id) AS researches,
                              COUNT(DISTINCT actor) AS actors
                       """ + where + """
                       GROUP BY fingerprint ORDER BY occurrences DESC, last_seen DESC LIMIT ?""",
                    params + [max(1, min(int(limit or 50), 500))])
    out = []
    for r in rows:
        sample = db.one("SELECT id, at, message, stack, request_id, correlation_id, research_id, actor"
                        + where + " AND fingerprint=? ORDER BY at DESC, rowid DESC LIMIT 1",
                        params + [r["fingerprint"]])
        out.append({**r, "sample": db.dec(sample, "detail", "client") if sample else None})
    return {"items": out, "total": len(out),
            "note": "Подпись дефекта не зависит от идентификаторов и чисел: одинаковые падения группируются"}


def stats() -> dict:
    by_level = {r["level"]: r["n"] for r in db.query("SELECT level, COUNT(*) AS n FROM ops_journal GROUP BY level")}
    by_kind = {r["kind"]: r["n"] for r in db.query("SELECT kind, COUNT(*) AS n FROM ops_journal GROUP BY kind")}
    by_source = {r["source"]: r["n"] for r in db.query("SELECT source, COUNT(*) AS n FROM ops_journal GROUP BY source")}
    day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    day = db.one("""SELECT COUNT(*) AS total,
                           SUM(CASE WHEN level IN ('error','critical') THEN 1 ELSE 0 END) AS errors,
                           SUM(CASE WHEN level='warn' THEN 1 ELSE 0 END) AS warnings
                    FROM ops_journal WHERE at>=?""", (day_ago,)) or {}
    slow = db.query("""SELECT action, COUNT(*) AS n, ROUND(AVG(duration_ms), 1) AS avg_ms,
                              MAX(duration_ms) AS max_ms FROM ops_journal
                       WHERE duration_ms IS NOT NULL GROUP BY action ORDER BY avg_ms DESC LIMIT 8""")
    top = db.query("""SELECT actor, COUNT(*) AS n FROM ops_journal WHERE actor IS NOT NULL
                      GROUP BY actor ORDER BY n DESC LIMIT 8""")
    first = db.one("SELECT MIN(at) AS at FROM ops_journal") or {}
    return {"total": sum(by_level.values()), "by_level": by_level, "by_kind": by_kind,
            "by_source": by_source, "last_24h": day, "slowest_actions": slow, "top_actors": top,
            "first_entry_at": first.get("at"), "failed_writes": FAILED_WRITES,
            "retention_days": SETTINGS.journal_retention_days, "max_rows": SETTINGS.journal_max_rows,
            "browser_errors": by_source.get("browser", 0)}


def export(fmt: str = "txt", *, limit: int = 5000, **filters) -> str:
    data = query(limit=limit, **filters)
    rows = data["items"]
    if fmt == "json":
        return json.dumps(data, ensure_ascii=False, indent=1, default=str)
    if fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf)
        cols = ["at", "level", "kind", "source", "action", "actor", "role", "outcome",
                "http_status", "duration_ms", "error_code", "error_type", "research_id",
                "entity_kind", "entity_id", "request_id", "correlation_id", "fingerprint", "message",
                # ИД-23: без деталей клиентских событий выгрузку нельзя разобрать —
                # не видно версию приложения, экран, число попыток и задержку очереди.
                "app_version", "screen", "route", "viewport", "boot_id", "queued_at",
                "delivered_with_delay", "detail", "client"]
        w.writerow(cols)
        for r in rows:
            client = r.get("client") or {}
            row = [r.get(k) for k in cols[:19]]
            row += [client.get("app_version"), client.get("screen"), client.get("route"),
                    client.get("viewport"), r.get("boot_id") or client.get("boot_id"),
                    client.get("queued_at"), client.get("delivered_with_delay"),
                    json.dumps(r.get("detail") or {}, ensure_ascii=False, default=str),
                    json.dumps(client, ensure_ascii=False, default=str)]
            w.writerow(row)
        return buf.getvalue()
    lines = [f"ИЩЕЙКА НТР AI — журнал действий (записей: {len(rows)} из {data['total']})",
             f"Политика хранения: {SETTINGS.journal_retention_days} сут., не более {SETTINGS.journal_max_rows} записей",
             ""]
    for r in rows:
        head = (f"{r['at']} {r['level'].upper():8} {r['kind']:9} {r['source']:9} "
                f"{r['action']:32} {r.get('actor') or '—':12} {r.get('outcome') or '—'}")
        extra = []
        if r.get("http_status"):
            extra.append(f"HTTP {r['http_status']}")
        if r.get("duration_ms") is not None:
            extra.append(f"{r['duration_ms']} мс")
        if r.get("error_code"):
            extra.append(r["error_code"])
        if r.get("error_type"):
            extra.append(r["error_type"])
        rid = r.get("request_id") or (r.get("detail") or {}).get("request_id")
        if rid:
            extra.append("rid=" + str(rid))
        if r.get("correlation_id"):
            extra.append("cid=" + r["correlation_id"])
        lines.append(head + ("  [" + ", ".join(extra) + "]" if extra else ""))
        if r.get("message"):
            lines.append("    " + r["message"])
        # ИД-23: контекст события браузера и подробности — в текстовой выгрузке.
        client = r.get("client") or {}
        ctx = []
        if client.get("app_version"):
            ctx.append("версия " + str(client["app_version"]))
        if client.get("screen"):
            ctx.append("экран " + str(client["screen"]))
        if client.get("route"):
            ctx.append("маршрут " + str(client["route"]))
        if client.get("viewport"):
            ctx.append("окно " + str(client["viewport"]))
        if client.get("queued_at"):
            ctx.append("в очереди с " + str(client["queued_at"]) + " (доставлено с задержкой)")
        if ctx:
            lines.append("    " + " · ".join(ctx))
        if r.get("detail"):
            lines.append("    детали: " + json.dumps(r["detail"], ensure_ascii=False, default=str)[:1200])
        if r.get("stack"):
            lines += ["    " + s for s in r["stack"].splitlines()[-12:]]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ ошибки браузера
def client_event(body: dict, *, peer: str = "", actor: str | None = None,
                 role: str | None = None, user_agent: str = "") -> dict:
    """Приём ошибки интерфейса. До входа тоже работает: иначе первый отказ теряется.

    Ограничения: размер полей, только известные уровни/виды, не более
    `journal_client_rate` событий в минуту с одного адреса.
    """
    if not isinstance(body, dict):
        raise CoreError("E_VALIDATION", "Ожидается объект события")
    now = time.time()
    with _LOCK:
        bucket = [t for t in _CLIENT_BUDGET.get(peer, []) if now - t < 60]
        if len(bucket) >= SETTINGS.journal_client_rate:
            _CLIENT_BUDGET[peer] = bucket
            raise CoreError("E_RATE_LIMIT", "Слишком много событий журнала с одного адреса")
        bucket.append(now)
        _CLIENT_BUDGET[peer] = bucket
    level = str(body.get("level") or "error").lower()
    level = level if level in LEVEL_RANK else "error"
    kind = str(body.get("kind") or "ui").lower()
    kind = kind if kind in KINDS else "ui"
    action = _text(body.get("action") or "browser.event", 160)
    message = _text(body.get("message") or "", 1200)
    if not message and not body.get("stack"):
        raise CoreError("E_VALIDATION", "Не задано сообщение события")
    client = {
        "route": _text(body.get("route"), 120),
        "screen": _text(body.get("screen"), 40),
        "url": _text(body.get("url"), 300),
        "user_agent": _text(user_agent or body.get("user_agent"), 300),
        "viewport": _text(body.get("viewport"), 40),
        "app_version": _text(body.get("app_version"), 40),
        "boot_id": _text(body.get("boot_id"), 80),
        "peer": _text(peer, 60),
    }
    # Событие могло ждать в очереди браузера, пока сервер был недоступен (ред. 1.4.1).
    # Время постановки в очередь сохраняем: иначе задержка выглядит «свежим» отказом.
    queued_at = _text(body.get("queued_at"), 40)
    if queued_at:
        client["queued_at"] = queued_at
        client["delivered_with_delay"] = True
    jid = record(level, kind, action, message, source="browser", actor=actor, role=role,
                 outcome="fail" if level in ("error", "critical") else "ok",
                 error_code=_text(body.get("error_code"), 40) or None,
                 error_type=_text(body.get("error_type"), 80) or None,
                 stack=_text(body.get("stack"), 6000) or None,
                 research_id=_text(body.get("research_id"), 80) or None,
                 detail=body.get("detail") if isinstance(body.get("detail"), dict) else None,
                 client=client)
    return {"id": jid, "accepted": jid is not None,
            "budget_left": max(0, SETTINGS.journal_client_rate - len(_CLIENT_BUDGET.get(peer, [])))}


# ------------------------------------------------------------------ политика хранения
def prune(*, days: int | None = None, max_rows: int | None = None) -> dict:
    """Ротация: журнал не должен расти неограниченно и вытеснять предметные данные."""
    days = SETTINGS.journal_retention_days if days is None else days
    max_rows = SETTINGS.journal_max_rows if max_rows is None else max_rows
    removed_age = removed_cap = 0
    if days and days > 0:
        border = (datetime.now(timezone.utc) - timedelta(days=int(days))).isoformat(timespec="seconds")
        before = db.count("ops_journal")
        db.execute("DELETE FROM ops_journal WHERE at<?", (border,))
        removed_age = before - db.count("ops_journal")
    total = db.count("ops_journal")
    if max_rows and total > max_rows:
        db.execute("""DELETE FROM ops_journal WHERE id IN (
                          SELECT id FROM ops_journal ORDER BY at, rowid LIMIT ?)""", (total - max_rows,))
        removed_cap = total - db.count("ops_journal")
    return {"removed_by_age": removed_age, "removed_by_cap": removed_cap, "kept": db.count("ops_journal")}
