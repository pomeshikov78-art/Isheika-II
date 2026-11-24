"""Загрузка реестров в БД (ТЗ-06 §14.3 seed-данные).

Идемпотентно: повторный запуск не создаёт дублей. Каталог источников и реестр
коннекторов связываются по имени источника, но остаются разными сущностями.
"""
from __future__ import annotations

import json
import os
from typing import Any

from ..config import SEED_DIR
from ..contracts import iso_now, new_id
from ..storage import db

_CACHE: dict[str, Any] = {}


def _load(name: str) -> dict:
    if name in _CACHE:
        return _CACHE[name]
    with open(os.path.join(SEED_DIR, name + ".json"), encoding="utf-8") as f:
        data = json.load(f)
    _CACHE[name] = data
    return data


def methodology() -> dict:
    return _load("methodology")


def agents_seed() -> dict:
    return _load("agents")


def connectors_seed() -> dict:
    return _load("connectors")


def providers_seed() -> dict:
    return _load("providers")


def sources_seed() -> dict:
    return _load("sources")


def countries_seed() -> dict:
    return _load("countries")


def _norm(s: str) -> str:
    import re
    s = re.sub(r"\(.*?\)", " ", (s or "").lower())
    s = re.sub(r"[^a-zа-я0-9]+", " ", s)
    return " ".join(s.split())


def seed_all(force: bool = False) -> dict:
    now = iso_now()
    stats = {"countries": 0, "sources": 0, "connectors": 0, "providers": 0, "models": 0,
             "agents": 0, "stoplist": 0, "statuses": 0}

    # --- справочник стран
    for c in countries_seed()["items"]:
        db.upsert("dict_countries", {
            "code": c["iso2"], "name_ru": c["name_ru"], "region": c["region"],
            "patent_office": c["patent_office"], "languages": c["languages"],
            "is_enabled": 1, "profile": {"coverage": c["coverage"]}, "updated_at": now,
        }, key="code")
        stats["countries"] += 1

    # --- каталог источников
    existing = {r["code"]: r for r in db.query("SELECT code, integration_status, connector_code, health, last_verified_at, last_success_at, last_http_status FROM registry_sources")}
    for s in sources_seed()["items"]:
        prev = existing.get(s["source_code"], {})
        db.upsert("registry_sources", {
            "id": prev.get("id") or new_id("src-"),
            "code": s["source_code"], "name": s["name"], "category": s["category"],
            "category_name": s["category_name"], "country_code": s["country_iso2"],
            "scope": s["scope"], "api_type": s["api_type"], "access_class": s["access_class"],
            "access_reason": s["access_reason"], "auth_type": s["auth_type"],
            "endpoints": s["endpoints"], "official_url": ("https://" + s["endpoints"][0]) if s["endpoints"] and not s["endpoints"][0].startswith("http") else (s["endpoints"][0] if s["endpoints"] else None),
            "purpose": s["purpose"], "limits": s["limits"],
            "evidence_marker": s["evidence_marker"], "marker_reason": s["marker_reason"],
            "integration_status": prev.get("integration_status") or s["integration_status"],
            "connector_code": prev.get("connector_code"),
            "priority": s["priority"], "response_format": s["response_format"],
            "registry_section": s["registry_section"],
            "last_verified_at": prev.get("last_verified_at") or s["verified_at"],
            "last_success_at": prev.get("last_success_at"),
            "last_http_status": prev.get("last_http_status"),
            "health": prev.get("health") or {},
            "metadata": {"registry_part": s["registry_part"], "notes": s["notes"]},
            "created_at": now, "updated_at": now,
        }, key="code")
        stats["sources"] += 1

    # --- реестр коннекторов + привязка к каталогу
    by_name = {}
    for r in db.query("SELECT code, name FROM registry_sources"):
        by_name.setdefault(_norm(r["name"]), r["code"])
    for c in connectors_seed()["items"]:
        src_code = by_name.get(_norm(c["source_name"]))
        if not src_code:
            # источник отсутствует в каталоге — добавляем запись каталога со статусом CANDIDATE
            src_code = "SRC-X-" + c["code"]
            db.upsert("registry_sources", {
                "id": new_id("src-"), "code": src_code, "name": c["source_name"],
                "category": "C01", "category_name": "Научные публикации", "country_code": c.get("country_code"),
                "scope": "national" if c.get("country_code") else "international",
                "api_type": c["protocol"], "access_class": "A1" if c.get("requires_key") else "A0",
                "access_reason": "задано реестром коннекторов", "auth_type": c["auth_type"],
                "endpoints": [c["base_url"]] if c.get("base_url") else [],
                "official_url": c.get("base_url"), "purpose": c["name"], "limits": c.get("limits", {}),
                "evidence_marker": c.get("verified_marker", "Д"), "marker_reason": "реестр коннекторов",
                "integration_status": "CANDIDATE", "connector_code": c["code"], "priority": c.get("priority", "P2"),
                "response_format": "JSON", "registry_section": "Реестр коннекторов",
                "last_verified_at": None, "health": {}, "metadata": {}, "created_at": now, "updated_at": now,
            }, key="code")
            stats["sources"] += 1
        db.upsert("registry_connectors", {
            "code": c["code"], "name": c["name"], "source_code": src_code,
            "protocol": c["protocol"], "base_url": c.get("base_url"), "auth_type": c["auth_type"],
            "secret_ref": c.get("secret_ref"), "capabilities": c.get("capabilities", {}),
            "limits": c.get("limits", {}), "quota_policy": c.get("quota_policy", {}),
            "enabled": 1 if c.get("enabled", True) else 0,
            "requires_key": 1 if c.get("requires_key") else 0, "paid": 1 if c.get("paid") else 0,
            "health_status": "unverified", "docs_url": c.get("docs_url"), "tos_url": c.get("tos_url"),
            "fallback_code": c.get("fallback_code"), "verified_marker": c.get("verified_marker", "Д"),
            "tos_url": c.get("tos_url") or c.get("api_terms_url"),
            "implementation": c.get("implementation", "stub"),
            "robots_policy": c.get("robots_policy", "respect"), "notes": c.get("notes"),
            "created_at": now,
        }, key="code")
        db.update("registry_sources", "code", src_code, {"connector_code": c["code"], "updated_at": now})
        stats["connectors"] += 1

    # --- провайдеры и модели
    for p in providers_seed()["items"]:
        row = db.one("SELECT id FROM ai_providers WHERE id=?", (p["id"],))
        db.upsert("ai_providers", {
            "id": p["id"], "name": p["name"], "family": p["family"], "endpoint": p.get("endpoint"),
            "docs_url": p.get("docs_url"), "auth_method": p["auth_method"], "adapter": p["adapter"],
            "privacy_policy": p.get("privacy_policy", {}), "region_limits": p.get("region_limits"),
            "pricing": p.get("pricing", {}), "paid": 1 if p.get("paid") else 0,
            "enabled": 1 if p.get("enabled", True) else 0,
            "status": "active" if p["id"] == "simulation" else "unavailable",
            "secret_ref": p.get("secret_ref"), "metadata": {"notes": p.get("notes")},
            "created_at": now,
        }, key="id")
        stats["providers"] += 1
        for m in p.get("models", []):
            db.upsert("ai_models", {
                "id": f'{p["id"]}::{m["model_id"]}', "provider_id": p["id"], "model_id": m["model_id"],
                "display_name": m.get("display_name"), "capabilities": m.get("capabilities", {}),
                "context_window": m.get("context_window"), "languages": m.get("capabilities", {}).get("languages", []),
                "free_tier": 1 if m.get("free_tier") else 0, "paid": 1 if m.get("paid") else 0,
                "quota": m.get("quota", {}), "quality_scores": {},
                "enabled": 1, "status": "active" if p["id"] == "simulation" else "unavailable",
                "verified_at": None,
            }, key="id")
            stats["models"] += 1

    # --- агенты
    for a in agents_seed()["items"]:
        db.upsert("ai_agents", {
            "code": a["code"], "name": a["name"], "purpose": a["purpose"],
            "task_classes": a["task_classes"], "prompt_version": agents_seed()["prompt_version"],
            "response_schema": a["response_schema"], "enabled": 1,
        }, key="code")
        stats["agents"] += 1

    # --- стоп-лист
    for s in _load("stoplist")["items"]:
        db.upsert("registry_stoplist", {**s, "created_at": now}, key="code")
        stats["stoplist"] += 1

    # --- «кладбище API» и критические изменения
    ch = _load("registry_changelog")
    for g in ch["graveyard"]:
        db.upsert("registry_changelog", {"id": "grave-" + _norm(g["name"])[:40], "kind": "graveyard",
                                        "subject": g["name"], "payload": g, "created_at": now}, key="id")
    for c in ch["critical_changes"]:
        db.upsert("registry_changelog", {"id": c["id"], "kind": "critical_change", "subject": c["subject"],
                                        "payload": c, "created_at": now}, key="id")

    # --- единый словарь статусов
    from .. import contracts as C
    from ..states import FSMS, terminal_states
    domains = {"research": C.RESEARCH_STATES, "task": C.TASK_STATES, "ai_request": C.AI_REQUEST_STATES,
               "extraction_status": C.EXTRACTION_STATUSES, "deduplication_status": C.DEDUP_STATUSES,
               "report": C.REPORT_STATES, "provider": C.PROVIDER_STATES,
               "integration": C.INTEGRATION_STATES, "claim_type": C.CLAIM_TYPES,
               "evidence_status": C.EVIDENCE_STATUSES, "relevance_class": C.RELEVANCE_CLASSES,
               "relevance_decision": C.RELEVANCE_DECISIONS, "document_relation": C.DOCUMENT_RELATIONS,
               "origin_class": C.ORIGIN_CLASSES, "display_mode": C.DISPLAY_MODES,
               "uncertainty_class": C.UNCERTAINTY_CLASSES, "methodology_approval": C.METHODOLOGY_APPROVAL,
               "access_class": C.ACCESS_CLASSES, "marker": C.MARKERS, "privacy_class": C.PRIVACY_CLASSES}
    for domain, codes in domains.items():
        term = terminal_states(domain) if domain in FSMS else set()
        for code in codes:
            db.upsert("dict_statuses", {"domain": domain, "code": code, "title_ru": code,
                                        "is_terminal": 1 if code in term else 0}, key=("domain","code"))
            stats["statuses"] += 1

    # --- реестр методик и справочник критериев TRL (ИД-08, ИД-09)
    from ..analytics import methodologies as M
    stats["methodologies"] = M.bootstrap()

    _seed_users_projects(now)
    return stats


def _seed_users_projects(now: str) -> None:
    users = [
        ("admin", "Администратор", "admin"),
        ("lead", "Руководитель исследования", "research_lead"),
        ("analyst", "Аналитик НТР", "analyst"),
        ("expert", "Эксперт", "expert"),
        ("observer", "Наблюдатель / заказчик", "observer"),
        ("auditor", "Аудитор качества", "auditor"),
    ]
    import hashlib
    for login, name, role in users:
        if not db.one("SELECT id FROM core_users WHERE login=?", (login,)):
            db.insert("core_users", {"id": new_id("usr-"), "login": login, "display_name": name,
                                     "role": role,
                                     "password_hash": hashlib.sha256(("dev:" + login).encode()).hexdigest(),
                                     "is_active": 1, "created_at": now})
    if not db.one("SELECT id FROM core_projects WHERE code=?", ("DEMO",)):
        owner = db.one("SELECT id FROM core_users WHERE login='lead'")
        db.insert("core_projects", {"id": new_id("prj-"), "code": "DEMO", "name": "Демонстрационный проект НТР",
                                    "description": "Открытые научно-технические исследования (профиль DEV)",
                                    "owner_user_id": owner["id"], "classification": "open",
                                    "status": "active", "settings": {}, "created_at": now, "updated_at": now})


def default_project() -> dict:
    return db.one("SELECT * FROM core_projects WHERE code='DEMO'")


def reload_cache() -> None:
    _CACHE.clear()
