"""Единый каталог API — OpenAPI 3.1 (ИД-04, ИД-12 ведомости v1.1).

Спецификация строится из фактически зарегистрированных маршрутов, поэтому
расхождение «есть в API — нет в каталоге» невозможно. Канонические ресурсы
используют множественное число и дефисные составные имена.
"""
from __future__ import annotations

from ..config import SETTINGS

CANONICAL = [
    "/api/v1/researches", "/api/v1/search-tasks", "/api/v1/search-results", "/api/v1/documents",
    "/api/v1/technologies", "/api/v1/evidence", "/api/v1/claims", "/api/v1/trl-assessments",
    "/api/v1/feasibility-assessments", "/api/v1/forecasts", "/api/v1/ai-tasks", "/api/v1/reports",
    "/api/v1/events", "/api/v1/methodologies", "/api/v1/confidence-assessments",
    "/api/v1/document-clusters", "/api/v1/document-relations", "/api/v1/independence-groups",
    "/api/v1/research-runs",
]

TAGS = {
    "researches": "Исследования", "search-tasks": "Поисковые задания", "search-results": "Результаты поиска",
    "documents": "Документы", "technologies": "Технологии", "evidence": "Доказательства",
    "claims": "Утверждения", "trl-assessments": "Оценки TRL", "feasibility-assessments": "Оценки реализуемости",
    "confidence-assessments": "Уверенность", "forecasts": "Прогнозы", "ai-tasks": "Задания ИИ",
    "reports": "Отчёты", "events": "События", "methodologies": "Методики",
    "document-clusters": "Кластеры документов", "document-relations": "Связи документов",
    "independence-groups": "Независимость доказательств", "research-runs": "Запуски и воспроизводимость",
}

ERROR_SCHEMA = {
    "type": "object",
    "required": ["error"],
    "properties": {"error": {
        "type": "object",
        "required": ["code", "message", "request_id", "timestamp", "retryable"],
        "properties": {
            "code": {"type": "string", "description": "Машинный код ошибки (E_*)"},
            "message": {"type": "string"},
            "details": {"type": "object"},
            "request_id": {"type": "string", "format": "uuid"},
            "task_id": {"type": ["string", "null"]},
            "timestamp": {"type": "string", "format": "date-time"},
            "retryable": {"type": "boolean"},
        }}},
}

SCHEMAS = {
    "Error": ERROR_SCHEMA,
    "SearchResult": {
        "type": "object",
        "description": "ИД-01/ИД-06/ИД-07: оценка соответствия запросу отделена от статуса обработки",
        "required": ["id", "document_id", "relevance_score", "relevance_class", "decision", "methodology_version"],
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "research_id": {"type": "string", "format": "uuid"},
            "document_id": {"type": "string", "format": "uuid"},
            "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
            "relevance_class": {"type": "string", "enum": ["DIRECT", "ADJACENT", "BELOW_THRESHOLD"]},
            "decision": {"type": "string", "enum": ["INCLUDE", "EXCLUDE", "MANUAL_INCLUDE", "MANUAL_EXCLUDE"]},
            "score_s": {"type": ["number", "null"]}, "score_t": {"type": ["number", "null"]},
            "score_c": {"type": ["number", "null"]}, "score_e": {"type": ["number", "null"]},
            "score_k": {"type": ["number", "null"]}, "score_f": {"type": ["number", "null"]},
            "reason_codes": {"type": "array", "items": {"type": "string"}},
            "methodology_id": {"type": ["string", "null"], "format": "uuid"},
            "methodology_version": {"type": "string"},
            "created_at": {"type": "string", "format": "date-time"},
        }},
    "Document": {
        "type": "object",
        "description": "ИД-03: логический документ; вхождения хранятся отдельно",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "logical_key": {"type": "string"},
            "blob_id": {"type": ["string", "null"]},
            "cluster_id": {"type": ["string", "null"]},
            "extraction_status": {"type": "string",
                                  "enum": ["DISCOVERED", "FETCHED", "EXTRACTED", "NORMALIZED", "FAILED", "UNSUPPORTED"]},
            "deduplication_status": {"type": "string",
                                     "enum": ["PENDING", "UNIQUE", "DUPLICATE", "CLUSTERED", "REVIEW"]},
            "occurrence_count": {"type": "integer"},
            "relevance_class": {"type": ["string", "null"]},
        }},
    "FeasibilityAssessment": {
        "type": "object",
        "description": "ИД-02: F допускается NULL; покрытие C — независимый показатель",
        "properties": {
            "score": {"type": ["number", "null"], "minimum": 0, "maximum": 100},
            "coverage": {"type": "number", "minimum": 0, "maximum": 1},
            "interpretation_allowed": {"type": "boolean"},
            "coverage_warning": {"type": ["string", "null"]},
            "unknown_factors": {"type": "array", "items": {"type": "string"}},
            "methodology_id": {"type": ["string", "null"]},
        }},
    "ForecastPoint": {
        "type": "object",
        "description": "ИД-05: внутренняя точность и политика представления разделены",
        "properties": {
            "forecast_horizon_years": {"type": "integer"},
            "probability_value": {"type": ["number", "null"], "description": "внутреннее значение, NUMERIC(7,6)"},
            "probability_lower": {"type": ["number", "null"]},
            "probability_upper": {"type": ["number", "null"]},
            "display_mode": {"type": "string", "enum": ["EXACT", "INTERVAL", "COARSE", "SCENARIO"]},
            "display_precision": {"type": "integer", "description": "-1 = точечное значение не выводится"},
            "display_text": {"type": "string"},
            "uncertainty_class": {"type": "string"},
            "warning_text": {"type": ["string", "null"]},
        }},
    "Methodology": {
        "type": "object",
        "description": "ИД-09: версионируемая методика",
        "properties": {
            "id": {"type": "string"}, "code": {"type": "string"}, "version": {"type": "string"},
            "approval_status": {"type": "string", "enum": ["PROVISIONAL", "VALIDATED", "DEPRECATED"]},
            "parameters": {"type": "object"}, "thresholds": {"type": "object"},
            "config_checksum": {"type": "string"},
        }},
    "ConfidenceAssessment": {
        "type": "object",
        "description": "ИД-10: уверенность ≠ F и ≠ P(T≤t)",
        "properties": {
            "subject_kind": {"type": "string", "enum": ["trl", "feasibility", "forecast", "claim"]},
            "confidence": {"type": ["number", "null"], "minimum": 0, "maximum": 1},
            "independent_groups": {"type": "integer"},
            "limitations": {"type": "array", "items": {"type": "string"}},
        }},
}

RESOURCE_SCHEMA = {
    "search-results": "SearchResult", "documents": "Document",
    "feasibility-assessments": "FeasibilityAssessment", "forecasts": "ForecastPoint",
    "methodologies": "Methodology", "confidence-assessments": "ConfidenceAssessment",
}


def _path_template(pattern: str) -> str:
    """Регулярное выражение маршрута → шаблон OpenAPI."""
    import re
    names = {
        r"/api/v1/researches/([^/]+)": "/api/v1/researches/{research_id}",
        r"/api/v1/documents/([^/]+)": "/api/v1/documents/{document_id}",
        r"/api/v1/methodologies/([^/]+)": "/api/v1/methodologies/{code}",
        r"/api/v1/technologies/([^/]+)/passport": "/api/v1/technologies/{technology_id}/passport",
        r"/api/v1/analytics/([^/]+)": "/api/v1/analytics/{research_id}",
        r"/api/v1/forecasts/([^/]+)": "/api/v1/forecasts/{research_id}",
        r"/api/v1/reports/([^/]+)": "/api/v1/reports/{report_id}",
    }
    if pattern in names:
        return names[pattern]
    return re.sub(r"\(\[\^/\]\+\)", "{id}", pattern)


def build_spec(routes: list) -> dict:
    paths: dict[str, dict] = {}
    for method, pat, fn in routes:
        pattern = pat.pattern[1:-1] if pat.pattern.startswith("^") else pat.pattern
        tpl = _path_template(pattern)
        resource = tpl.split("/")[3] if len(tpl.split("/")) > 3 else "system"
        params = [{"name": n, "in": "path", "required": True, "schema": {"type": "string"}}
                  for n in __import__("re").findall(r"\{(\w+)\}", tpl)]
        if method == "GET" and "{" not in tpl:
            params += [
                {"name": "research_id", "in": "query", "required": False, "schema": {"type": "string"}},
                {"name": "limit", "in": "query", "required": False,
                 "schema": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50}},
                {"name": "cursor", "in": "query", "required": False, "schema": {"type": "string"},
                 "description": "Курсор пагинации (идентификатор последней записи)"},
                {"name": "offset", "in": "query", "required": False, "schema": {"type": "integer"}},
                {"name": "sort", "in": "query", "required": False, "schema": {"type": "string"}},
            ]
        schema_ref = RESOURCE_SCHEMA.get(resource)
        ok_schema = {"type": "object", "properties": {
            "items": {"type": "array", "items": {"$ref": f"#/components/schemas/{schema_ref}"}}}} if schema_ref \
            else {"type": "object"}
        op = {
            "tags": [TAGS.get(resource, resource)],
            "summary": (fn.__doc__ or "").strip().split("\n")[0] or f"{method} {tpl}",
            "operationId": f"{method.lower()}_{fn.__name__}",
            "parameters": params,
            "responses": {
                "200": {"description": "Успех", "content": {"application/json": {"schema": ok_schema}}},
                "401": {"description": "Требуется аутентификация",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                "403": {"description": "Недостаточно прав",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                "410": {"description": "Маршрут выведен из эксплуатации (ИД-04)",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                "422": {"description": "Нарушение схемы",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
            },
        }
        if method in ("POST", "DELETE"):
            op["requestBody"] = {"required": False, "content": {"application/json": {"schema": {"type": "object"}}}}
            op["parameters"].append({"name": "Idempotency-Key", "in": "header", "required": False,
                                     "schema": {"type": "string"}})
        paths.setdefault(tpl, {})[method.lower()] = op
    return {
        "openapi": "3.1.0",
        "info": {"title": "ИЩЕЙКА НТР AI — API", "version": "1.1.0",
                 "description": "Единый каталог маршрутов (ИД-04). Идентификаторы — UUID, "
                                "даты — ISO 8601 с часовым поясом, ответы — JSON UTF-8, "
                                "ошибки — единый формат, пагинация — limit/cursor."},
        "servers": [{"url": "/"}],
        "paths": paths,
        "components": {"schemas": SCHEMAS,
                       "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}},
        "security": [{"bearer": []}],
        "x-canonical-resources": CANONICAL,
        "x-legacy-policy": {"sunset": SETTINGS.api_legacy_sunset,
                            "compat_enabled": SETTINGS.api_legacy_compat,
                            "behavior": "410 Gone с указанием нового пути"},
    }


def missing_canonical(routes: list) -> list[str]:
    """Контроль API-01: все канонические ресурсы зарегистрированы."""
    spec = build_spec(routes)
    present = set(spec["paths"])
    return [p for p in CANONICAL if p not in present]
