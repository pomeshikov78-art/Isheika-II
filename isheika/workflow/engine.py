"""Граф выполнения исследования и менеджер заданий (ТЗ-05 §10, ТЗ-06 §8).

12 этапов информационно-вычислительного процесса (ТЗ-05 §4.1). Каждый этап —
задание с состоянием, попытками, идемпотентным ключом и прогрессом. Прерванное
исследование продолжается с незавершённых этапов, а не начинается заново.
"""
from __future__ import annotations

import threading
import traceback
from typing import Callable

from .. import telemetry
from ..contracts import CoreError, iso_now, new_id
from ..states import assert_transition
from ..storage import db
from . import events

STAGES: list[tuple[str, str, list[str]]] = [
    ("task_setup", "Этап 1. Постановка задачи", []),
    ("search_model", "Этап 2. Формирование поисковой модели", ["task_setup"]),
    ("source_search", "Этап 3. Поиск по источникам", ["search_model"]),
    ("document_processing", "Этап 4. Обработка документов", ["source_search"]),
    ("relevance_filter", "Этап 5. Фильтрация релевантности", ["document_processing"]),
    ("ai_tasks", "Этап 6. Постановка задач ИИ-агентам", ["relevance_filter"]),
    ("collective_analysis", "Этап 7. Коллективный анализ", ["ai_tasks"]),
    ("evidence_base", "Этап 8. Формирование доказательной базы", ["collective_analysis"]),
    ("math_core", "Этап 9. Математические расчёты (TRL, реализуемость)", ["evidence_base"]),
    ("forecast", "Этап 10. Прогнозирование", ["math_core"]),
    ("quality_control", "Этап 11. Контроль качества", ["forecast"]),
    ("report", "Этап 12. Формирование результата", ["quality_control"]),
]

HANDLERS: dict[str, Callable[[dict, dict], dict]] = {}
_RUNNING: dict[str, threading.Thread] = {}
_CANCEL: dict[str, threading.Event] = {}
_LOCK = threading.RLock()


def stage_handler(stage: str):
    def deco(fn):
        HANDLERS[stage] = fn
        return fn
    return deco


def create_workflow(research_id: str) -> list[dict]:
    jobs = []
    for stage, name, deps in STAGES:
        existing = db.one("SELECT * FROM workflow_jobs WHERE research_id=? AND stage=?", (research_id, stage))
        if existing:
            jobs.append(existing)
            continue
        jid = new_id("job-")
        db.insert("workflow_jobs", {
            "id": jid, "research_id": research_id, "stage": stage, "name": name,
            "status": "queued", "depends_on": deps, "attempts": 0,
            "idempotency_key": f"{research_id}:{stage}:v1", "progress": 0,
            "processed": 0, "total": 0, "result": {}, "created_at": iso_now()})
        jobs.append(db.one("SELECT * FROM workflow_jobs WHERE id=?", (jid,)))
    return jobs


def _ts(value: str) -> float:
    import datetime
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def set_job_state(job_id: str, state: str, *, reason: str = "", **fields) -> None:
    job = db.one("SELECT * FROM workflow_jobs WHERE id=?", (job_id,))
    if not job:
        return
    if job["status"] != state:
        assert_transition("task", job["status"], state)
        db.insert("core_state_history", {"id": new_id("st-"), "entity_kind": "task", "entity_id": job_id,
                                        "from_state": job["status"], "to_state": state, "reason": reason,
                                        "actor": "workflow", "created_at": iso_now()})
    upd = {"status": state, **fields}
    if state == "running" and not job["started_at"]:
        upd["started_at"] = iso_now()
    if state in ("completed", "failed", "cancelled", "partial"):
        now = iso_now()
        upd["finished_at"] = now
        start = job.get("started_at")
        if start:
            upd["duration_ms"] = max(0, int((_ts(now) - _ts(start)) * 1000))
    cid = telemetry.correlation_id()
    if cid and not job.get("correlation_id"):
        upd["correlation_id"] = cid
    db.update("workflow_jobs", "id", job_id, upd)


def set_research_state(research_id: str, state: str, *, reason: str = "") -> None:
    r = db.one("SELECT status FROM core_researches WHERE id=?", (research_id,))
    if not r:
        raise CoreError("E_NOT_FOUND", "Исследование не найдено", research_id=research_id)
    if r["status"] != state:
        assert_transition("research", r["status"], state)
        db.insert("core_state_history", {"id": new_id("st-"), "entity_kind": "research", "entity_id": research_id,
                                        "from_state": r["status"], "to_state": state, "reason": reason,
                                        "actor": "workflow", "created_at": iso_now()})
    db.update("core_researches", "id", research_id, {"status": state, "updated_at": iso_now()})
    events.emit("research.state_changed", research_id=research_id,
                payload={"from": r["status"], "to": state, "reason": reason})


def progress(job_id: str, processed: int, total: int, message: str = "") -> None:
    pct = (processed / total) if total else 0.0
    db.update("workflow_jobs", "id", job_id, {"processed": processed, "total": total, "progress": pct})
    job = db.one("SELECT research_id, stage FROM workflow_jobs WHERE id=?", (job_id,))
    events.emit("job.progress", research_id=job["research_id"], job_id=job_id,
                payload={"stage": job["stage"], "processed": processed, "total": total,
                         "progress": round(pct, 3), "message": message})


def cancel(research_id: str) -> None:
    with _LOCK:
        ev = _CANCEL.get(research_id)
        if ev:
            ev.set()
    set_research_state(research_id, "cancelled", reason="Отменено пользователем")
    for j in db.query("SELECT id,status FROM workflow_jobs WHERE research_id=? AND status IN ('queued','running')",
                      (research_id,)):
        set_job_state(j["id"], "cancelled", reason="Отмена исследования")
    events.emit("research.state_changed", research_id=research_id, payload={"to": "cancelled"})


def is_cancelled(research_id: str) -> bool:
    ev = _CANCEL.get(research_id)
    return bool(ev and ev.is_set())


def start(research_id: str, *, resume: bool = False) -> dict:
    """Запуск (или продолжение) исследования в фоновом потоке."""
    with _LOCK:
        if research_id in _RUNNING and _RUNNING[research_id].is_alive():
            return {"status": "already_running", "research_id": research_id}
        _CANCEL[research_id] = threading.Event()
    create_workflow(research_id)
    if resume:
        for j in db.query("SELECT id FROM workflow_jobs WHERE research_id=? AND status IN ('failed','partial','retry_wait')",
                          (research_id,)):
            set_job_state(j["id"], "queued", reason="Повторный запуск после сбоя")
    set_research_state(research_id, "queued", reason="Принято в очередь")
    # фоновый поток наследует трассировку запроса, инициировавшего запуск (P6)
    cid = telemetry.correlation_id() or new_id("run-")
    t = threading.Thread(target=_run, args=(research_id, cid), name=f"research-{research_id[:8]}", daemon=True)
    with _LOCK:
        _RUNNING[research_id] = t
    t.start()
    events.emit("research.started", research_id=research_id, payload={"resume": resume})
    return {"status": "accepted", "research_id": research_id}


def _run(research_id: str, correlation_id: str | None = None) -> None:
    with telemetry.scope(correlation=correlation_id or new_id("run-")):
        _run_stages(research_id)


def _run_stages(research_id: str) -> None:
    from ..storage import db as _db
    from . import pipeline as _pipeline          # регистрация обработчиков этапов
    _db.connect()
    ctx: dict = {"research_id": research_id}
    failed: list[str] = []
    partial: list[str] = []
    try:
        set_research_state(research_id, "running", reason="Запуск графа выполнения")
        for stage, name, deps in STAGES:
            if is_cancelled(research_id):
                break
            job = db.one("SELECT * FROM workflow_jobs WHERE research_id=? AND stage=?", (research_id, stage))
            job = db.dec(job, "depends_on", "result")
            if job["status"] == "completed":
                ctx[stage] = job["result"]
                continue
            dep_ok = True
            for d in deps:
                dj = db.one("SELECT status FROM workflow_jobs WHERE research_id=? AND stage=?", (research_id, d))
                if not dj or dj["status"] not in ("completed", "partial"):
                    dep_ok = False
            if not dep_ok:
                set_job_state(job["id"], "skipped", reason="Не выполнены зависимости")
                partial.append(stage)
                continue
            handler = HANDLERS.get(stage)
            if handler is None:
                set_job_state(job["id"], "skipped", reason="Обработчик этапа не реализован")
                partial.append(stage)
                continue
            set_job_state(job["id"], "running")
            db.update("workflow_jobs", "id", job["id"], {"attempts": job["attempts"] + 1})
            events.emit("job.started", research_id=research_id, job_id=job["id"],
                        payload={"stage": stage, "name": name})
            try:
                previous = result_signature(job.get("result"))
                result = handler(job, ctx) or {}
                state = result.pop("_state", "completed")
                set_job_state(job["id"], state, result=result, progress=1.0)
                ctx[stage] = result
                # Этап выполнен заново и дал другой предметный результат —
                # зависимые этапы обязаны пересчитаться, иначе новые документы
                # не дойдут до оценки, расчётов и отчёта (ИД-17).
                if job["attempts"] > 0 and result_signature(result) != previous:
                    invalidate_dependents(research_id, stage,
                                          reason="Результат этапа изменился при повторном выполнении")
                if state == "partial":
                    partial.append(stage)
                events.emit("job.completed", research_id=research_id, job_id=job["id"],
                            payload={"stage": stage, "state": state, "summary": _summary(result)})
            except CoreError as e:
                failed.append(stage)
                set_job_state(job["id"], "failed", reason=e.error.message,
                              error_code=e.error.code, error_message=e.error.message)
                events.emit("job.failed", research_id=research_id, job_id=job["id"], severity="error",
                            payload={"stage": stage, **e.error.to_dict()})
            except Exception as e:  # noqa: BLE001
                failed.append(stage)
                tb = traceback.format_exc()[-1500:]
                set_job_state(job["id"], "failed", reason=str(e)[:300],
                              error_code="E_INTERNAL", error_message=str(e)[:500])
                events.emit("job.failed", research_id=research_id, job_id=job["id"], severity="error",
                            payload={"stage": stage, "code": "E_INTERNAL", "message": str(e)[:300], "trace": tb})
                # Полный traceback этапа — в журнал действий: событие хранит хвост,
                # а для разбора дефекта нужна вся цепочка вызовов (ред. 1.4.0).
                try:
                    from .. import journal
                    journal.error(e, "workflow", f"stage.{stage}", message=str(e),
                                  source="workflow", research_id=research_id, job_id=job["id"],
                                  error_code="E_INTERNAL", entity_kind="job", entity_id=job["id"],
                                  detail={"stage": stage, "name": name, "attempt": job["attempts"] + 1})
                except Exception:
                    pass
        if is_cancelled(research_id):
            final = "cancelled"
        elif failed and not partial:
            final = "failed" if len(failed) >= len(STAGES) / 2 else "partial"
        elif failed or partial:
            final = "partial"
        else:
            final = "completed"
        set_research_state(research_id, final, reason=f"failed={failed} partial={partial}")
        events.emit("research.completed", research_id=research_id,
                    payload={"state": final, "failed": failed, "partial": partial})
    except Exception as e:  # noqa: BLE001
        try:
            set_research_state(research_id, "failed", reason=str(e)[:300])
        except Exception:
            pass
        events.emit("system.error", research_id=research_id, severity="error", payload={"message": str(e)[:300]})
        try:
            from .. import journal
            journal.error(e, "workflow", "research.run", message=str(e), source="workflow",
                          research_id=research_id, error_code="E_INTERNAL",
                          entity_kind="research", entity_id=research_id)
        except Exception:
            pass
    finally:
        with _LOCK:
            _RUNNING.pop(research_id, None)



# Поля, которые меняются от запуска к запуску сами по себе (время, счётчики
# обращений) и не означают изменения предметного результата этапа.
_VOLATILE = {"at", "generated_at", "checked_at", "started_at", "finished_at",
             "duration_ms", "elapsed_ms", "run_id", "report_id", "created_at"}


def result_signature(result: dict | None) -> str:
    """Подпись предметного результата этапа — для решения о пересчёте зависимых."""
    import hashlib
    import json
    data = {k: v for k, v in (result or {}).items() if k not in _VOLATILE and not k.startswith("_")}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                     default=str).encode("utf-8")).hexdigest()[:16]


def dependents(stage: str) -> list[str]:
    """Все этапы, которые прямо или косвенно зависят от данного (в порядке графа)."""
    out: list[str] = []
    for s, _name, deps in STAGES:
        if s == stage:
            continue
        if any(d == stage or d in out for d in deps):
            out.append(s)
    return out


def invalidate_dependents(research_id: str, stage: str, *, reason: str) -> list[str]:
    """Возвращает зависимые этапы в очередь пересчёта.

    Основание — журнал с машины пользователя (ред. 1.4.2): повторный запуск
    выполнял только этап 3, находил новые документы, а этапы 4–12 считались
    завершёнными и пропускались. Новые документы не оценивались и не попадали
    в отчёт, хотя исследование помечалось завершённым.
    """
    reset: list[str] = []
    for s in dependents(stage):
        row = db.one("SELECT id, status FROM workflow_jobs WHERE research_id=? AND stage=?",
                     (research_id, s))
        if not row or row["status"] not in ("completed", "partial", "skipped"):
            continue
        set_job_state(row["id"], "queued", reason=reason,
                      progress=0, processed=0, total=0,
                      error_code=None, error_message=None,
                      started_at=None, finished_at=None, duration_ms=None)
        reset.append(s)
    if reset:
        events.emit("job.invalidated", research_id=research_id,
                    payload={"stage": stage, "reset": reset, "reason": reason})
        try:
            from .. import journal
            journal.record(level="info", kind="workflow", action="workflow.recompute",
                           message=f"Пересчёт этапов после изменения «{stage}»: {', '.join(reset)}",
                           source="workflow", research_id=research_id,
                           detail={"stage": stage, "reset": reset, "reason": reason})
        except Exception:
            pass
    return reset


def _summary(result: dict) -> dict:
    return {k: v for k, v in result.items() if isinstance(v, (int, float, str, bool)) and len(str(v)) < 200}


def status(research_id: str) -> dict:
    jobs = db.query("SELECT * FROM workflow_jobs WHERE research_id=? ORDER BY created_at", (research_id,))
    return {"research_id": research_id,
            "jobs": [db.dec(j, "depends_on", "result") for j in jobs],
            "running": research_id in _RUNNING and _RUNNING[research_id].is_alive()}
