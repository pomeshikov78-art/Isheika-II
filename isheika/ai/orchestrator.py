"""AI Orchestrator (ТЗ-02 §5, ТЗ-05 §8).

Реализует алгоритм Free-First (§8.6), формальное ранжирование моделей (§8.5),
резервирование и повторы (§8.7–8.8), контроль стоимости и квот (§8.10),
валидацию JSON Schema с единственной попыткой исправления (§3 ТЗ-02).
Каждая попытка — новая запись ai_requests с новым request_id и тем же task_id.
"""
from __future__ import annotations

import hashlib
import json
import time

from ..config import SETTINGS
from ..contracts import (AIRequest, AIResponse, CoreError, iso_now, new_id)
from ..states import assert_transition
from ..storage import db
from ..storage.secrets import SecretStore
from ..workflow import events
from . import safety
from .adapters import build_adapter, extract_json

TASK_CLASS_PROFILE = {
    "query_expansion": {"langs": ["ru", "en"], "json": True, "quality_weight": 0.3},
    "technical_translation": {"langs": ["ru", "en"], "json": False, "quality_weight": 0.6},
    "science_analysis": {"langs": ["ru", "en"], "json": True, "quality_weight": 0.5},
    "patent_analysis": {"langs": ["en"], "json": True, "quality_weight": 0.5},
    "industry_analysis": {"langs": ["ru", "en"], "json": True, "quality_weight": 0.4},
    "country_analysis": {"langs": ["ru"], "json": True, "quality_weight": 0.3},
    "tech_analysis": {"langs": ["ru", "en"], "json": True, "quality_weight": 0.6},
    "trl_signals": {"langs": ["en"], "json": True, "quality_weight": 0.6},
    "feasibility_signals": {"langs": ["ru", "en"], "json": True, "quality_weight": 0.6},
    "alternatives": {"langs": ["en"], "json": True, "quality_weight": 0.4},
    "forecast_assumptions": {"langs": ["ru"], "json": True, "quality_weight": 0.5},
    "critique": {"langs": ["ru", "en"], "json": True, "quality_weight": 0.7},
    "arbitration": {"langs": ["ru", "en"], "json": True, "quality_weight": 0.7},
    "synthesis": {"langs": ["ru"], "json": True, "quality_weight": 0.5},
}


def _provider_rows() -> list[dict]:
    rows = db.query("SELECT * FROM ai_providers")
    return [db.dec(r, "privacy_policy", "pricing", "metadata") for r in rows]


def _model_rows() -> list[dict]:
    rows = db.query("SELECT * FROM ai_models")
    return [db.dec(r, "capabilities", "quota", "quality_scores", "languages") for r in rows]


def candidates(task_class: str, privacy_class: str = "public") -> dict:
    """Шаги 1–5 алгоритма Free-First: фильтрация и разделение кандидатов."""
    prof = TASK_CLASS_PROFILE.get(task_class, {"langs": ["ru", "en"], "json": True, "quality_weight": 0.5})
    providers = {p["id"]: p for p in _provider_rows()}
    free, local, paid, rejected = [], [], [], []
    for m in _model_rows():
        p = providers.get(m["provider_id"])
        if not p:
            continue
        reasons = []
        if not p["enabled"] or not m["enabled"]:
            reasons.append("отключён администратором")
        if p["status"] in ("auth_error", "unavailable", "disabled") and p["id"] != "simulation":
            has_key = bool(p.get("secret_ref") and SecretStore.has(p["secret_ref"]))
            if not has_key:
                reasons.append("ключ не задан / провайдер не проверен")
        try:
            safety.check_privacy(privacy_class, p, allow_external=SETTINGS.allow_external_ai)
        except CoreError as e:
            reasons.append(e.error.message)
        caps = m.get("capabilities") or {}
        if prof["json"] and caps.get("json_schema") is False:
            reasons.append("нет поддержки структурированного ответа (мягкое ограничение)")
        langs = m.get("languages") or caps.get("languages") or []
        lang_ok = (not langs) or any(l in langs for l in prof["langs"])
        entry = {"model": m, "provider": p, "reasons": reasons, "lang_ok": lang_ok,
                 "hard_reject": any("ключ" in r or "отключён" in r or "класс" in r or "запрещена" in r for r in reasons)}
        if entry["hard_reject"]:
            rejected.append(entry)
            continue
        if p["family"] == "local" or p["id"] == "simulation":
            local.append(entry)
        elif m["paid"] or p["paid"]:
            paid.append(entry)
        else:
            free.append(entry)
    return {"free": free, "local": local, "paid": paid, "rejected": rejected, "profile": prof}


def quality_score(entry: dict, task_class: str) -> dict:
    """Q(m,t). Самооценка модели не используется. Подтверждённое качество —
    только из результатов контрольных задач (quality_scores)."""
    m = entry["model"]
    prof = entry["profile"] if "profile" in entry else TASK_CLASS_PROFILE.get(task_class, {})
    qs = m.get("quality_scores") or {}
    verified = qs.get(task_class)
    q_quality = verified if isinstance(verified, (int, float)) else 0.5
    caps = m.get("capabilities") or {}
    q_lang = 1.0 if entry["lang_ok"] else 0.4
    q_json = 1.0 if caps.get("json_schema") else 0.7
    ctx = m.get("context_window")
    q_ctx = 0.7 if not ctx else min(1.0, ctx / 32000)
    q_avail = 1.0 if m.get("status") == "active" else 0.6
    qw = prof.get("quality_weight", 0.5)
    total = qw * q_quality + 0.2 * q_lang + 0.15 * q_json + 0.1 * q_ctx + 0.15 * q_avail
    return {"total": round(total, 4), "quality": q_quality,
            "quality_verified": isinstance(verified, (int, float)),
            "language": q_lang, "json": q_json, "context": q_ctx, "availability": q_avail,
            "note": "" if isinstance(verified, (int, float)) else "качество на контрольных задачах не подтверждено"}


def rank(entries: list[dict], task_class: str) -> list[dict]:
    out = []
    for e in entries:
        e = dict(e)
        e["score"] = quality_score(e, task_class)
        out.append(e)
    out.sort(key=lambda e: -e["score"]["total"])
    return out


def select_route(task_class: str, privacy_class: str = "public", *, allow_paid: bool | None = None) -> dict:
    """Шаги 6–9 Free-First. Платный маршрут — только при явном разрешении."""
    allow_paid = SETTINGS.allow_paid_ai if allow_paid is None else allow_paid
    c = candidates(task_class, privacy_class)
    free = rank(c["free"], task_class)
    local = rank(c["local"], task_class)
    paid = rank(c["paid"], task_class)
    if free:
        return {"entry": free[0], "group": "free", "alternatives": free[1:] + local,
                "reason": "Бесплатная доступная модель с наилучшей пригодностью"}
    if local:
        return {"entry": local[0], "group": "local", "alternatives": local[1:],
                "reason": "Локальная/имитационная модель (free-first, данные не покидают сервер)"}
    if paid and allow_paid:
        return {"entry": paid[0], "group": "paid", "alternatives": paid[1:],
                "reason": "Платный маршрут разрешён пользователем"}
    if paid:
        raise CoreError("E_POLICY", "Доступны только платные модели. Платные вызовы отключены по умолчанию — "
                                    "требуется явное согласие и бюджет.",
                        stage="routing", candidates=[e["model"]["id"] for e in paid[:5]])
    raise CoreError("E_POLICY", "Нет доступных моделей: не заданы ключи и не запущены локальные модели. "
                                "В DEV-профиле используется детерминированный экстрактор.",
                    stage="routing", rejected=[{"model": e["model"]["id"], "reasons": e["reasons"]} for e in c["rejected"][:8]])


def _set_request_state(request_id: str, state: str, **fields) -> None:
    r = db.one("SELECT state FROM ai_requests WHERE id=?", (request_id,))
    if r and r["state"] != state:
        assert_transition("ai_request", r["state"], state)
    db.update("ai_requests", "id", request_id, {"state": state, **fields})


def execute(research_id: str, agent_code: str, task_class: str, payload: dict, *,
            mode: str = "independent", privacy_class: str = "public",
            force_provider: str | None = None, force_model: str | None = None) -> dict:
    """Полный цикл задания ИИ с маршрутизацией, повторами и валидацией схемы."""
    agent = db.one("SELECT * FROM ai_agents WHERE code=?", (agent_code,))
    if not agent:
        raise CoreError("E_NOT_FOUND", f"Агент {agent_code} не зарегистрирован")
    agent = db.dec(agent, "response_schema", "task_classes")
    schema = agent["response_schema"]

    task_id = new_id("ait-")
    db.insert("ai_tasks", {"id": task_id, "research_id": research_id, "agent_code": agent_code,
                           "task_class": task_class, "status": "running",
                           "input_refs": [d.get("id") for d in (payload.get("documents") or [])][:50],
                           "payload": {"documents": len(payload.get("documents") or [])},
                           "mode": mode, "created_at": iso_now()})
    events.emit("ai.request_created", research_id=research_id,
                payload={"task_id": task_id, "agent": agent_code, "task_class": task_class, "mode": mode})

    prompt = _build_prompt(agent, payload, schema)
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

    tried: set[str] = set()
    attempt = 0
    last_error: dict | None = None
    max_attempts = 3
    while attempt < max_attempts:
        attempt += 1
        try:
            route = select_route(task_class, privacy_class)
        except CoreError as e:
            db.update("ai_tasks", "id", task_id, {"status": "failed", "finished_at": iso_now()})
            events.emit("ai.policy_blocked", research_id=research_id, severity="warning",
                        payload={"task_id": task_id, "agent": agent_code, **e.error.to_dict()})
            return {"ok": False, "task_id": task_id, "agent": agent_code, "error": e.error.to_dict(),
                    "structured": None, "simulated": False}
        entry = route["entry"]
        if force_provider:
            forced = [e for e in (route["alternatives"] + [entry])
                      if e["provider"]["id"] == force_provider and (not force_model or e["model"]["model_id"] == force_model)]
            if forced:
                entry = forced[0]
        model, provider = entry["model"], entry["provider"]
        key = f'{provider["id"]}::{model["model_id"]}'
        if key in tried and route["alternatives"]:
            alt = next((e for e in route["alternatives"]
                        if f'{e["provider"]["id"]}::{e["model"]["model_id"]}' not in tried), None)
            if alt:
                entry, model, provider = alt, alt["model"], alt["provider"]
                key = f'{provider["id"]}::{model["model_id"]}'
        tried.add(key)

        request_id = new_id("air-")
        db.insert("ai_requests", {
            "id": request_id, "task_id": task_id, "research_id": research_id, "attempt_no": attempt,
            "provider_id": provider["id"], "model_id": model["model_id"], "agent_code": agent_code,
            "state": "created", "privacy_class": privacy_class, "prompt_version": agent["prompt_version"],
            "prompt_hash": prompt_hash, "simulated": 1 if provider["id"] == "simulation" else 0,
            "route_reason": route["reason"], "created_at": iso_now()})
        _set_request_state(request_id, "validated")
        _set_request_state(request_id, "routed", route_reason=json.dumps(
            {"group": route["group"], "score": entry["score"], "reason": route["reason"]}, ensure_ascii=False))
        events.emit("ai.routed", research_id=research_id,
                    payload={"request_id": request_id, "agent": agent_code, "provider": provider["id"],
                             "model": model["model_id"], "group": route["group"],
                             "score": entry["score"], "attempt": attempt})
        _set_request_state(request_id, "quota_checked")
        _set_request_state(request_id, "submitted")
        _set_request_state(request_id, "waiting_response")

        req = AIRequest(request_id=request_id, task_id=task_id, agent_id=agent_code,
                        provider_id=provider["id"], model_id=model["model_id"], prompt=prompt,
                        context_refs=[d.get("id") for d in (payload.get("documents") or [])][:50],
                        response_schema=schema, timeout_s=60.0, privacy_class=privacy_class,
                        budget_policy={"allow_paid": SETTINGS.allow_paid_ai, "max_cost_usd": 0.0},
                        research_id=research_id, prompt_version=agent["prompt_version"])
        try:
            adapter = build_adapter(provider)
            resp: AIResponse = adapter.complete(req, model["model_id"])
        except CoreError as e:
            _set_request_state(request_id, "provider_error", error_code=e.error.code,
                               error_message=e.error.message, finished_at=iso_now())
            last_error = e.error.to_dict()
            events.emit("ai.fallback" if attempt < max_attempts else "ai.policy_blocked",
                        research_id=research_id, severity="warning",
                        payload={"request_id": request_id, "provider": provider["id"], **e.error.to_dict()})
            db.execute("UPDATE ai_providers SET status=?, last_error=?, last_checked_at=? WHERE id=?",
                       ("auth_error" if e.error.code == "E_AUTH" else
                        "rate_limited" if e.error.code == "E_RATE_LIMIT" else "degraded",
                        e.error.message[:300], iso_now(), provider["id"]))
            if e.error.code == "E_RATE_LIMIT":
                time.sleep(min(10.0, 2.0 ** attempt))
            _set_request_state(request_id, "fallback_pending")
            continue

        _set_request_state(request_id, "response_received",
                           usage=resp.usage, latency_ms=resp.latency_ms,
                           estimated_cost=resp.estimated_cost)
        _set_request_state(request_id, "validating")
        structured = resp.structured_result or extract_json(resp.content)
        errors = safety.validate_schema(structured, schema) if structured is not None else ["ответ не содержит JSON"]
        if errors and structured is not None:
            # единственная попытка исправления: отбрасываем лишние поля, приводим типы
            structured = _repair(structured, schema)
            errors = safety.validate_schema(structured, schema)
        if errors:
            _set_request_state(request_id, "schema_error", error_code="E_SCHEMA",
                               error_message="; ".join(errors)[:500], finished_at=iso_now())
            events.emit("ai.schema_error", research_id=research_id, severity="warning",
                        payload={"request_id": request_id, "errors": errors[:6]})
            last_error = {"code": "E_SCHEMA", "message": "; ".join(errors)[:300]}
            if attempt < max_attempts:
                _set_request_state(request_id, "fallback_pending")
                continue
            db.update("ai_tasks", "id", task_id, {"status": "failed", "finished_at": iso_now()})
            return {"ok": False, "task_id": task_id, "agent": agent_code, "error": last_error,
                    "structured": None, "simulated": resp.simulated}

        check = safety.validate_model_output(structured)
        db.insert("ai_results", {"id": new_id("aires-"), "request_id": request_id, "task_id": task_id,
                                 "research_id": research_id, "agent_code": agent_code,
                                 "content": resp.content[:20000], "structured_result": structured,
                                 "citations": resp.citations, "schema_valid": 1, "created_at": iso_now()})
        _set_request_state(request_id, "completed", finished_at=iso_now())
        db.update("ai_tasks", "id", task_id, {"status": "completed", "finished_at": iso_now()})
        db.execute("UPDATE ai_providers SET status='active', last_checked_at=?, last_error=NULL WHERE id=?",
                   (iso_now(), provider["id"]))
        db.execute("UPDATE ai_models SET status='active' WHERE id=?", (model["id"],))
        events.emit("ai.response", research_id=research_id,
                    payload={"request_id": request_id, "agent": agent_code, "provider": provider["id"],
                             "model": model["model_id"], "usage": resp.usage, "latency_ms": resp.latency_ms,
                             "simulated": resp.simulated, "injection_issues": check["injection_issues"]})
        return {"ok": True, "task_id": task_id, "request_id": request_id, "agent": agent_code,
                "structured": structured, "provider": provider["id"], "model": model["model_id"],
                "simulated": resp.simulated, "usage": resp.usage, "latency_ms": resp.latency_ms,
                "route": route["reason"], "safety": check}

    db.update("ai_tasks", "id", task_id, {"status": "failed", "finished_at": iso_now()})
    return {"ok": False, "task_id": task_id, "agent": agent_code, "error": last_error,
            "structured": None, "simulated": False}


def _build_prompt(agent: dict, payload: dict, schema: dict) -> str:
    docs = payload.get("documents") or []
    block = safety.wrap_documents(docs)
    brief = {k: v for k, v in payload.items() if k != "documents"}
    return (f'Агент: {agent["code"]} {agent["name"]}\nНазначение: {agent["purpose"]}\n'
            f'Схема ответа (JSON Schema): {json.dumps(schema, ensure_ascii=False)}\n'
            f'{block}\n'
            f'===PAYLOAD===\n{json.dumps({**brief, "documents": docs}, ensure_ascii=False)}')


def _repair(data: dict, schema: dict) -> dict:
    """Ограниченная попытка исправления формата (ТЗ-02 §3)."""
    if not isinstance(data, dict):
        return data
    props = schema.get("properties", {})
    out = {}
    for k, v in data.items():
        if k not in props:
            if k.startswith("_"):
                out[k] = v
            continue
        spec = props[k]
        t = spec.get("type")
        if t == "array" and not isinstance(v, list):
            v = [v]
        if t == "object" and not isinstance(v, dict):
            continue
        if t == "string" and not isinstance(v, str):
            v = str(v)
        if t in ("number", "integer") and isinstance(v, str):
            try:
                v = float(v) if t == "number" else int(float(v))
            except Exception:
                continue
        if t == "array" and isinstance(v, list) and "items" in spec:
            v = [_repair(i, spec["items"]) if isinstance(i, dict) else i for i in v]
        out[k] = v
    return out


def provider_status_overview() -> list[dict]:
    out = []
    for p in _provider_rows():
        models = [m for m in _model_rows() if m["provider_id"] == p["id"]]
        has_key = bool(p.get("secret_ref") and SecretStore.has(p["secret_ref"]))
        out.append({
            "id": p["id"], "name": p["name"], "family": p["family"], "adapter": p["adapter"],
            "status": p["status"], "enabled": bool(p["enabled"]), "paid": bool(p["paid"]),
            "key_configured": has_key, "endpoint": p["endpoint"], "docs_url": p["docs_url"],
            "privacy": p["privacy_policy"], "last_checked_at": p["last_checked_at"],
            "last_error": p["last_error"],
            "models": [{"id": m["model_id"], "display_name": m["display_name"],
                        "status": m["status"], "free_tier": bool(m["free_tier"]),
                        "paid": bool(m["paid"]), "quota": m["quota"],
                        "quality_verified": bool((m.get("quality_scores") or {}))} for m in models],
            "quota_display": "неизвестно" if not any(m.get("quota") for m in models) else "см. модели",
        })
    return out
