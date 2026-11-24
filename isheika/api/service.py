"""Сервисный слой (ТЗ-06 §7). Используется REST-обработчиками и инструментами.

Здесь сосредоточены проверки RBAC, валидация входов, идемпотентность и
регистрация результата в аудите. Транспорт (stdlib HTTP или FastAPI) от
предметной логики отделён.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets as pysecrets
import time
from typing import Any

from ..config import SETTINGS
from .. import telemetry
from ..contracts import CoreError, iso_now, new_id
from ..storage import db
from ..storage.secrets import SecretStore, mask
from ..registry import loader
from ..states import FSMS
from ..workflow import engine as W, events
from ..search import expansion as EX, manager as SM, query_parser as QP
from ..analytics import evidence as E, feasibility as F, passport as P, quality as Q, trends as TR, trl as T
from ..analytics import barriers as B, alternatives as ALT, forecast as FC
from ..analytics import confidence as CF, methodologies as M, snapshot as SNAP
from ..search import dedup as DD
from ..ai import orchestrator as O
from ..reports import builder as RB

# ------------------------------------------------------------------ RBAC
ROLE_RIGHTS = {
    "admin": {"*"},
    "research_lead": {"research.read", "research.write", "research.run", "report.write", "registry.read",
                      "registry.write", "ai.read", "ai.run", "analytics.read", "analytics.write",
                      "evidence.write", "settings.read", "logs.read", "keys.write", "quality.write"},
    "analyst": {"research.read", "research.write", "research.run", "report.write", "registry.read",
                "ai.read", "ai.run", "analytics.read", "analytics.write", "evidence.write",
                "settings.read", "logs.read", "quality.write"},
    "expert": {"research.read", "analytics.read", "evidence.write", "quality.write", "registry.read", "logs.read"},
    "observer": {"research.read", "analytics.read", "registry.read"},
    "auditor": {"research.read", "analytics.read", "registry.read", "logs.read", "settings.read"},
}

_SESSIONS: dict[str, dict] = {}


def login(login_name: str, password: str) -> dict:
    u = db.one("SELECT * FROM core_users WHERE login=? AND is_active=1", (login_name,))
    if not u:
        raise CoreError("E_AUTH", "Пользователь не найден")
    expect = hashlib.sha256(password.encode()).hexdigest()
    if u["password_hash"] != expect:
        raise CoreError("E_AUTH", "Неверные учётные данные")
    token = pysecrets.token_urlsafe(24)
    _SESSIONS[token] = {"user_id": u["id"], "login": u["login"], "role": u["role"],
                        "display_name": u["display_name"], "created": time.time()}
    audit(u["login"], "auth.login", "user", u["id"])
    return {"token": token, "user": {"id": u["id"], "login": u["login"], "role": u["role"],
                                     "display_name": u["display_name"],
                                     "rights": sorted(ROLE_RIGHTS.get(u["role"], set()))}}


def session(token: str | None) -> dict:
    if not token:
        raise CoreError("E_AUTH", "Требуется аутентификация")
    s = _SESSIONS.get(token)
    if not s:
        raise CoreError("E_AUTH", "Сессия недействительна")
    if time.time() - s["created"] > 12 * 3600:
        _SESSIONS.pop(token, None)
        raise CoreError("E_AUTH", "Сессия истекла")
    return s


def require(sess: dict, right: str) -> None:
    rights = ROLE_RIGHTS.get(sess["role"], set())
    if "*" in rights or right in rights:
        return
    raise CoreError("E_FORBIDDEN", f'Роль «{sess["role"]}» не имеет права «{right}»')


def audit(actor: str, action: str, kind: str | None = None, entity_id: str | None = None,
          research_id: str | None = None, payload: dict | None = None,
          http_status: int | None = None, duration_ms: int | None = None) -> None:
    try:
        db.insert("audit_log", {"id": new_id("aud-"), "actor": actor, "action": action,
                                "entity_kind": kind, "entity_id": entity_id, "research_id": research_id,
                                "request_id": telemetry.request_id(),
                                "correlation_id": telemetry.correlation_id(),
                                "http_status": http_status, "duration_ms": duration_ms,
                                "payload": payload or {}, "created_at": iso_now()})
    except Exception:
        pass
    # Журнал действий (ред. 1.4.0): то же действие в сквозном журнале — с исходом,
    # длительностью и подписью дефекта, чтобы отказ искался фильтром, а не глазами.
    try:
        from .. import journal
        failed = bool(http_status and http_status >= 400) or (payload or {}).get("outcome") == "fail"
        journal.record("warn" if failed else "info", "action", action,
                       message=str((payload or {}).get("message") or ""),
                       actor=actor, research_id=research_id, entity_kind=kind, entity_id=entity_id,
                       http_status=http_status, duration_ms=duration_ms,
                       outcome="fail" if failed else "ok", detail=payload or {})
    except Exception:
        pass


# ------------------------------------------------------------------ исследования
def create_research(body: dict, *, actor: str = "system") -> dict:
    title = (body.get("title") or body.get("query") or "").strip()
    query_text = (body.get("query") or title).strip()
    if not query_text:
        raise CoreError("E_VALIDATION", "Не задан поисковый запрос")
    project = loader.default_project()
    countries = body.get("countries")
    if countries == "all" or countries is None:
        countries = [c["code"] for c in db.query("SELECT code FROM dict_countries WHERE is_enabled=1 ORDER BY name_ru")]
    if not isinstance(countries, list):
        raise CoreError("E_VALIDATION", "countries должен быть списком ISO-кодов или 'all'")
    unknown = [c for c in countries if not db.one("SELECT code FROM dict_countries WHERE code=?", (c,))]
    if unknown:
        raise CoreError("E_VALIDATION", f"Неизвестные коды стран: {unknown}")
    languages = body.get("languages") or ["ru", "en"]
    horizon = int(body.get("forecast_horizon_years") or 50)
    if not 0 <= horizon <= 50:
        raise CoreError("E_VALIDATION", "Горизонт прогнозирования должен быть 0–50 лет")
    rid = new_id("res-")
    settings = body.get("settings") or {}
    db.insert("core_researches", {
        "id": rid, "project_id": project["id"], "title": title[:500],
        "research_type": body.get("research_type") or "technology", "status": "draft",
        "owner_user_id": None, "goal": body.get("goal"),
        "period_from": body.get("period_from"), "period_to": body.get("period_to"),
        "forecast_horizon_years": horizon, "language_codes": languages, "country_codes": countries,
        "settings": settings, "methodology_version": SETTINGS.methodology_version,
        "version_no": 1, "created_at": iso_now(), "updated_at": iso_now()})
    db.insert("search_queries", {"id": new_id("qry-"), "research_id": rid, "raw_text": query_text,
                                 "parsed": {}, "expansions": {}, "branches": [], "exclusions": [],
                                 "query_version": 1, "created_at": iso_now()})
    db.insert("search_profiles", {"id": new_id("prf-"), "research_id": rid, "country_codes": countries,
                                  "source_codes": settings.get("source_codes") or [],
                                  "categories": settings.get("categories") or [],
                                  "languages": languages, "access_max": settings.get("access_max", "A1"),
                                  "settings": settings, "created_at": iso_now()})
    db.insert("core_state_history", {"id": new_id("st-"), "entity_kind": "research", "entity_id": rid,
                                     "from_state": None, "to_state": "draft", "reason": "Создано",
                                     "actor": actor, "created_at": iso_now()})
    W.create_workflow(rid)
    events.emit("research.created", research_id=rid, payload={"title": title, "countries": len(countries)})
    audit(actor, "research.create", "research", rid, rid, {"title": title})
    return get_research(rid)


def get_research(rid: str) -> dict:
    r = db.dec(db.one("SELECT * FROM core_researches WHERE id=?", (rid,)),
               "settings", "country_codes", "language_codes")
    if not r:
        raise CoreError("E_NOT_FOUND", "Исследование не найдено", research_id=rid)
    q = db.dec(db.one("SELECT * FROM search_queries WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (rid,)),
               "parsed", "expansions", "branches", "exclusions")
    r["query"] = q
    r["counts"] = {
        "documents": db.count("research_documents", "research_id=?", (rid,)),
        "direct": db.count("research_documents", "research_id=? AND relevance_class='DIRECT'", (rid,)),
        "adjacent": db.count("research_documents", "research_id=? AND relevance_class='ADJACENT'", (rid,)),
        "claims": db.count("knowledge_claims", "research_id=?", (rid,)),
        "evidence": db.count("evidence_items", "research_id=?", (rid,)),
    }
    trl = db.one("SELECT trl,confidence FROM analytics_trl WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (rid,))
    fea = db.one("SELECT score,coverage,interpretation FROM analytics_feasibility WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (rid,))
    r["trl"] = trl
    r["feasibility"] = fea
    return r


def list_researches(limit: int = 50, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM core_researches"
    params: list = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    out = []
    for r in db.query(sql, params):
        r = db.dec(r, "settings", "country_codes", "language_codes")
        r["counts"] = {"documents": db.count("research_documents", "research_id=?", (r["id"],)),
                       "direct": db.count("research_documents", "research_id=? AND relevance_class='DIRECT'", (r["id"],))}
        out.append(r)
    return out


def start_research(rid: str, *, resume: bool = False, actor: str = "system") -> dict:
    get_research(rid)
    res = W.start(rid, resume=resume)
    audit(actor, "research.start", "research", rid, rid, {"resume": resume})
    return res


def cancel_research(rid: str, *, actor: str = "system") -> dict:
    W.cancel(rid)
    audit(actor, "research.cancel", "research", rid, rid)
    return {"status": "cancelled", "research_id": rid}


def research_status(rid: str) -> dict:
    st = W.status(rid)
    st["research"] = get_research(rid)
    st["search_jobs"] = db.query("SELECT * FROM search_jobs WHERE research_id=? ORDER BY created_at", (rid,))
    return st


def update_query(rid: str, body: dict, *, actor: str = "system") -> dict:
    """Уточнение запроса (UI-03). Создаёт новую версию запроса."""
    get_research(rid)
    text = (body.get("query") or "").strip()
    if not text:
        raise CoreError("E_VALIDATION", "Пустой запрос")
    prev = db.one("SELECT query_version FROM search_queries WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (rid,))
    q = QP.parse(text)
    ex = EX.build(q, languages=body.get("languages") or ["ru", "en"])
    db.insert("search_queries", {"id": new_id("qry-"), "research_id": rid, "raw_text": text,
                                 "parsed": q.to_dict(), "expansions": ex.to_dict(),
                                 "branches": [b.to_dict() for b in ex.branches],
                                 "exclusions": body.get("exclusions") or ex.exclusions,
                                 "query_version": (prev["query_version"] + 1) if prev else 1,
                                 "created_at": iso_now()})
    audit(actor, "query.update", "research", rid, rid, {"query": text})
    return {"parsed": q.to_dict(), "expansion": ex.to_dict()}


def preview_query(body: dict) -> dict:
    q = QP.parse(body.get("query") or "")
    ex = EX.build(q, languages=body.get("languages") or ["ru", "en"])
    conns = SM.select_connectors({"categories": body.get("categories"),
                                  "access_max": body.get("access_max", "A1"),
                                  "include_simulation": SETTINGS.profile == "DEV"})
    return {"parsed": q.to_dict(), "expansion": ex.to_dict(),
            "expression": EX.primary_expression(ex, q),
            "connectors": [{"code": c["code"], "name": c["name"], "requires_key": bool(c["requires_key"]),
                            "source_code": c["source_code"]} for c in conns]}


# ------------------------------------------------------------------ документы
def list_documents(rid: str, *, cls: str | None = None, country: str | None = None,
                   doc_type: str | None = None, language: str | None = None,
                   min_score: float | None = None, q: str | None = None,
                   limit: int = 100, offset: int = 0, sort: str = "score") -> dict:
    sql = """SELECT d.*, d.relevance_score AS score, d.relevance_class AS rclass,
                    r.reason, r.components, r.reason_codes, r.methodology_version AS rel_methodology
             FROM research_documents d
             LEFT JOIN search_results r ON r.document_id=d.id AND r.research_id=d.research_id
                  AND r.id=(SELECT s2.id FROM search_results s2 WHERE s2.document_id=d.id
                            AND s2.research_id=d.research_id ORDER BY s2.created_at DESC, s2.rowid DESC LIMIT 1)
             WHERE d.research_id=?"""
    params: list = [rid]
    if cls:
        sql += " AND d.relevance_class=?"
        params.append(cls)
    if country:
        sql += " AND d.country_code=?"
        params.append(country)
    if doc_type:
        sql += " AND d.doc_type=?"
        params.append(doc_type)
    if language:
        sql += " AND d.language=?"
        params.append(language)
    if min_score is not None:
        sql += " AND d.relevance_score>=?"
        params.append(min_score)
    if q:
        sql += " AND (d.title LIKE ? OR d.abstract LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    total = db.one("SELECT COUNT(*) AS n FROM (" + sql + ")", params)["n"]
    order = {"score": "d.relevance_score DESC", "date": "d.published_at DESC",
             "title": "d.title ASC"}.get(sort, "d.relevance_score DESC")
    sql += f" ORDER BY {order} LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = [db.dec(r, "authors", "organizations", "identifiers", "components", "reason_codes")
            for r in db.query(sql, params)]
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


def get_document(did: str) -> dict:
    d = db.dec(db.one("SELECT * FROM content_documents WHERE id=?", (did,)),
               "authors", "organizations", "identifiers")
    if not d:
        raise CoreError("E_NOT_FOUND", "Документ не найден")
    d["occurrences"] = db.query("SELECT * FROM content_occurrences WHERE document_id=? ORDER BY accessed_at", (did,))
    d["relations"] = db.query("SELECT * FROM content_relations WHERE from_document_id=? OR to_document_id=?", (did, did))
    d["relevance_by_research"] = [db.dec(x, "components", "weights", "reason_codes", "gate") for x in
                                  db.query("SELECT * FROM search_results WHERE document_id=? ORDER BY created_at DESC", (did,))]
    d["relevance"] = db.dec(db.one("SELECT * FROM search_results WHERE document_id=? ORDER BY created_at DESC LIMIT 1", (did,)),
                            "components", "weights", "reason_codes", "gate")
    d["evidence"] = db.query("SELECT * FROM evidence_items WHERE document_id=?", (did,))
    d["claims"] = db.query("""SELECT c.* FROM knowledge_claims c JOIN knowledge_links l ON l.from_id=c.id
                              WHERE l.to_id=? AND l.from_kind='claim'""", (did,))
    return d


def exclude_document(did: str, reason: str = "", *, actor: str = "system",
                     research_id: str | None = None) -> dict:
    """Решение о включении хранится ОТДЕЛЬНО от класса релевантности (ИД-06).

    Аналитик может исключить документ с высоким R — класс при этом не меняется.
    """
    rows = db.query("SELECT * FROM search_results WHERE document_id=? ORDER BY created_at DESC", (did,))
    if research_id:
        rows = [r for r in rows if r["research_id"] == research_id]
    if not rows:
        occ = db.one("SELECT research_id FROM content_occurrences WHERE document_id=? LIMIT 1", (did,))
        if not occ:
            raise CoreError("E_NOT_FOUND", "Документ не найден")
        rid = research_id or occ["research_id"]
        rid_new = new_id("rel-")
        db.insert("search_results", {
            "id": rid_new, "research_id": rid, "document_id": did, "relevance_score": 0.0,
            "relevance_class": "BELOW_THRESHOLD", "decision": "MANUAL_EXCLUDE",
            "reason": reason or "Исключён аналитиком", "reason_codes": ["MANUAL_EXCLUDE"],
            "methodology_version": "manual", "created_at": iso_now()})
        audit(actor, "document.exclude", "document", did, rid, {"reason": reason})
        return {"document_id": did, "decision": "MANUAL_EXCLUDE", "research_id": rid}
    r = rows[0]
    db.update("search_results", "id", r["id"], {"decision": "MANUAL_EXCLUDE",
                                               "reason": (r["reason"] or "") + "; исключён аналитиком: " + reason})
    audit(actor, "document.exclude", "document", did, r["research_id"], {"reason": reason})
    return {"document_id": did, "decision": "MANUAL_EXCLUDE", "research_id": r["research_id"],
            "relevance_class": r["relevance_class"]}


def label_document(did: str, label: int, *, actor: str = "system",
                   research_id: str | None = None) -> dict:
    """Разметка относится к пара «документ × исследование» (документ глобальный)."""
    if research_id:
        d = db.one("SELECT research_id FROM research_documents WHERE id=? AND research_id=?", (did, research_id))
    else:
        d = db.one("SELECT research_id FROM research_documents WHERE id=?", (did,))
    if not d:
        raise CoreError("E_NOT_FOUND", "Документ не найден в указанном исследовании")
    Q.label_document(d["research_id"], did, label)
    audit(actor, "document.label", "document", did, d["research_id"], {"label": label})
    return {"document_id": did, "label": label, "research_id": d["research_id"]}


# ------------------------------------------------------------------ аналитика
def analytics_bundle(rid: str) -> dict:
    """Показатели возвращаются РАЗДЕЛЬНО (ИД-10/КИ-014): F, P(T≤t), уверенность."""
    return {"trl": T.latest(rid), "feasibility": F.latest(rid), "barriers": B.list_barriers(rid),
            "alternatives": ALT.list_alternatives(rid), "trends": TR.latest(rid),
            "forecast": FC.latest(rid), "quality": Q.latest(rid),
            "confidence": CF.latest(rid),
            "deduplication": DD.summary(rid),
            "independence_groups": E.independence_groups(rid),
            "methodologies": {m["family"]: {"code": m["code"], "version": m["version"],
                                            "approval_status": m["approval_status"],
                                            "config_checksum": m["config_checksum"]}
                              for m in M.listing() if m["is_active"]},
            "runs": SNAP.runs(rid),
            "coverage": SM.coverage_by_country(rid), "evidence_summary": E.summary(rid)}


def recompute(rid: str, *, weights: dict | None = None, actor: str = "system") -> dict:
    """Пересчёт создаёт НОВУЮ запись результата; история не переписывается (ИД-09).

    Если переданы новые веса — создаётся новая версия методики FEASIBILITY_V(n+1),
    предыдущие результаты остаются связанными со своей версией.
    """
    new_version = None
    if weights:
        cur = M.active("FEASIBILITY")
        factors = [dict(f) for f in cur["parameters"]["factors"]]
        for f in factors:
            if f["code"] in weights:
                f["weight"] = float(weights[f["code"]])
        new_version = M.create_version("FEASIBILITY", parameters={"factors": factors},
                                       author=actor, description="Переоценка весов факторов пользователем")
    t = T.compute(rid)
    f = F.compute(rid, methodology_id=(new_version or {}).get("id"))
    c = CF.compute_all(rid)
    P.build(rid)
    audit(actor, "analytics.recompute", "research", rid, rid,
          {"weights": weights, "methodology": (new_version or {}).get("code")})
    return {"trl": t, "feasibility": f, "confidence": c, "methodology_version": new_version,
            "note": "Создана новая запись расчёта; предыдущие результаты сохранены"}


# ------------------------------------------------------------------ методики (ИД-09)
def methodologies_list() -> list[dict]:
    return M.listing()


def methodology_get(code: str) -> dict:
    m = M.by_code(code) or M.active(code)
    if not m:
        raise CoreError("E_NOT_FOUND", f"Методика {code} не найдена")
    m["history"] = [{k: h[k] for k in ("code", "version", "approval_status", "is_active",
                                       "config_checksum", "created_at", "change_description")}
                    for h in M.history(code)]
    return m


def methodology_create_version(code: str, body: dict, *, actor: str = "system") -> dict:
    m = M.create_version(code, parameters=body.get("parameters"), thresholds=body.get("thresholds"),
                         formula=body.get("formula"), author=actor,
                         description=body.get("description", ""),
                         activate=bool(body.get("activate", True)),
                         approval_status=body.get("approval_status", "PROVISIONAL"))
    audit(actor, "methodology.version", "methodology", m["id"], None,
          {"code": m["code"], "checksum": m["config_checksum"]})
    events.emit("methodology.version_created", payload={"code": m["code"], "version": m["version"]})
    return m


def methodology_approve(methodology_id: str, status: str, *, actor: str = "system") -> dict:
    m = M.set_approval(methodology_id, status, actor)
    audit(actor, "methodology.approval", "methodology", methodology_id, None, {"status": status})
    return m


def trl_criteria() -> list[dict]:
    return T.criteria_catalog()


def trl_assessments(rid: str) -> dict:
    return {"latest": T.latest(rid), "history": T.history(rid),
            "criterion_evidence": T.criterion_evidence(T.latest(rid)["id"]) if T.latest(rid) else []}


def feasibility_assessments(rid: str) -> dict:
    return {"latest": F.latest(rid), "history": F.history(rid)}


def confidence_assessments(rid: str, subject: str | None = None) -> dict:
    return {"items": CF.latest(rid) if not subject else [CF.latest(rid, subject)],
            "note": "Уверенность отделена от F и P(T≤t) (ИД-10)"}


def forecast_points(rid: str) -> dict:
    fc = FC.latest(rid)
    if not fc:
        return {"items": [], "presentation_policy": M.active("FORECAST")["parameters"]["presentation_policy"]}
    return {"forecast_id": fc["id"], "items": fc.get("points") or [],
            "calibration_status": fc.get("calibration_status"),
            "presentation_policy": M.active("FORECAST")["parameters"]["presentation_policy"]}


# ------------------------------------------------------------------ дедупликация (ИД-03)
def dedup_summary(rid: str) -> dict:
    return DD.summary(rid)


def document_clusters(rid: str) -> list[dict]:
    return DD.clusters(rid)


def document_relations(rid: str) -> list[dict]:
    return db.query("""SELECT r.*, d1.title AS from_title, d2.title AS to_title
                       FROM content_relations r
                       JOIN content_documents d1 ON d1.id=r.from_document_id
                       JOIN content_documents d2 ON d2.id=r.to_document_id
                       JOIN content_occurrences o ON o.document_id=r.from_document_id
                       WHERE o.research_id=? GROUP BY r.id ORDER BY r.created_at DESC LIMIT 500""", (rid,))


def document_graph(rid: str, types: list[str] | None = None, limit: int = 300) -> dict:
    """Граф связей документов исследования (ROADMAP P4).

    Узлы — логические документы, рёбра — типизированные связи ИД-03.
    Фильтр типов применяется на сервере; браузер только отображает граф.
    """
    docs = db.query("""SELECT d.id, d.title, d.doc_type, d.evidence_class, d.cluster_id,
                              d.published_at, d.origin_class, r.relevance_class, r.relevance_score,
                              (SELECT COUNT(*) FROM content_occurrences o
                               WHERE o.document_id=d.id AND o.research_id=?) AS occurrences
                       FROM research_documents d
                       LEFT JOIN search_results r ON r.document_id=d.id AND r.research_id=d.research_id
                       WHERE d.research_id=? GROUP BY d.id
                       ORDER BY r.relevance_score DESC, d.created_at LIMIT ?""", (rid, rid, limit))
    ids = {d["id"] for d in docs}
    rels = [r for r in document_relations(rid)
            if r["from_document_id"] in ids and r["to_document_id"] in ids]
    counts: dict[str, int] = {}
    for r in rels:
        counts[r["relation_type"]] = counts.get(r["relation_type"], 0) + 1
    keep = set(types or [])
    edges = [{"source": r["from_document_id"], "target": r["to_document_id"],
              "type": r["relation_type"], "confidence": r["confidence"],
              "basis": r["basis"], "decided_by": r["decided_by"]}
             for r in rels if not keep or r["relation_type"] in keep]
    linked = {e["source"] for e in edges} | {e["target"] for e in edges}
    clusters = db.query("""SELECT DISTINCT d.cluster_id AS id FROM research_documents d
                           WHERE d.research_id=? AND d.cluster_id IS NOT NULL""", (rid,))
    return {"nodes": docs, "edges": edges,
            "types": [{"type": k, "count": v, "selected": (not keep or k in keep)}
                      for k, v in sorted(counts.items(), key=lambda x: -x[1])],
            "clusters": len(clusters), "isolated": len(ids - linked),
            "truncated": db.count("research_documents", "research_id=?", (rid,)) > limit,
            "note": "Связи версий и производных материалов (ИД-03); вхождения сохранены отдельно"}


# ------------------------------------------------------------------ сравнение версий расчётов (P4)
DIFF_FIELDS = {"trl": ("trl", "confidence"), "feasibility": ("score", "coverage", "range"),
               "forecast": ("calibration_status",), "confidence": ("confidence", "independent_groups")}


def assessment_diff(kind: str, a_id: str, b_id: str) -> dict:
    """Сравнение двух записей расчёта: значения, методика, набор документов, факторы/критерии.

    Исторические записи не изменяются (ИД-09/ИД-12); сравнение — только чтение.
    """
    if kind not in SNAP.ASSESSMENT_TABLES:
        raise CoreError("E_VALIDATION", f"Неизвестный вид расчёта: {kind}")
    a, b = SNAP.assessment(kind, a_id), SNAP.assessment(kind, b_id)
    if not a or not b:
        raise CoreError("E_NOT_FOUND", "Запись расчёта не найдена")
    if a["research_id"] != b["research_id"]:
        raise CoreError("E_VALIDATION", "Сравнивать можно расчёты одного исследования")
    deltas = []
    for f in DIFF_FIELDS.get(kind, ()):
        va, vb = a.get(f), b.get(f)
        d = {"field": f, "a": va, "b": vb, "changed": va != vb}
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            d["delta"] = round(vb - va, 6)
        deltas.append(d)
    factors = []
    if kind == "feasibility":
        fa = {f["code"]: f for f in (a.get("factors") or [])}
        fb = {f["code"]: f for f in (b.get("factors") or [])}
        for code in sorted(set(fa) | set(fb)):
            x, y = fa.get(code, {}), fb.get(code, {})
            factors.append({"code": code, "name": y.get("name") or x.get("name") or code,
                            "x_a": x.get("x"), "x_b": y.get("x"),
                            "weight_a": x.get("weight"), "weight_b": y.get("weight"),
                            "available_a": x.get("is_available"), "available_b": y.get("is_available"),
                            "changed": (x.get("x") != y.get("x")) or (x.get("weight") != y.get("weight"))
                                       or (x.get("is_available") != y.get("is_available"))})
    criteria = []
    if kind == "trl":
        ca = {c["criterion_code"]: c for c in (a.get("criteria") or [])}
        cb = {c["criterion_code"]: c for c in (b.get("criteria") or [])}
        for code in sorted(set(ca) | set(cb)):
            x, y = ca.get(code, {}), cb.get(code, {})
            if bool(x.get("confirmed")) != bool(y.get("confirmed")):
                criteria.append({"criterion_code": code, "level": y.get("level") or x.get("level"),
                                 "confirmed_a": bool(x.get("confirmed")), "confirmed_b": bool(y.get("confirmed")),
                                 "text": y.get("text") or x.get("text")})
    ma, mb = M.by_id(a.get("methodology_id")) or {}, M.by_id(b.get("methodology_id")) or {}
    return {"kind": kind, "research_id": a["research_id"],
            "a": {"id": a_id, "created_at": a.get("created_at"), "methodology_id": a.get("methodology_id"),
                  "methodology": (ma.get("code") or "") + " " + (ma.get("version") or ""),
                  "config_checksum": a.get("config_checksum"), "input_hash": a.get("input_hash"),
                  "output_hash": a.get("output_hash"), "document_set_version": a.get("document_set_version")},
            "b": {"id": b_id, "created_at": b.get("created_at"), "methodology_id": b.get("methodology_id"),
                  "methodology": (mb.get("code") or "") + " " + (mb.get("version") or ""),
                  "config_checksum": b.get("config_checksum"), "input_hash": b.get("input_hash"),
                  "output_hash": b.get("output_hash"), "document_set_version": b.get("document_set_version")},
            "deltas": deltas, "factors": factors, "criteria": criteria,
            "methodology_changed": a.get("methodology_id") != b.get("methodology_id"),
            "document_set_changed": a.get("document_set_version") != b.get("document_set_version"),
            "identical_result": a.get("output_hash") == b.get("output_hash"),
            "note": "Сравнение версий: значения и версии методик; исторические записи не переписываются"}


def confirm_cluster(rid: str, body: dict, *, actor: str = "system") -> dict:
    a, b = body.get("from_document_id"), body.get("to_document_id")
    rel = body.get("relation_type", "EXACT_DUPLICATE")
    if not a or not b:
        raise CoreError("E_VALIDATION", "Требуются from_document_id и to_document_id")
    res = DD.confirm_relation(a, b, rel, actor)
    audit(actor, "document.cluster_confirm", "document", a, rid, {"to": b, "relation": rel})
    return res


def search_results(rid: str, *, cls: str | None = None, limit: int = 100, offset: int = 0) -> dict:
    sql = "SELECT * FROM search_results WHERE research_id=?"
    params: list = [rid]
    if cls:
        sql += " AND relevance_class=?"
        params.append(cls.upper())
    total = db.one("SELECT COUNT(*) AS n FROM (" + sql + ")", params)["n"]
    sql += " ORDER BY relevance_score DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    items = [db.dec(r, "components", "weights", "gate", "reason_codes") for r in db.query(sql, params)]
    return {"total": total, "limit": limit, "offset": offset, "items": items}


def independence_groups(rid: str) -> list[dict]:
    return E.independence_groups(rid)


def runs(rid: str) -> list[dict]:
    return SNAP.runs(rid)


def replay(kind: str, assessment_id: str, *, actor: str = "system") -> dict:
    res = SNAP.replay(kind, assessment_id)
    audit(actor, "analytics.replay", kind, assessment_id, None, {"identical": res.get("identical")})
    return res


def passport(rid: str) -> dict:
    p = P.get(rid)
    if not p:
        p = P.build(rid)
    return p


def claims(rid: str, ctype: str | None = None, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM knowledge_claims WHERE research_id=?"
    params: list = [rid]
    if ctype:
        sql += " AND claim_type=?"
        params.append(ctype)
    if status:
        sql += " AND status=?"
        params.append(status)
    return db.query(sql + " ORDER BY created_at LIMIT 500", params)


def evidence_list(rid: str, claim_id: str | None = None) -> list[dict]:
    return E.evidence_for(rid, claim_id)


def add_evidence(rid: str, body: dict, *, actor: str = "system") -> dict:
    """Ручное добавление доказательства экспертом."""
    claim_id = body.get("claim_id")
    if not claim_id or not db.one("SELECT id FROM knowledge_claims WHERE id=? AND research_id=?", (claim_id, rid)):
        raise CoreError("E_VALIDATION", "claim_id не найден в этом исследовании")
    doc_id = body.get("document_id")
    if doc_id and not db.one("SELECT id FROM research_documents WHERE id=? AND research_id=?", (doc_id, rid)):
        raise CoreError("E_POLICY", "Запрещено связывать доказательство из другого исследования")
    eid = new_id("evd-")
    db.insert("evidence_items", {
        "id": eid, "claim_id": claim_id, "document_id": doc_id, "research_id": rid,
        "source_code": body.get("source_code"), "url": body.get("url"), "locator": body.get("locator"),
        "quote": body.get("quote"), "published_at": body.get("published_at"), "accessed_at": iso_now(),
        "evidence_class": body.get("evidence_class", "unknown"),
        "independence_group": body.get("independence_group"), "quality": body.get("quality"),
        "status": body.get("status", "UNVERIFIED"), "marker": body.get("marker", "Д"),
        "created_at": iso_now()})
    audit(actor, "evidence.add", "evidence", eid, rid, {"claim_id": claim_id})
    return {"evidence_id": eid}


# ------------------------------------------------------------------ реестры
def sources(category: str | None = None, country: str | None = None, access: str | None = None,
            status: str | None = None, marker: str | None = None, q: str | None = None,
            limit: int = 200, offset: int = 0) -> dict:
    sql = "SELECT * FROM registry_sources WHERE 1=1"
    params: list = []
    for cond, val in (("category", category), ("country_code", country), ("access_class", access),
                      ("integration_status", status), ("evidence_marker", marker)):
        if val:
            sql += f" AND {cond}=?"
            params.append(val)
    if q:
        sql += " AND (name LIKE ? OR purpose LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    total = db.one("SELECT COUNT(*) AS n FROM (" + sql + ")", params)["n"]
    rows = [db.dec(r, "endpoints", "limits", "health", "metadata")
            for r in db.query(sql + " ORDER BY category, name LIMIT ? OFFSET ?", params + [limit, offset])]
    return {"total": total, "items": rows, "limit": limit, "offset": offset}


def source_stats() -> dict:
    by_cat = db.query("SELECT category, category_name, COUNT(*) AS n FROM registry_sources GROUP BY category ORDER BY category")
    by_acc = db.query("SELECT access_class, COUNT(*) AS n FROM registry_sources GROUP BY access_class")
    by_status = db.query("SELECT integration_status, COUNT(*) AS n FROM registry_sources GROUP BY integration_status")
    by_marker = db.query("SELECT evidence_marker, COUNT(*) AS n FROM registry_sources GROUP BY evidence_marker")
    by_country = db.query("SELECT country_code, COUNT(*) AS n FROM registry_sources WHERE country_code IS NOT NULL GROUP BY country_code")
    return {"total": db.count("registry_sources"), "by_category": by_cat, "by_access": by_acc,
            "by_status": by_status, "by_marker": by_marker, "by_country": by_country,
            "categories": loader.sources_seed()["categories"]}


def connectors() -> list[dict]:
    out = []
    for r in db.query("SELECT * FROM registry_connectors ORDER BY code"):
        r = db.dec(r, "capabilities", "limits", "quota_policy")
        r["key_configured"] = bool(r.get("secret_ref") and SecretStore.has(r["secret_ref"]))
        out.append(r)
    return out


def connector_health(code: str | None = None, *, actor: str = "system") -> list[dict]:
    from ..search.connectors import build_connector
    rows = db.query("SELECT * FROM registry_connectors" + (" WHERE code=?" if code else ""), (code,) if code else ())
    out = []
    for r in rows:
        meta = db.dec(r, "capabilities", "limits", "quota_policy")
        conn = build_connector(meta)
        if conn is None:
            res = {"code": r["code"], "status": "not_implemented", "checked_at": iso_now()}
        else:
            res = conn.health_check()
        db.update("registry_connectors", "code", r["code"],
                  {"health_status": res["status"], "last_checked_at": iso_now(),
                   "last_error": res.get("reason")})
        if r["source_code"]:
            status = {"active": "CONNECTED", "degraded": "TESTED", "restricted": "RESTRICTED",
                      "error": "UNAVAILABLE", "unavailable": "UNAVAILABLE"}.get(res["status"], "CANDIDATE")
            db.execute("UPDATE registry_sources SET integration_status=?, last_verified_at=? WHERE code=?",
                       (status, iso_now(), r["source_code"]))
        out.append(res)
    audit(actor, "connector.health_check", "connector", code)
    return out


def countries() -> list[dict]:
    out = []
    for c in db.query("SELECT * FROM dict_countries ORDER BY name_ru"):
        c = db.dec(c, "languages", "profile")
        c["sources"] = db.count("registry_sources", "country_code=?", (c["code"],))
        out.append(c)
    return out


def toggle_country(code: str, enabled: bool, *, actor: str = "system") -> dict:
    db.update("dict_countries", "code", code, {"is_enabled": 1 if enabled else 0, "updated_at": iso_now()})
    audit(actor, "country.toggle", "country", code, payload={"enabled": enabled})
    return {"code": code, "enabled": enabled}


def registry_changelog() -> dict:
    rows = db.query("SELECT * FROM registry_changelog ORDER BY kind, id")
    return {"graveyard": [db.dec(r, "payload")["payload"] for r in rows if r["kind"] == "graveyard"],
            "critical_changes": [db.dec(r, "payload")["payload"] for r in rows if r["kind"] == "critical_change"],
            "stoplist": db.query("SELECT * FROM registry_stoplist ORDER BY code")}


# ------------------------------------------------------------------ ИИ
def ai_providers() -> list[dict]:
    return O.provider_status_overview()


def ai_agents() -> list[dict]:
    return [db.dec(r, "task_classes", "response_schema") for r in db.query("SELECT * FROM ai_agents ORDER BY code")]


def ai_tasks(rid: str) -> dict:
    tasks = db.query("SELECT * FROM ai_tasks WHERE research_id=? ORDER BY created_at", (rid,))
    reqs = db.query("SELECT * FROM ai_requests WHERE research_id=? ORDER BY created_at", (rid,))
    for r in reqs:
        r["route_reason"] = json.loads(r["route_reason"]) if r["route_reason"] and r["route_reason"].startswith("{") else r["route_reason"]
        r["usage"] = json.loads(r["usage"]) if r["usage"] else None
    results = [db.dec(r, "structured_result", "citations") for r in
               db.query("SELECT * FROM ai_results WHERE research_id=? ORDER BY created_at", (rid,))]
    consensus = [db.dec(r, "positions", "conflicts", "resolution", "synthesis") for r in
                 db.query("SELECT * FROM ai_consensus WHERE research_id=?", (rid,))]
    return {"tasks": tasks, "requests": reqs, "results": results, "consensus": consensus}


def run_agent(rid: str, code: str, *, actor: str = "system") -> dict:
    from ..ai import agents as A
    task_class = next((t for a, t in A.AGENT_TASKS if a == code), None)
    if not task_class:
        raise CoreError("E_VALIDATION", f"Агент {code} не имеет класса задачи")
    payload = {"documents": A.document_package(rid)}
    res = O.execute(rid, code, task_class, payload)
    audit(actor, "ai.run_agent", "research", rid, rid, {"agent": code})
    return res


def set_provider_enabled(pid: str, enabled: bool, *, actor: str = "system") -> dict:
    db.update("ai_providers", "id", pid, {"enabled": 1 if enabled else 0,
                                         "status": "active" if enabled else "disabled"})
    audit(actor, "ai.provider_toggle", "provider", pid, payload={"enabled": enabled})
    return {"id": pid, "enabled": enabled}


def check_provider(pid: str, *, actor: str = "system") -> dict:
    from ..ai.adapters import build_adapter
    p = db.dec(db.one("SELECT * FROM ai_providers WHERE id=?", (pid,)), "privacy_policy", "pricing", "metadata")
    if not p:
        raise CoreError("E_NOT_FOUND", "Провайдер не найден")
    adapter = build_adapter(p)
    res = adapter.check_connection()
    db.update("ai_providers", "id", pid, {"status": res["status"], "last_checked_at": iso_now(),
                                         "last_error": res.get("reason")})
    if res["status"] == "active":
        try:
            for m in adapter.list_models():
                db.upsert("ai_models", {
                    "id": f'{pid}::{m["model_id"]}', "provider_id": pid, "model_id": m["model_id"],
                    "display_name": m.get("display_name"), "capabilities": {"json_schema": None, "languages": []},
                    "context_window": m.get("context_window"), "languages": [],
                    "free_tier": 0, "paid": 1 if p["paid"] else 0, "quota": {},
                    "quality_scores": {}, "enabled": 1, "status": "active", "verified_at": iso_now()}, key="id")
        except CoreError:
            pass
    audit(actor, "ai.provider_check", "provider", pid, payload=res)
    return res


def put_secret(ref: str, value: str, *, kind: str = "api_key", actor: str = "system") -> dict:
    SecretStore.put(ref, kind, actor, value)
    audit(actor, "secret.put", "secret", ref, payload={"hint": value[-4:] if len(value) > 8 else "****"})
    return {"ref": ref, "stored": True}


def delete_secret(ref: str, *, actor: str = "system") -> dict:
    SecretStore.delete(ref)
    audit(actor, "secret.delete", "secret", ref)
    return {"ref": ref, "deleted": True}


def list_secrets() -> list[dict]:
    return SecretStore.list_public()


# ------------------------------------------------------------------ отчёты, журнал, система
def generate_report(rid: str, formats: list[str] | None = None, *, actor: str = "system") -> dict:
    res = RB.generate(rid, formats)
    audit(actor, "report.generate", "report", res["report_id"], rid, {"formats": formats})
    return res


def reports(rid: str) -> list[dict]:
    """Отчёты исследования с фактической доступностью файлов.

    Запись в БД переживает сам файл: клонирование состояния без var/files,
    восстановление из копии, ручная чистка каталога. Раньше интерфейс рисовал
    ссылку на каждый формат из записи, и клик по отсутствующему файлу давал
    голый 404 (замечание TOOL-03). Теперь доступность считается на сервере:
    `files_available` по форматам и `missing_files` списком.
    """
    out = []
    for r in db.query("SELECT * FROM reporting_reports WHERE research_id=? ORDER BY created_at DESC", (rid,)):
        item = db.dec(r, "formats", "files", "warnings")
        avail = {fmt: os.path.exists(path) for fmt, path in (item.get("files") or {}).items()}
        item["files_available"] = avail
        item["missing_files"] = sorted(f for f, ok in avail.items() if not ok)
        out.append(item)
    return out


def report_file(report_id: str, fmt: str) -> str:
    r = db.dec(db.one("SELECT * FROM reporting_reports WHERE id=?", (report_id,)), "files")
    if not r:
        raise CoreError("E_NOT_FOUND", "Отчёт не найден")
    key = fmt if fmt in r["files"] else ("csv_" + fmt if "csv_" + fmt in r["files"] else None)
    if not key:
        raise CoreError("E_NOT_FOUND", f"Формат {fmt} отсутствует в отчёте")
    path = r["files"][key]
    if not os.path.exists(path):
        raise CoreError("E_NOT_FOUND", "Файл отчёта недоступен")
    return path


def logs(research_id: str | None = None, limit: int = 300, kind: str = "all") -> dict:
    out: dict = {}
    if kind in ("all", "events"):
        out["events"] = events.history(research_id, limit=limit)
    if kind in ("all", "audit"):
        sql = "SELECT * FROM audit_log" + (" WHERE research_id=?" if research_id else "") + " ORDER BY created_at DESC LIMIT ?"
        out["audit"] = [db.dec(r, "payload") for r in db.query(sql, ([research_id] if research_id else []) + [limit])]
    if kind in ("all", "api"):
        sql = "SELECT * FROM audit_api_calls" + (" WHERE research_id=?" if research_id else "") + " ORDER BY created_at DESC LIMIT ?"
        out["api_calls"] = db.query(sql, ([research_id] if research_id else []) + [limit])
    if kind in ("all", "states"):
        sql = "SELECT * FROM core_state_history" + (" WHERE entity_id=?" if research_id else "") + " ORDER BY created_at DESC LIMIT ?"
        out["state_history"] = db.query(sql, ([research_id] if research_id else []) + [limit])
    return out


def trace(correlation_id: str, limit: int = 500) -> dict:
    """Полный путь запроса/запуска по correlation_id (ROADMAP P6).

    Собирает события, вызовы внешних API, записи аудита и затронутые этапы —
    в хронологическом порядке, без изменения предметного состояния.
    """
    cid = telemetry.sanitize(correlation_id)
    if not cid:
        raise CoreError("E_VALIDATION", "Некорректный correlation_id")
    ev = db.query("""SELECT id, seq, research_id, job_id, event_type, severity, created_at
                     FROM workflow_events WHERE correlation_id=? ORDER BY created_at LIMIT ?""", (cid, limit))
    calls = db.query("""SELECT id, kind, target, http_status, duration_ms, cached, error_code, created_at
                        FROM audit_api_calls WHERE correlation_id=? ORDER BY created_at LIMIT ?""", (cid, limit))
    aud = db.query("""SELECT id, actor, action, entity_kind, entity_id, created_at
                      FROM audit_log WHERE correlation_id=? ORDER BY created_at LIMIT ?""", (cid, limit))
    jobs = db.query("""SELECT id, research_id, stage, status, duration_ms, started_at, finished_at
                       FROM workflow_jobs WHERE correlation_id=? ORDER BY started_at""", (cid,))
    return {"correlation_id": cid, "events": ev, "api_calls": calls, "audit": aud, "jobs": jobs,
            "research_ids": sorted({r["research_id"] for r in ev if r.get("research_id")}),
            "total": len(ev) + len(calls) + len(aud),
            "note": "Трассировка связывает запрос → задание → этап → источник → расчёт"}


def logs_export(research_id: str | None, fmt: str = "json") -> str:
    data = logs(research_id, limit=2000)
    if fmt == "json":
        return json.dumps(data, ensure_ascii=False, indent=1, default=str)
    if fmt == "csv":
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["kind", "created_at", "type/action", "severity/http", "payload"])
        for kind, rows in data.items():
            for r in rows:
                w.writerow([kind, r.get("created_at"), r.get("event_type") or r.get("action") or r.get("target"),
                            r.get("severity") or r.get("http_status"), json.dumps(r, ensure_ascii=False)[:1500]])
        return buf.getvalue()
    lines = []
    for kind, rows in data.items():
        lines.append(f"=== {kind} ===")
        for r in rows:
            lines.append(f'{r.get("created_at")} {json.dumps(r, ensure_ascii=False)}')
    return "\n".join(lines)


# ------------------------------------------------------------------ журнал действий (ред. 1.4.0)
def journal_list(**filters) -> dict:
    from .. import journal
    return journal.query(**filters)


def journal_entry(journal_id: str) -> dict:
    from .. import journal
    return journal.entry(journal_id)


def journal_errors(limit: int = 50, since: str | None = None) -> dict:
    from .. import journal
    return journal.errors(limit=limit, since=since)


def journal_stats() -> dict:
    from .. import journal
    return journal.stats()


def journal_export(fmt: str = "txt", **filters) -> str:
    from .. import journal
    return journal.export(fmt, **filters)


def journal_client(body: dict, *, peer: str = "", session: dict | None = None,
                   user_agent: str = "") -> dict:
    """Ошибка интерфейса, присланная браузером (доступно и до входа)."""
    from .. import journal
    sess = session or {}
    return journal.client_event(body, peer=peer, actor=sess.get("login"),
                                role=sess.get("role"), user_agent=user_agent)


def journal_prune(*, actor: str = "system", days: int | None = None,
                  max_rows: int | None = None) -> dict:
    from .. import journal
    res = journal.prune(days=days, max_rows=max_rows)
    audit(actor, "journal.prune", "journal", None, None, res)
    return res


def diagnostics_run(research_id: str | None = None, *, to_journal: bool = False,
                    actor: str = "system") -> dict:
    """Поиск противоречий: расхождений с ТЗ, а не мнений модели."""
    from .. import diagnostics
    res = diagnostics.run(research_id=research_id, to_journal=to_journal, actor=actor)
    if to_journal:
        audit(actor, "diagnostics.run", "diagnostics", None, research_id,
              {"findings": len(res["findings"]), "cases": res["cases"]})
    return res


# ------------------------------------------------------------------ эксплуатация (P6, ред. 1.3)
def slo_report() -> dict:
    from .. import slo
    return slo.report()


def slo_probes_run(*, actor: str = "system") -> dict:
    from .. import slo
    probes = slo.run_probes()
    res = slo.evaluate_alerts(actor=actor)
    audit(actor, "slo.probes", "system", None, payload={"probes": len(probes),
                                                       "opened": len(res["opened"])})
    return {"probes": probes, "opened": res["opened"], "closed": res["closed"],
            "report": slo.report()}


def alerts_list(state: str = "active", limit: int = 200) -> dict:
    from .. import slo
    items = slo.alerts(state=state, limit=limit)
    return {"items": items, "total": len(items),
            "rules": {code: {"severity": r["severity"], "title": r["title"]} for code, r in slo.RULES.items()}}


def alerts_evaluate(*, actor: str = "system") -> dict:
    from .. import slo
    res = slo.evaluate_alerts(actor=actor)
    audit(actor, "alerts.evaluate", "system", None, payload={"opened": len(res["opened"]),
                                                             "closed": len(res["closed"])})
    return res


def alert_acknowledge(alert_id: str, *, actor: str = "system") -> dict:
    from .. import slo
    row = slo.acknowledge(alert_id, actor=actor)
    audit(actor, "alert.acknowledge", "alert", alert_id)
    return row


def backups_list() -> dict:
    from .. import backup as BK
    items = BK.list_backups()
    return {"items": items, "total": len(items),
            "policy": {"max_age_hours": __import__("isheika.slo", fromlist=["x"]).BACKUP_MAX_AGE_HOURS,
                       "note": "Восстановление выполняется из CLI при остановленном сервере."}}


def backup_create(*, actor: str = "system", kind: str = "manual") -> dict:
    from .. import backup as BK
    row = BK.create(actor=actor, kind=kind)
    check = BK.verify(row["path"])
    audit(actor, "backup.create", "backup", row["id"], payload={"size_bytes": row["size_bytes"],
                                                                "verified": check["ok"]})
    events.emit("system.warning", payload={"action": "backup.created", "backup_id": row["id"],
                                           "verified": check["ok"]})
    return {"backup": row, "verify": {"ok": check["ok"], "checks": check["checks"]}}


def backup_verify(backup_id: str, *, actor: str = "system") -> dict:
    from .. import backup as BK
    path = BK.resolve(backup_id)
    res = BK.verify(path)
    audit(actor, "backup.verify", "backup", backup_id, payload={"ok": res["ok"]})
    return res


def system_state() -> dict:
    from ..search import quota
    return {
        "app": "ИЩЕЙКА НТР AI", "codename": "ISHEIKA-NTR-AI", "version": __import__("isheika").__version__,
        "api_version": "v1", "methodology_version": SETTINGS.methodology_version,
        "profile": SETTINGS.profile, "settings": SETTINGS.public_dict(),
        "counters": {
            "researches": db.count("core_researches"), "documents": db.count("content_documents"),
            "sources": db.count("registry_sources"), "connectors": db.count("registry_connectors"),
            "countries": db.count("dict_countries"), "providers": db.count("ai_providers"),
            "models": db.count("ai_models"), "agents": db.count("ai_agents"),
            "claims": db.count("knowledge_claims"), "evidence": db.count("evidence_items"),
            "reports": db.count("reporting_reports"), "events": db.count("workflow_events"),
        },
        "quota": quota.snapshot(),
        "statuses": {k: list(v) for k, v in FSMS.items()},
        "server_time": iso_now(),
    }


def dashboard() -> dict:
    recent = list_researches(limit=8)
    provs = ai_providers()
    active = [p for p in provs if p["status"] == "active"]
    conns = connectors()
    return {
        "researches": recent,
        "jobs": db.query("SELECT stage,status,COUNT(*) AS n FROM workflow_jobs GROUP BY stage,status"),
        "providers_summary": {"total": len(provs), "active": len(active),
                              "key_configured": sum(1 for p in provs if p["key_configured"]),
                              "paid_blocked": sum(1 for p in provs if p["paid"] and not SETTINGS.allow_paid_ai)},
        "connectors_summary": {"total": len(conns),
                               "live": sum(1 for c in conns if c["implementation"] == "live"),
                               "active": sum(1 for c in conns if c["health_status"] == "active"),
                               "restricted": sum(1 for c in conns if c["requires_key"] and not c["key_configured"])},
        "recent_documents": [db.dec(r, "identifiers") for r in db.query(
            "SELECT id,title,source_code,country_code,published_at,state,created_at FROM research_documents ORDER BY created_at DESC LIMIT 10")],
        "source_stats": source_stats(),
        "events": events.history(limit=25),
        "quality": db.query("SELECT metric, value, sample_size, calibrated FROM analytics_quality ORDER BY created_at DESC LIMIT 6"),
    }


def update_settings(body: dict, *, actor: str = "system") -> dict:
    allowed = {"allow_paid_ai", "allow_external_ai", "network_enabled", "respect_robots",
               "ai_mode", "contact_email", "max_docs_per_source", "max_parallel_fetch",
               "privacy_class_max", "http_timeout"}
    changed = {}
    for k, v in body.items():
        if k not in allowed:
            continue
        cur = getattr(SETTINGS, k)
        if isinstance(cur, bool):
            v = bool(v)
        elif isinstance(cur, int):
            v = int(v)
        elif isinstance(cur, float):
            v = float(v)
        setattr(SETTINGS, k, v)
        changed[k] = v
    SETTINGS.save()
    audit(actor, "settings.update", "settings", None, payload=changed)
    return {"changed": changed, "settings": SETTINGS.public_dict()}
