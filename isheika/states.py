"""Конечные автоматы состояний (ТЗ-05 §9, ТЗ-06 §8).

Каждый переход проверяется и журналируется. История переходов неизменяема:
при fallback создаётся новая попытка с новым request_id, но тем же task_id.
"""
from __future__ import annotations

from .contracts import CoreError

RESEARCH_FSM = {
    "draft": {"queued", "cancelled"},
    "queued": {"running", "cancelled", "failed"},
    "running": {"partial", "completed", "failed", "cancelled", "paused"},
    "partial": {"queued", "running", "completed", "failed", "cancelled", "paused"},
    "paused": {"running", "cancelled"},
    "completed": {"queued", "running"},   # повторный запуск = новая версия расчёта
    "failed": {"queued", "running"},
    "cancelled": {"queued"},
}

TASK_FSM = {
    "queued": {"running", "cancelled", "skipped"},
    "running": {"completed", "partial", "failed", "cancelled", "retry_wait"},
    "retry_wait": {"running", "failed", "cancelled"},
    "partial": {"queued", "running", "completed", "failed", "cancelled"},
    "completed": {"running", "queued"},
    "failed": {"queued", "running"},
    "cancelled": {"queued"},
    "skipped": {"queued"},
}

AI_FSM = {
    "created": {"validated", "policy_blocked", "cancelled"},
    "validated": {"routed", "policy_blocked", "cancelled"},
    "routed": {"quota_checked", "policy_blocked", "provider_error", "cancelled"},
    "quota_checked": {"submitted", "policy_blocked", "retry_wait", "cancelled"},
    "submitted": {"waiting_response", "provider_error", "cancelled"},
    "waiting_response": {"response_received", "provider_error", "retry_wait", "cancelled"},
    "response_received": {"validating", "schema_error"},
    "validating": {"completed", "schema_error"},
    "schema_error": {"fallback_pending", "cancelled", "submitted"},
    "retry_wait": {"submitted", "fallback_pending", "provider_error", "cancelled"},
    "provider_error": {"retry_wait", "fallback_pending", "cancelled"},
    "fallback_pending": {"routed", "cancelled", "provider_error"},
    "policy_blocked": {"cancelled", "routed"},
    "completed": set(),
    "cancelled": set(),
}

# ИД-06 (v1.1): два независимых автомата вместо одного смешанного.
# EXTRACTION_FSM — обработка содержимого; DEDUP_FSM — дедупликация/кластеризация.
# Класс релевантности (DIRECT/ADJACENT/BELOW_THRESHOLD) хранится в search_results
# и НЕ является состоянием документа.
EXTRACTION_FSM = {
    "DISCOVERED": {"FETCHED", "FAILED", "UNSUPPORTED"},
    "FETCHED": {"EXTRACTED", "FAILED", "UNSUPPORTED"},
    "EXTRACTED": {"NORMALIZED", "FAILED"},
    "NORMALIZED": {"EXTRACTED", "FETCHED"},      # повторная обработка новой версии
    "FAILED": {"DISCOVERED", "FETCHED", "UNSUPPORTED"},
    "UNSUPPORTED": {"FETCHED", "EXTRACTED"},
}

DEDUP_FSM = {
    "PENDING": {"UNIQUE", "DUPLICATE", "CLUSTERED", "REVIEW"},
    "UNIQUE": {"DUPLICATE", "CLUSTERED", "REVIEW"},
    "DUPLICATE": {"UNIQUE", "CLUSTERED", "REVIEW"},
    "CLUSTERED": {"UNIQUE", "DUPLICATE", "REVIEW"},
    "REVIEW": {"UNIQUE", "DUPLICATE", "CLUSTERED"},
}

DOCUMENT_FSM = EXTRACTION_FSM                  # совместимость ключа "document"

REPORT_FSM = {
    "requested": {"preparing", "cancelled"},
    "preparing": {"generating", "failed", "cancelled"},
    "generating": {"validating", "failed", "cancelled"},
    "validating": {"ready", "failed"},
    "ready": {"preparing"},
    "failed": {"preparing"},
    "cancelled": {"preparing"},
}

# Интеграционный статус источника в реестре (ТЗ-01 §3.3)
SOURCE_FSM = {
    "CANDIDATE": {"TESTED", "RESTRICTED", "UNAVAILABLE", "DISABLED"},
    "TESTED": {"CONNECTED", "RESTRICTED", "UNAVAILABLE", "DISABLED", "CANDIDATE"},
    "CONNECTED": {"TESTED", "RESTRICTED", "UNAVAILABLE", "DISABLED"},
    "RESTRICTED": {"TESTED", "CONNECTED", "UNAVAILABLE", "DISABLED"},
    "UNAVAILABLE": {"CANDIDATE", "TESTED", "CONNECTED", "RESTRICTED", "DISABLED"},
    "DISABLED": {"CANDIDATE", "TESTED"},
}

# Состояние провайдера ИИ (ТЗ-02 §5). Здоровье — событийная величина:
# переход возможен между любыми операционными состояниями, но выход из
# disabled/policy_blocked требует явного действия администратора.
PROVIDER_FSM = {
    "active": {"degraded", "quota_exhausted", "rate_limited", "auth_error", "unavailable",
               "disabled", "paid_blocked", "policy_blocked"},
    "degraded": {"active", "quota_exhausted", "rate_limited", "auth_error", "unavailable",
                 "disabled", "paid_blocked", "policy_blocked"},
    "quota_exhausted": {"active", "degraded", "rate_limited", "unavailable", "disabled"},
    "rate_limited": {"active", "degraded", "quota_exhausted", "unavailable", "disabled"},
    "auth_error": {"active", "degraded", "unavailable", "disabled"},
    "unavailable": {"active", "degraded", "auth_error", "disabled"},
    "disabled": {"active", "degraded", "unavailable", "auth_error"},
    "paid_blocked": {"active", "disabled", "policy_blocked"},
    "policy_blocked": {"active", "disabled", "paid_blocked"},
}

FSMS = {"research": RESEARCH_FSM, "task": TASK_FSM, "ai_request": AI_FSM,
        "document": DOCUMENT_FSM, "extraction": EXTRACTION_FSM, "deduplication": DEDUP_FSM,
        "report": REPORT_FSM, "source": SOURCE_FSM, "provider": PROVIDER_FSM}


def can_transition(kind: str, src: str, dst: str) -> bool:
    fsm = FSMS.get(kind)
    if fsm is None:
        raise CoreError("E_VALIDATION", f"Неизвестный автомат: {kind}")
    if src == dst:
        return True
    return dst in fsm.get(src, set())


def assert_transition(kind: str, src: str, dst: str) -> None:
    if not can_transition(kind, src, dst):
        raise CoreError("E_STATE", f"{kind}: {src} -> {dst} недопустим",
                        stage="state_machine", kind=kind, from_state=src, to_state=dst)


def terminal_states(kind: str) -> set[str]:
    return {s for s, nxt in FSMS[kind].items() if not nxt}
