"""SLO доступности и правила оповещения (ROADMAP P6, ТЗ-01 §12: ≥ 98 %/мес).

Модуль измеряет доступность САМОЙ системы, а не качество научных расчётов:

* самопроверки (`probe`) выполняют короткие операции над реальными
  подсистемами — БД, файловое хранилище, транспортный слой — и фиксируют
  результат, длительность и причину отказа;
* доступность считается по доле успешных самопроверок в окне; при отсутствии
  измерений возвращается состояние NO_DATA, а не «100 %» (выдумывать
  показатель запрещено — тот же принцип, что и для F/уверенности, ИД-10);
* бюджет ошибок = 100 % − цель; скорость его расхода (burn rate) — отношение
  доли отказов в коротком окне к допустимой доле отказов;
* правила (`RULES`) детерминированы и возвращают доказательства (числа),
  на основании которых открыт алерт; алерт живёт до устранения причины.

Все вычисления серверные; интерфейс только отображает готовые значения.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone

from .config import SETTINGS
from .contracts import CoreError, iso_now, new_id
from .storage import db

TARGET_AVAILABILITY = 98.0                 # ТЗ-01: доступность не ниже 98 % за месяц
ERROR_BUDGET = round(100.0 - TARGET_AVAILABILITY, 6)   # 2 % отказов
WINDOWS = (("24h", 24), ("7d", 168), ("30d", 720))
COMPONENTS = ("api", "database", "storage")
PROBE_INTERVAL_SEC = 60                    # период фоновых самопроверок
BURN_RATE_CRITICAL = 14.4                  # классический порог быстрого выгорания бюджета
BACKUP_MAX_AGE_HOURS = 168                 # регламент: копия не старше 7 суток


def _since(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")


def _round(v: float | None, nd: int = 6) -> float | None:
    return None if v is None else round(float(v), nd)


# ------------------------------------------------------------------ самопроверки
def probe(component: str) -> dict:
    """Одна самопроверка подсистемы. Отказ фиксируется, а не пробрасывается."""
    if component not in COMPONENTS:
        raise CoreError("E_VALIDATION", f"Неизвестный компонент: {component}")
    started = time.perf_counter()
    ok, detail = True, ""
    try:
        if component == "database":
            row = db.one("SELECT COUNT(*) AS c FROM meta_migrations")
            integrity = db.one("PRAGMA quick_check")
            state = next(iter(integrity.values())) if integrity else "unknown"
            ok = state == "ok"
            detail = f"migrations={row['c'] if row else 0}; quick_check={state}"
        elif component == "storage":
            SETTINGS.ensure_dirs()
            path = os.path.join(SETTINGS.files_dir, ".slo-probe")
            with open(path, "w", encoding="utf-8") as f:
                f.write(iso_now())
            os.remove(path)
            detail = "files_dir доступен на запись"
        elif component == "api":
            from .api.server import ROUTES          # поздний импорт: без цикла
            ok = len(ROUTES) > 0
            detail = f"routes={len(ROUTES)}"
    except Exception as exc:
        ok, detail = False, f"{type(exc).__name__}: {exc}"[:300]
    return record(component, ok, round((time.perf_counter() - started) * 1000, 3), detail)


def record(component: str, ok: bool, latency_ms: float, detail: str = "",
           *, at: str | None = None) -> dict:
    """Запись результата самопроверки (используется и планировщиком, и тестами)."""
    row = {"id": new_id("prb-"), "at": at or iso_now(), "component": component,
           "ok": 1 if ok else 0, "latency_ms": latency_ms, "detail": detail}
    db.insert("service_probes", row)
    return row


def run_probes() -> list[dict]:
    return [probe(c) for c in COMPONENTS]


def last_probes() -> dict:
    out = {}
    for c in COMPONENTS:
        # rowid разрешает ничьи: метки времени имеют точность до секунды
        row = db.one("SELECT * FROM service_probes WHERE component=? ORDER BY at DESC, rowid DESC LIMIT 1", (c,))
        out[c] = row
    return out


# ------------------------------------------------------------------ доступность
def window_stats(hours: float, component: str | None = None) -> dict:
    """Доступность в окне. NO_DATA, если измерений нет — значение не выдумывается."""
    sql = "SELECT COUNT(*) AS total, SUM(ok) AS ok, AVG(latency_ms) AS lat FROM service_probes WHERE at >= ?"
    params: list = [_since(hours)]
    if component:
        sql += " AND component=?"
        params.append(component)
    row = db.one(sql, params) or {}
    total = int(row.get("total") or 0)
    ok = int(row.get("ok") or 0)
    failed = total - ok
    availability = _round(ok / total * 100.0) if total else None
    budget_used = _round((100.0 - availability) / ERROR_BUDGET * 100.0, 3) if availability is not None else None
    return {
        "window_hours": hours, "component": component or "all",
        "probes": total, "ok": ok, "failed": failed,
        "availability_pct": availability,
        "target_pct": TARGET_AVAILABILITY,
        "error_budget_pct": ERROR_BUDGET,
        "error_budget_used_pct": budget_used,
        "latency_ms_avg": _round(row.get("lat"), 3),
        "estimated_downtime_minutes": _round(failed * PROBE_INTERVAL_SEC / 60.0, 2),
        "state": "NO_DATA" if not total else ("BREACH" if availability < TARGET_AVAILABILITY else "OK"),
    }


def burn_rate(hours: float = 1.0, component: str | None = None) -> dict:
    """Скорость расхода бюджета ошибок: доля отказов / допустимая доля отказов."""
    st = window_stats(hours, component)
    rate = _round(st["failed"] / st["probes"] / (ERROR_BUDGET / 100.0), 3) if st["probes"] else None
    return {"window_hours": hours, "component": component or "all", "probes": st["probes"], "burn_rate": rate,
            "threshold": BURN_RATE_CRITICAL,
            "state": "NO_DATA" if rate is None else ("CRITICAL" if rate >= BURN_RATE_CRITICAL else "OK")}


def report() -> dict:
    """Сводка SLO для экрана эксплуатации и метрик."""
    windows = [dict(window_stats(h), window=name) for name, h in WINDOWS]
    components = [window_stats(24, c) for c in COMPONENTS]
    month = next(w for w in windows if w["window"] == "30d")
    return {
        "generated_at": iso_now(),
        "target_pct": TARGET_AVAILABILITY,
        "error_budget_pct": ERROR_BUDGET,
        "probe_interval_sec": PROBE_INTERVAL_SEC,
        "windows": windows,
        "components": components,
        "burn_rate_1h": burn_rate(1.0),
        "burn_rate_6h": burn_rate(6.0),
        "last_probes": last_probes(),
        "probes_total": db.count("service_probes"),
        "state": month["state"],
        "measurement_note": ("Доступность = доля успешных самопроверок (api/database/storage) "
                             "в окне; при отсутствии измерений — NO_DATA."),
    }


# ------------------------------------------------------------------ правила оповещения
def _rule_availability() -> tuple[bool, str, dict]:
    st = window_stats(720)
    if st["state"] == "NO_DATA":
        return False, "", st
    fired = st["availability_pct"] < TARGET_AVAILABILITY
    return fired, (f"Доступность за 30 суток {st['availability_pct']:.3f} % ниже цели "
                   f"{TARGET_AVAILABILITY} % (отказов {st['failed']} из {st['probes']})"), st


def _rule_burn() -> tuple[bool, str, dict]:
    st = burn_rate(1.0)
    fired = st["burn_rate"] is not None and st["burn_rate"] >= BURN_RATE_CRITICAL and st["probes"] >= 10
    return fired, (f"Бюджет ошибок расходуется со скоростью {st['burn_rate']}× "
                   f"(порог {BURN_RATE_CRITICAL}×)"), st


def _rule_component() -> tuple[bool, str, dict]:
    last = last_probes()
    down = [c for c, r in last.items() if r and not r["ok"]]
    ev = {"components": {c: (None if not r else {"ok": bool(r["ok"]), "at": r["at"], "detail": r["detail"]})
                       for c, r in last.items()}}
    return bool(down), "Отказ подсистемы при последней самопроверке: " + ", ".join(down), ev


def _rule_connectors() -> tuple[bool, str, dict]:
    rows = db.query("SELECT health_status, COUNT(*) AS n FROM registry_connectors GROUP BY health_status")
    known = [r for r in rows if r["health_status"] not in ("not_implemented", None, "")]
    total = sum(r["n"] for r in known)
    bad = sum(r["n"] for r in known if r["health_status"] in ("error", "unavailable"))
    share = _round(bad / total, 4) if total else None
    fired = share is not None and share > 0.30
    return fired, (f"Недоступно {bad} из {total} проверенных коннекторов ({share:.0%})" if share is not None else ""), {
        "checked": total, "unavailable": bad, "share": share, "threshold": 0.30}


def _rule_providers() -> tuple[bool, str, dict]:
    rows = db.query("SELECT status, COUNT(*) AS n FROM ai_providers GROUP BY status")
    total = sum(r["n"] for r in rows)
    bad = sum(r["n"] for r in rows if r["status"] in ("quota_exhausted", "auth_error", "unavailable", "rate_limited"))
    share = _round(bad / total, 4) if total else None
    fired = share is not None and share > 0.50
    return fired, (f"Недоступно {bad} из {total} провайдеров ИИ ({share:.0%})" if share is not None else ""), {
        "total": total, "unavailable": bad, "share": share, "threshold": 0.50}


def _rule_backup() -> tuple[bool, str, dict]:
    row = db.one("SELECT created_at FROM ops_backups ORDER BY created_at DESC LIMIT 1")
    if not row:
        return True, "Резервных копий нет: восстановление после сбоя невозможно", {"last_backup_at": None}
    age_h = (datetime.now(timezone.utc) - datetime.fromisoformat(row["created_at"])).total_seconds() / 3600.0
    fired = age_h > BACKUP_MAX_AGE_HOURS
    return fired, (f"Последняя резервная копия старше {BACKUP_MAX_AGE_HOURS} ч "
                   f"({age_h:.1f} ч назад)"), {"last_backup_at": row["created_at"], "age_hours": _round(age_h, 2),
                                              "max_age_hours": BACKUP_MAX_AGE_HOURS}


RULES = {
    "SLO_AVAILABILITY_30D": {"severity": "critical", "title": "Доступность ниже цели 98 %/мес",
                             "fn": _rule_availability},
    "SLO_BURN_RATE_1H": {"severity": "critical", "title": "Быстрый расход бюджета ошибок",
                         "fn": _rule_burn},
    "COMPONENT_DOWN": {"severity": "critical", "title": "Отказ подсистемы",
                       "fn": _rule_component},
    "CONNECTORS_DEGRADED": {"severity": "warning", "title": "Более 30 % коннекторов недоступны",
                            "fn": _rule_connectors},
    "PROVIDERS_UNAVAILABLE": {"severity": "warning", "title": "Более 50 % провайдеров ИИ недоступны",
                              "fn": _rule_providers},
    "BACKUP_OVERDUE": {"severity": "warning", "title": "Резервная копия просрочена",
                       "fn": _rule_backup},
}


def evaluate_alerts(*, actor: str = "system", emit_events: bool = True) -> dict:
    """Проверка всех правил: открытие новых алертов и закрытие устранённых."""
    from .workflow import events
    opened, closed = [], []
    for code, rule in RULES.items():
        fired, message, evidence = rule["fn"]()
        current = db.one("SELECT * FROM ops_alerts WHERE rule_code=? AND state<>'closed' ORDER BY opened_at DESC", (code,))
        if fired and not current:
            row = {"id": new_id("alr-"), "rule_code": code, "severity": rule["severity"],
                   "state": "open", "message": message or rule["title"], "context": evidence,
                   "opened_at": iso_now()}
            db.insert("ops_alerts", row)
            opened.append(row)
            if emit_events:
                events.emit("system.warning" if rule["severity"] == "warning" else "system.error",
                            payload={"alert_id": row["id"], "rule_code": code, "message": row["message"],
                                     "evidence": evidence},
                            severity="warning" if rule["severity"] == "warning" else "error")
        elif fired and current:
            db.update("ops_alerts", "id", current["id"], {"message": message or rule["title"], "context": evidence})
        elif not fired and current:
            db.update("ops_alerts", "id", current["id"], {"state": "closed", "closed_at": iso_now()})
            closed.append(current["id"])
            if emit_events:
                events.emit("system.warning", payload={"alert_id": current["id"], "rule_code": code,
                                                       "message": "Причина устранена, алерт закрыт"})
    return {"opened": opened, "closed": closed, "alerts": alerts(state="active")}


def alerts(state: str = "all", limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM ops_alerts"
    params: list = []
    if state == "active":
        sql += " WHERE state<>'closed'"
    elif state in ("open", "closed", "acknowledged"):
        sql += " WHERE state=?"
        params.append(state)
    sql += " ORDER BY opened_at DESC LIMIT ?"
    params.append(int(limit))
    return [db.dec(r, "context") for r in db.query(sql, params)]


def acknowledge(alert_id: str, *, actor: str = "system") -> dict:
    row = db.one("SELECT * FROM ops_alerts WHERE id=?", (alert_id,))
    if not row:
        raise CoreError("E_NOT_FOUND", "Алерт не найден")
    if row["state"] != "open":
        raise CoreError("E_STATE", "Подтвердить можно только открытый алерт")
    db.update("ops_alerts", "id", alert_id, {"state": "acknowledged", "ack_by": actor, "ack_at": iso_now()})
    return db.dec(db.one("SELECT * FROM ops_alerts WHERE id=?", (alert_id,)), "context")


def tick(*, actor: str = "scheduler") -> dict:
    """Один цикл эксплуатационного наблюдения: самопроверки → правила."""
    probes = run_probes()
    res = evaluate_alerts(actor=actor)
    return {"probes": probes, "opened": len(res["opened"]), "closed": len(res["closed"])}
