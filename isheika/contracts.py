"""Единый словарь статусов и контракты обмена (ТЗ-05 §7, ТЗ-06 §8).

ТЗ-06 §21 (замечание 2): статусы централизованы здесь, строковые коды в БД
обязаны принадлежать этим перечислениям. Три уровня состояний не смешиваются.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

# ------------------------------------------------------------------ статусы

RESEARCH_STATES = ("draft", "queued", "running", "partial", "paused", "completed", "failed", "cancelled")
TASK_STATES = ("queued", "running", "partial", "completed", "failed", "cancelled", "retry_wait", "skipped")
AI_REQUEST_STATES = ("created", "validated", "routed", "quota_checked", "submitted", "waiting_response",
                     "response_received", "retry_wait", "provider_error", "policy_blocked",
                     "fallback_pending", "validating", "completed", "schema_error", "cancelled")
# ИД-06 (v1.1): жизненный цикл обработки содержимого ОТДЕЛЁН от оценки
# тематического соответствия. Классы релевантности не являются статусами документа.
EXTRACTION_STATUSES = ("DISCOVERED", "FETCHED", "EXTRACTED", "NORMALIZED", "FAILED", "UNSUPPORTED")
DEDUP_STATUSES = ("PENDING", "UNIQUE", "DUPLICATE", "CLUSTERED", "REVIEW")
DOCUMENT_STATES = EXTRACTION_STATUSES          # совместимость имени; значения — только обработка
REPORT_STATES = ("requested", "preparing", "generating", "validating", "ready", "failed", "cancelled")

PROVIDER_STATES = ("active", "degraded", "quota_exhausted", "rate_limited", "auth_error",
                   "unavailable", "disabled", "paid_blocked", "policy_blocked")
INTEGRATION_STATES = ("CONNECTED", "TESTED", "CANDIDATE", "RESTRICTED", "UNAVAILABLE", "DISABLED")

CLAIM_TYPES = ("FACT", "ANALYSIS", "HYPOTHESIS", "FORECAST")
EVIDENCE_STATUSES = ("SUPPORTED", "PARTIAL", "CONTRADICTED", "UNVERIFIED", "SUPERSEDED")
EVIDENCE_CLASSES = ("primary_peer_reviewed", "primary_report", "patent", "standard", "official_register",
                    "dataset", "preprint", "press_release", "media", "forum", "encyclopedia", "unknown")
PRIVACY_CLASSES = ("public", "internal", "restricted")
# ИД-07 (v1.1): три нормативных машинных кода. Буквенные A/B/C запрещены в API и БД.
RELEVANCE_CLASSES = ("DIRECT", "ADJACENT", "BELOW_THRESHOLD")
RELEVANCE_LABELS_RU = {"DIRECT": "Прямое соответствие", "ADJACENT": "Смежная тема",
                       "BELOW_THRESHOLD": "Ниже порога"}
RELEVANCE_DECISIONS = ("INCLUDE", "EXCLUDE", "MANUAL_INCLUDE", "MANUAL_EXCLUDE")
# ИД-03 (v1.1): типы связей между логическими документами
DOCUMENT_RELATIONS = ("EXACT_DUPLICATE", "ALTERNATIVE_HOSTING", "PREPRINT_OF", "PUBLISHED_VERSION_OF",
                      "REVISION_OF", "TRANSLATION_OF", "SUMMARY_OF", "CITES")
# ИД-11 (v1.1): происхождение доказательства и независимость подтверждений
ORIGIN_CLASSES = ("PRIMARY", "INDEPENDENT_CONFIRMATION", "REPRINT", "SUMMARY", "DERIVATIVE", "CONTRADICTORY")
# ИД-05 (v1.1): серверная политика представления прогнозов
DISPLAY_MODES = ("EXACT", "INTERVAL", "COARSE", "SCENARIO")
UNCERTAINTY_CLASSES = ("LOW", "MODERATE", "HIGH", "VERY_HIGH", "SCENARIO_ONLY")
# ИД-09 (v1.1): статус утверждения методики
METHODOLOGY_APPROVAL = ("PROVISIONAL", "VALIDATED", "DEPRECATED")
METHODOLOGY_CODES = ("RELEVANCE_V1", "FEASIBILITY_V1", "TRL_CRITERIA_V1", "FORECAST_V1",
                     "SOURCE_QUALITY_V1", "EVIDENCE_QUALITY_V1")
ACCESS_CLASSES = ("A0", "A1", "A2", "A3", "A4", "UNKNOWN")
MARKERS = ("П", "Р", "Д")

# ------------------------------------------------------------------ ошибки

ERROR_CODES = {
    "E_AUTH": "Требуется аутентификация",
    "E_FORBIDDEN": "Недостаточно прав (RBAC)",
    "E_NOT_FOUND": "Объект не найден",
    "E_VALIDATION": "Нарушение схемы входных данных",
    "E_STATE": "Недопустимый переход состояния",
    "E_QUOTA": "Квота источника или провайдера исчерпана",
    "E_RATE_LIMIT": "Ограничение частоты запросов",
    "E_PROVIDER": "Ошибка провайдера",
    "E_SCHEMA": "Ответ не соответствует JSON Schema",
    "E_POLICY": "Заблокировано политикой (приватность/платный маршрут/стоп-лист)",
    "E_NETWORK": "Сетевая ошибка или недоступность источника",
    "E_ROBOTS": "Запрещено robots.txt или ToS источника",
    "E_TIMEOUT": "Превышено время ожидания",
    "E_INTERNAL": "Внутренняя ошибка",
    "E_CANCELLED": "Отменено",
    "E_NO_DATA": "Данные не получены",
    "E_GONE": "Маршрут выведен из эксплуатации, используйте канонический путь (ИД-04)",
}


def new_id(prefix: str = "") -> str:
    u = str(uuid.uuid4())
    return f"{prefix}{u}" if prefix else u


def now_ms() -> int:
    return int(time.time() * 1000)


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------------------------ оболочки

@dataclass
class Envelope:
    """Унифицированная оболочка сообщения (ТЗ-05 §7.1)."""
    message_id: str = field(default_factory=lambda: new_id("msg-"))
    correlation_id: str | None = None
    request_id: str | None = None
    research_id: str | None = None
    task_id: str | None = None
    producer: str = "core"
    schema_version: str = "1.0"
    ts: str = field(default_factory=iso_now)
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ApiError:
    code: str
    message: str
    stage: str | None = None
    task_id: str | None = None
    request_id: str | None = None
    details: dict = field(default_factory=dict)
    retryable: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["description"] = ERROR_CODES.get(self.code, "")
        return d


class CoreError(Exception):
    def __init__(self, code: str, message: str = "", *, stage: str | None = None,
                 retryable: bool = False, **details: Any):
        self.error = ApiError(code, message or ERROR_CODES.get(code, code), stage=stage,
                              details=details, retryable=retryable)
        super().__init__(f"{code}: {self.error.message}")


@dataclass
class AIRequest:
    """ТЗ-02 §3 / ТЗ-06 §6.3."""
    request_id: str
    task_id: str
    agent_id: str
    provider_id: str | None
    model_id: str | None
    prompt: str
    context_refs: list[str] = field(default_factory=list)
    response_schema: dict | None = None
    timeout_s: float = 60.0
    privacy_class: str = "public"
    budget_policy: dict = field(default_factory=lambda: {"allow_paid": False, "max_cost_usd": 0.0})
    retry_policy: dict = field(default_factory=lambda: {"max_attempts": 3, "backoff_s": 2.0})
    research_id: str | None = None
    prompt_version: str = "P-1.0.0"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AIResponse:
    """Фактические значения приходят от провайдера; выдуманные токены запрещены."""
    request_id: str
    status: str
    content: str = ""
    structured_result: dict | None = None
    citations: list[dict] = field(default_factory=list)
    usage: dict | None = None            # None => неизвестно, не 0
    latency_ms: int | None = None
    estimated_cost: float | None = None
    finish_reason: str | None = None
    error_code: str | None = None
    timestamp: str = field(default_factory=iso_now)
    provider_id: str | None = None
    model_id: str | None = None
    simulated: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Document:
    """Контракт документа (ТЗ-05 §7.3, ТЗ-06 §6.3.6)."""
    document_id: str
    source_code: str
    connector_code: str | None
    external_id: str | None
    title: str
    url: str
    doc_type: str = "unknown"
    authors: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    country_iso2: str | None = None
    language: str | None = None
    published_at: str | None = None
    accessed_at: str = field(default_factory=iso_now)
    abstract: str = ""
    text_excerpt: str = ""
    license: str | None = None
    oa_status: str | None = None
    doi: str | None = None
    identifiers: dict = field(default_factory=dict)
    raw_ref: str | None = None
    content_hash: str | None = None
    state: str = "discovered"
    relevance: dict | None = None
    evidence_class: str = "unknown"
    independence_group: str | None = None
    marker: str = "Д"

    def to_dict(self) -> dict:
        return asdict(self)
