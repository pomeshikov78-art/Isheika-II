"""HTTP-транспорт на стандартной библиотеке (профиль DEV/автономный).

ТЗ-05 §9.2 рекомендует FastAPI для промышленного контура. Предметная логика
(api/service.py) не зависит от транспорта: рядом лежит adapters_fastapi.py,
который поднимает те же маршруты на FastAPI/uvicorn без изменения сервисного
слоя. Здесь — zero-dependency сервер, чтобы система запускалась сразу.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..config import SETTINGS, WEB_DIR
from ..contracts import CoreError, iso_now, new_id
from .. import telemetry
from ..workflow import events
from . import service as S

ROUTES: list[tuple[str, str, callable]] = []


def route(method: str, pattern: str):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


# ------------------------------------------------------------------ auth / system
@route("POST", r"/api/v1/auth/login")
def r_login(req, m, body):
    return S.login(body.get("login", ""), body.get("password", ""))


@route("GET", r"/api/v1/auth/me")
def r_me(req, m, body):
    s = req.session
    return {"user": {k: s[k] for k in ("login", "role", "display_name")},
            "rights": sorted(S.ROLE_RIGHTS.get(s["role"], set()))}


@route("GET", r"/api/v1/methodology")
def r_methodology(req, m, body):
    """Методика расчётного ядра: веса, пороги, критерии TRL, цели валидации (ТЗ-03)."""
    from ..registry import loader
    return loader.methodology()


@route("GET", r"/api/v1/system")
def r_system(req, m, body):
    return S.system_state()


@route("GET", r"/api/v1/system/dashboard")
def r_dashboard(req, m, body):
    S.require(req.session, "research.read")
    return S.dashboard()


@route("GET", r"/api/v1/users")
def r_users(req, m, body):
    S.require(req.session, "settings.read")
    from ..storage import db
    return {"items": db.query("SELECT id, login, display_name, role, is_active FROM core_users ORDER BY login")}


# ------------------------------------------------------------------ research
@route("GET", r"/api/v1/researches")
def r_list(req, m, body):
    S.require(req.session, "research.read")
    return {"items": S.list_researches(limit=int(req.qs.get("limit", 50)), status=req.qs.get("status"))}


@route("POST", r"/api/v1/researches")
def r_create(req, m, body):
    S.require(req.session, "research.write")
    return S.create_research(body, actor=req.session["login"])


@route("GET", r"/api/v1/researches/([^/]+)")
def r_get(req, m, body):
    S.require(req.session, "research.read")
    return S.get_research(m.group(1))


@route("POST", r"/api/v1/researches/([^/]+)/start")
def r_start(req, m, body):
    S.require(req.session, "research.run")
    return S.start_research(m.group(1), resume=bool(body.get("resume")), actor=req.session["login"])


@route("POST", r"/api/v1/researches/([^/]+)/cancel")
def r_cancel(req, m, body):
    S.require(req.session, "research.run")
    return S.cancel_research(m.group(1), actor=req.session["login"])


@route("GET", r"/api/v1/researches/([^/]+)/status")
def r_status(req, m, body):
    S.require(req.session, "research.read")
    return S.research_status(m.group(1))


@route("POST", r"/api/v1/researches/([^/]+)/query")
def r_query_update(req, m, body):
    S.require(req.session, "research.write")
    return S.update_query(m.group(1), body, actor=req.session["login"])


@route("POST", r"/api/v1/queries/preview")
def r_preview(req, m, body):
    S.require(req.session, "research.read")
    return S.preview_query(body)


# ------------------------------------------------------------------ documents
@route("GET", r"/api/v1/documents")
def r_docs(req, m, body):
    S.require(req.session, "research.read")
    rid = req.qs.get("research_id")
    if not rid:
        raise CoreError("E_VALIDATION", "Не указан research_id")
    return S.list_documents(rid, cls=req.qs.get("class"), country=req.qs.get("country"),
                            doc_type=req.qs.get("type"), language=req.qs.get("language"),
                            min_score=float(req.qs["min_score"]) if req.qs.get("min_score") else None,
                            q=req.qs.get("q"), limit=int(req.qs.get("limit", 50)),
                            offset=int(req.qs.get("offset", 0)), sort=req.qs.get("sort", "score"))


@route("GET", r"/api/v1/documents/([^/]+)")
def r_doc(req, m, body):
    S.require(req.session, "research.read")
    return S.get_document(m.group(1))


@route("POST", r"/api/v1/documents/([^/]+)/exclude")
def r_doc_exclude(req, m, body):
    S.require(req.session, "evidence.write")
    return S.exclude_document(m.group(1), body.get("reason", ""), actor=req.session["login"],
                              research_id=body.get("research_id") or req.qs.get("research_id"))


@route("POST", r"/api/v1/documents/([^/]+)/label")
def r_doc_label(req, m, body):
    S.require(req.session, "quality.write")
    return S.label_document(m.group(1), int(body.get("label", 0)), actor=req.session["login"],
                            research_id=body.get("research_id") or req.qs.get("research_id"))


# ------------------------------------------------------------------ analytics
@route("GET", r"/api/v1/analytics/([^/]+)")
def r_analytics(req, m, body):
    S.require(req.session, "analytics.read")
    return S.analytics_bundle(m.group(1))


@route("POST", r"/api/v1/analytics/([^/]+)/recompute")
def r_recompute(req, m, body):
    S.require(req.session, "analytics.write")
    return S.recompute(m.group(1), weights=body.get("weights"), actor=req.session["login"])


@route("GET", r"/api/v1/technologies/([^/]+)/passport")
def r_passport(req, m, body):
    S.require(req.session, "analytics.read")
    return S.passport(m.group(1))


@route("GET", r"/api/v1/claims")
def r_claims(req, m, body):
    S.require(req.session, "analytics.read")
    return {"items": S.claims(req.qs.get("research_id", ""), req.qs.get("type"), req.qs.get("status"))}


@route("GET", r"/api/v1/evidence")
def r_evidence(req, m, body):
    S.require(req.session, "analytics.read")
    return {"items": S.evidence_list(req.qs.get("research_id", ""), req.qs.get("claim_id"))}


@route("POST", r"/api/v1/evidence")
def r_evidence_add(req, m, body):
    S.require(req.session, "evidence.write")
    return S.add_evidence(body.get("research_id", ""), body, actor=req.session["login"])


@route("GET", r"/api/v1/forecasts/([^/]+)")
def r_forecast(req, m, body):
    S.require(req.session, "analytics.read")
    from ..analytics import forecast as F
    return F.latest(m.group(1)) or {}


# ------------------------------------------------------------------ registry
@route("GET", r"/api/v1/sources")
def r_sources(req, m, body):
    S.require(req.session, "registry.read")
    return S.sources(category=req.qs.get("category"), country=req.qs.get("country"),
                     access=req.qs.get("access"), status=req.qs.get("status"),
                     marker=req.qs.get("marker"), q=req.qs.get("q"),
                     limit=int(req.qs.get("limit", 100)), offset=int(req.qs.get("offset", 0)))


@route("GET", r"/api/v1/sources/stats")
def r_source_stats(req, m, body):
    S.require(req.session, "registry.read")
    return S.source_stats()


@route("GET", r"/api/v1/connectors")
def r_connectors(req, m, body):
    S.require(req.session, "registry.read")
    return {"items": S.connectors()}


@route("POST", r"/api/v1/connectors/check")
def r_conn_check(req, m, body):
    S.require(req.session, "registry.write")
    return {"items": S.connector_health(body.get("code"), actor=req.session["login"])}


@route("GET", r"/api/v1/countries")
def r_countries(req, m, body):
    return {"items": S.countries()}


@route("POST", r"/api/v1/countries/([^/]+)/toggle")
def r_country_toggle(req, m, body):
    S.require(req.session, "registry.write")
    return S.toggle_country(m.group(1), bool(body.get("enabled", True)), actor=req.session["login"])


@route("GET", r"/api/v1/registry/changelog")
def r_changelog(req, m, body):
    S.require(req.session, "registry.read")
    return S.registry_changelog()


# ------------------------------------------------------------------ AI
@route("GET", r"/api/v1/ai/providers")
def r_providers(req, m, body):
    S.require(req.session, "ai.read")
    return {"items": S.ai_providers()}


@route("GET", r"/api/v1/ai/agents")
def r_agents(req, m, body):
    S.require(req.session, "ai.read")
    return {"items": S.ai_agents()}


@route("GET", r"/api/v1/ai/tasks")
def r_ai_tasks(req, m, body):
    S.require(req.session, "ai.read")
    return S.ai_tasks(req.qs.get("research_id", ""))


@route("POST", r"/api/v1/ai/providers/([^/]+)/check")
def r_provider_check(req, m, body):
    S.require(req.session, "ai.run")
    return S.check_provider(m.group(1), actor=req.session["login"])


@route("POST", r"/api/v1/ai/providers/([^/]+)/toggle")
def r_provider_toggle(req, m, body):
    S.require(req.session, "keys.write")
    return S.set_provider_enabled(m.group(1), bool(body.get("enabled", True)), actor=req.session["login"])


@route("POST", r"/api/v1/ai/agents/([^/]+)/run")
def r_agent_run(req, m, body):
    S.require(req.session, "ai.run")
    return S.run_agent(body.get("research_id", ""), m.group(1), actor=req.session["login"])


@route("GET", r"/api/v1/ai/route")
def r_route_preview(req, m, body):
    S.require(req.session, "ai.read")
    from ..ai import orchestrator as O
    task_class = req.qs.get("task_class", "tech_analysis")
    c = O.candidates(task_class)
    try:
        r = O.select_route(task_class)
        chosen = {"provider": r["entry"]["provider"]["id"], "model": r["entry"]["model"]["model_id"],
                  "group": r["group"], "score": r["entry"]["score"], "reason": r["reason"]}
    except CoreError as e:
        chosen = {"error": e.error.to_dict()}
    return {"task_class": task_class, "chosen": chosen,
            "free": [{"provider": e["provider"]["id"], "model": e["model"]["model_id"],
                      "score": e["score"]} for e in O.rank(c["free"], task_class)],
            "local": [{"provider": e["provider"]["id"], "model": e["model"]["model_id"]} for e in c["local"]],
            "paid_blocked": [{"provider": e["provider"]["id"], "model": e["model"]["model_id"]} for e in c["paid"]],
            "rejected": [{"provider": e["provider"]["id"], "model": e["model"]["model_id"],
                          "reasons": e["reasons"]} for e in c["rejected"]]}


# ------------------------------------------------------------------ settings / secrets
@route("GET", r"/api/v1/settings")
def r_settings(req, m, body):
    S.require(req.session, "settings.read")
    return SETTINGS.public_dict()


@route("POST", r"/api/v1/settings")
def r_settings_post(req, m, body):
    S.require(req.session, "keys.write")
    return S.update_settings(body, actor=req.session["login"])


@route("GET", r"/api/v1/settings/secrets")
def r_secrets(req, m, body):
    S.require(req.session, "settings.read")
    return {"items": S.list_secrets()}


@route("POST", r"/api/v1/settings/secrets")
def r_secret_put(req, m, body):
    S.require(req.session, "keys.write")
    if not body.get("ref") or not body.get("value"):
        raise CoreError("E_VALIDATION", "Требуются ref и value")
    return S.put_secret(body["ref"], body["value"], kind=body.get("kind", "api_key"), actor=req.session["login"])


@route("DELETE", r"/api/v1/settings/secrets/([^/]+)")
def r_secret_del(req, m, body):
    S.require(req.session, "keys.write")
    return S.delete_secret(m.group(1), actor=req.session["login"])


# ------------------------------------------------------------------ reports / logs / events
@route("GET", r"/api/v1/reports")
def r_reports(req, m, body):
    S.require(req.session, "research.read")
    return {"items": S.reports(req.qs.get("research_id", ""))}


@route("POST", r"/api/v1/reports")
def r_report_gen(req, m, body):
    S.require(req.session, "report.write")
    return S.generate_report(body.get("research_id", ""), body.get("formats"), actor=req.session["login"])


@route("GET", r"/api/v1/logs")
def r_logs(req, m, body):
    S.require(req.session, "logs.read")
    return S.logs(req.qs.get("research_id"), limit=int(req.qs.get("limit", 200)), kind=req.qs.get("kind", "all"))


@route("GET", r"/api/v1/events")
def r_events(req, m, body):
    S.require(req.session, "research.read")
    return {"items": events.history(req.qs.get("research_id"), after=req.qs.get("after"),
                                    limit=int(req.qs.get("limit", 200)))}


# ------------------------------------------------------------------ каталог v1.1 (ИД-04)
@route("GET", r"/api/v1/search-tasks")
def r_search_tasks(req, m, body):
    S.require(req.session, "research.read")
    from ..storage import db
    rid = req.qs.get("research_id")
    if not rid:
        raise CoreError("E_VALIDATION", "Не указан research_id")
    return {"items": db.query("SELECT * FROM search_jobs WHERE research_id=? ORDER BY created_at", (rid,))}


@route("GET", r"/api/v1/search-results")
def r_search_results(req, m, body):
    S.require(req.session, "research.read")
    rid = req.qs.get("research_id")
    if not rid:
        raise CoreError("E_VALIDATION", "Не указан research_id")
    return S.search_results(rid, cls=req.qs.get("class"), limit=int(req.qs.get("limit", 100)),
                            offset=int(req.qs.get("offset", 0)))


@route("GET", r"/api/v1/technologies")
def r_technologies(req, m, body):
    S.require(req.session, "analytics.read")
    from ..storage import db
    rid = req.qs.get("research_id")
    if not rid:
        raise CoreError("E_VALIDATION", "Не указан research_id")
    return {"items": [db.dec(r, "passport") for r in
                      db.query("SELECT * FROM knowledge_technologies WHERE research_id=?", (rid,))]}


@route("GET", r"/api/v1/trl-assessments")
def r_trl_assessments(req, m, body):
    S.require(req.session, "analytics.read")
    return S.trl_assessments(req.qs.get("research_id", ""))


@route("GET", r"/api/v1/trl-criteria")
def r_trl_criteria(req, m, body):
    S.require(req.session, "analytics.read")
    return {"items": S.trl_criteria()}


@route("GET", r"/api/v1/feasibility-assessments")
def r_feasibility(req, m, body):
    S.require(req.session, "analytics.read")
    return S.feasibility_assessments(req.qs.get("research_id", ""))


@route("GET", r"/api/v1/confidence-assessments")
def r_confidence(req, m, body):
    S.require(req.session, "analytics.read")
    return S.confidence_assessments(req.qs.get("research_id", ""), req.qs.get("subject"))


@route("GET", r"/api/v1/forecasts")
def r_forecasts(req, m, body):
    S.require(req.session, "analytics.read")
    return S.forecast_points(req.qs.get("research_id", ""))


@route("GET", r"/api/v1/ai-tasks")
def r_ai_tasks_catalog(req, m, body):
    S.require(req.session, "ai.read")
    return S.ai_tasks(req.qs.get("research_id", ""))


@route("GET", r"/api/v1/methodologies")
def r_methodologies(req, m, body):
    S.require(req.session, "analytics.read")
    return {"items": S.methodologies_list()}


@route("GET", r"/api/v1/methodologies/([^/]+)")
def r_methodology_code(req, m, body):
    S.require(req.session, "analytics.read")
    return S.methodology_get(m.group(1))


@route("POST", r"/api/v1/methodologies/([^/]+)/versions")
def r_methodology_new_version(req, m, body):
    S.require(req.session, "analytics.write")
    return S.methodology_create_version(m.group(1), body, actor=req.session["login"])


@route("POST", r"/api/v1/methodologies/([^/]+)/approval")
def r_methodology_approval(req, m, body):
    S.require(req.session, "analytics.write")
    return S.methodology_approve(m.group(1), body.get("approval_status", "VALIDATED"),
                                 actor=req.session["login"])


@route("GET", r"/api/v1/document-clusters")
def r_clusters(req, m, body):
    S.require(req.session, "research.read")
    return {"items": S.document_clusters(req.qs.get("research_id", "")),
            "summary": S.dedup_summary(req.qs.get("research_id", ""))}


@route("GET", r"/api/v1/document-relations")
def r_relations(req, m, body):
    S.require(req.session, "research.read")
    return {"items": S.document_relations(req.qs.get("research_id", ""))}


@route("POST", r"/api/v1/document-clusters/confirm")
def r_cluster_confirm(req, m, body):
    S.require(req.session, "evidence.write")
    return S.confirm_cluster(body.get("research_id", ""), body, actor=req.session["login"])


@route("GET", r"/api/v1/independence-groups")
def r_independence(req, m, body):
    S.require(req.session, "analytics.read")
    return {"items": S.independence_groups(req.qs.get("research_id", ""))}


@route("GET", r"/api/v1/research-runs")
def r_runs(req, m, body):
    S.require(req.session, "research.read")
    return {"items": S.runs(req.qs.get("research_id", ""))}


@route("POST", r"/api/v1/replay")
def r_replay(req, m, body):
    S.require(req.session, "analytics.write")
    return S.replay(body.get("kind", "feasibility"), body.get("assessment_id", ""),
                    actor=req.session["login"])


@route("GET", r"/api/v1/document-graph")
def r_document_graph(req, m, body):
    """Граф связей документов с серверной фильтрацией типов (ROADMAP P4)."""
    S.require(req.session, "research.read")
    types = [t for t in (req.qs.get("types", "") or "").split(",") if t]
    return S.document_graph(req.qs.get("research_id", ""), types,
                            limit=int(req.qs.get("limit", "300")))


@route("GET", r"/api/v1/assessments/diff")
def r_assessment_diff(req, m, body):
    """Сравнение двух версий расчёта (ROADMAP P4, ИД-09/ИД-12)."""
    S.require(req.session, "analytics.read")
    return S.assessment_diff(req.qs.get("kind", "feasibility"),
                             req.qs.get("a", ""), req.qs.get("b", ""))


@route("GET", r"/api/v1/trace/([^/]+)")
def r_trace(req, m, body):
    """Сквозная трассировка: события, вызовы API и аудит по correlation_id (P6)."""
    S.require(req.session, "logs.read")
    return S.trace(m.group(1))


@route("GET", r"/api/v1/slo")
def r_slo(req, m, body):
    """SLO доступности: окна 24 ч / 7 сут / 30 сут, бюджет ошибок, burn rate (P6)."""
    S.require(req.session, "logs.read")
    return S.slo_report()


@route("POST", r"/api/v1/slo/probes")
def r_slo_probes(req, m, body):
    """Немедленные самопроверки подсистем и пересчёт правил оповещения."""
    S.require(req.session, "settings.read")
    return S.slo_probes_run(actor=req.session["login"])


@route("GET", r"/api/v1/alerts")
def r_alerts(req, m, body):
    """Алерты эксплуатации с доказательствами и справочником правил."""
    S.require(req.session, "logs.read")
    return S.alerts_list(req.qs.get("state", "active"), int(req.qs.get("limit", "200")))


@route("POST", r"/api/v1/alerts/evaluate")
def r_alerts_evaluate(req, m, body):
    S.require(req.session, "settings.read")
    return S.alerts_evaluate(actor=req.session["login"])


@route("POST", r"/api/v1/alerts/([^/]+)/acknowledge")
def r_alert_ack(req, m, body):
    """Подтверждение алерта оператором (закрытие — только по устранении причины)."""
    S.require(req.session, "settings.read")
    return S.alert_acknowledge(m.group(1), actor=req.session["login"])


@route("GET", r"/api/v1/backups")
def r_backups(req, m, body):
    """Реестр резервных копий и регламент их давности."""
    S.require(req.session, "logs.read")
    return S.backups_list()


@route("POST", r"/api/v1/backups")
def r_backup_create(req, m, body):
    """Создание копии с немедленной проверкой целостности."""
    S.require(req.session, "keys.write")
    return S.backup_create(actor=req.session["login"], kind=(body or {}).get("kind", "manual"))


@route("POST", r"/api/v1/backups/([^/]+)/verify")
def r_backup_verify(req, m, body):
    S.require(req.session, "logs.read")
    return S.backup_verify(m.group(1), actor=req.session["login"])


@route("GET", r"/api/v1/boot-log")
def r_boot_log(req, m, body):
    """Журнал загрузки и самопроверка исправности (доступен без аутентификации)."""
    from .. import boot
    return boot.snapshot(with_checks=req.qs.get("check", "1") != "0")


@route("GET", r"/api/v1/boot-log/history")
def r_boot_history(req, m, body):
    """История загрузок: шаги предыдущих запусков процесса.

    В отличие от текущего журнала (`/api/v1/boot-log`, публичная диагностика
    «белого экрана») история — эксплуатационный журнал: пути к каталогу данных,
    платформа, причины прошлых отказов. Право `logs.read`, как у остальных
    журналов и у SLO/алертов/копий (замечание RBAC: наблюдатель не читает журнал).
    """
    S.require(req.session, "logs.read")
    from .. import boot
    from ..storage import db
    limit = int(req.qs.get("limit", "300"))
    rows = db.query("SELECT * FROM ops_boot_log ORDER BY at DESC, rowid DESC LIMIT ?", (limit,))
    return {"items": rows, "total": len(rows), "current_boot_id": boot.BOOT_ID}


# ------------------------------------------------------------------ журнал действий (ред. 1.4.0)
@route("GET", r"/api/v1/journal")
def r_journal(req, m, body):
    """Сквозной журнал действий: фильтры по уровню, виду, автору, исследованию, трассировке."""
    S.require(req.session, "logs.read")
    q = req.qs
    return S.journal_list(level=q.get("level"), kind=q.get("kind"), actor=q.get("actor"),
                          source=q.get("source"), research_id=q.get("research_id"),
                          correlation_id=q.get("cid") or q.get("correlation_id"),
                          request_id=q.get("request_id"), outcome=q.get("outcome"),
                          q=q.get("q"), since=q.get("since"), until=q.get("until"),
                          fingerprint_=q.get("fingerprint"),
                          limit=int(q.get("limit", "200")), offset=int(q.get("offset", "0")))


@route("GET", r"/api/v1/journal/stats")
def r_journal_stats(req, m, body):
    S.require(req.session, "logs.read")
    return S.journal_stats()


@route("GET", r"/api/v1/journal/errors")
def r_journal_errors(req, m, body):
    """Дефекты, сгруппированные по подписи: одинаковые падения — один дефект."""
    S.require(req.session, "logs.read")
    return S.journal_errors(limit=int(req.qs.get("limit", "50")), since=req.qs.get("since"))


@route("POST", r"/api/v1/journal/client")
def r_journal_client(req, m, body):
    """Ошибка интерфейса из браузера. Публичный маршрут: первый отказ бывает до входа."""
    peer = req.client_address[0] if getattr(req, "client_address", None) else ""
    return S.journal_client(body or {}, peer=peer, session=getattr(req, "session", None),
                            user_agent=req.headers.get("User-Agent", ""))


@route("POST", r"/api/v1/journal/prune")
def r_journal_prune(req, m, body):
    """Ручная ротация журнала по политике хранения."""
    S.require(req.session, "settings.read")
    b = body or {}
    return S.journal_prune(actor=req.session["login"], days=b.get("days"), max_rows=b.get("max_rows"))


@route("GET", r"/api/v1/journal/([^/]+)")
def r_journal_entry(req, m, body):
    S.require(req.session, "logs.read")
    return S.journal_entry(m.group(1))


@route("GET", r"/api/v1/diagnostics")
def r_diagnostics(req, m, body):
    """Поиск противоречий: состояние, расчёты, доказательства, политика, повторяемость дефектов."""
    S.require(req.session, "logs.read")
    return S.diagnostics_run(req.qs.get("research_id"))


@route("POST", r"/api/v1/diagnostics/run")
def r_diagnostics_run(req, m, body):
    """Прогон правил с записью найденных противоречий в журнал действий."""
    S.require(req.session, "logs.read")
    b = body or {}
    return S.diagnostics_run(b.get("research_id"), to_journal=True, actor=req.session["login"])


@route("GET", r"/api/v1/openapi.json")
def r_openapi(req, m, body):
    from .openapi import build_spec
    return build_spec(ROUTES)


# ------------------------------------------------------------------ устаревшие маршруты
def legacy(method: str, pattern: str, new_path: str, fn):
    """ИД-04: старые пути возвращают 410 Gone с указанием канонического маршрута.

    Обратная совместимость включается явно (SETTINGS.api_legacy_compat) и имеет
    установленный срок вывода (SETTINGS.api_legacy_sunset).
    """
    def handler(req, m, body):
        if not SETTINGS.api_legacy_compat:
            raise CoreError("E_GONE", f"Маршрут {pattern} выведен из эксплуатации (ИД-04)",
                            new_path=new_path, sunset=SETTINGS.api_legacy_sunset,
                            canonical_catalog="/api/v1/openapi.json")
        return fn(req, m, body)
    ROUTES.append((method, re.compile("^" + pattern + "$"), handler))


legacy("GET", r"/api/v1/research", "/api/v1/researches", r_list)
legacy("POST", r"/api/v1/research", "/api/v1/researches", r_create)
legacy("GET", r"/api/v1/research/([^/]+)", "/api/v1/researches/{research_id}", r_get)
legacy("POST", r"/api/v1/research/([^/]+)/start", "/api/v1/researches/{research_id}/start", r_start)
legacy("POST", r"/api/v1/research/([^/]+)/cancel", "/api/v1/researches/{research_id}/cancel", r_cancel)
legacy("GET", r"/api/v1/research/([^/]+)/status", "/api/v1/researches/{research_id}/status", r_status)
legacy("POST", r"/api/v1/research/([^/]+)/query", "/api/v1/researches/{research_id}/query", r_query_update)
legacy("GET", r"/api/v1/ai/tasks", "/api/v1/ai-tasks", r_ai_tasks_catalog)


# Типы содержимого задаются явно: mimetypes на Windows читает реестр и может
# вернуть text/plain для .js — браузер тогда откажется исполнять сценарий.
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".ico": "image/x-icon", ".webp": "image/webp",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
    ".map": "application/json; charset=utf-8", ".txt": "text/plain; charset=utf-8",
}


def static_ctype(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return STATIC_TYPES.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"


def static_target(path: str) -> str | None:
    """URL → безопасный относительный путь внутри каталога интерфейса.

    Разбор ведётся в POSIX-правилах НЕЗАВИСИМО от os.path: на Windows
    os.path.normpath("/app.js") возвращает "\\app.js", lstrip("/") его не
    снимает, os.path.join отбрасывает каталог интерфейса — и каждый ресурс
    подменялся index.html (белый экран в браузере). Возвращает None для
    попыток выхода за пределы каталога.
    """
    import posixpath
    import urllib.parse

    rel = urllib.parse.unquote((path or "/").split("?", 1)[0].split("#", 1)[0])
    rel = rel.replace("\\", "/")
    if rel in ("", "/"):
        rel = "/index.html"
    rel = posixpath.normpath("/" + rel.lstrip("/")).lstrip("/")
    if not rel or rel.startswith("..") or ":" in rel.split("/")[0]:
        return None
    return rel


PUBLIC_PATHS = {"/api/v1/auth/login", "/api/v1/system", "/api/v1/countries", "/api/v1/boot-log",
                "/api/v1/journal/client"}


class Handler(BaseHTTPRequestHandler):
    server_version = "IsheikaNTR/" + __import__("isheika").__version__
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # тишина в stdout, журнал — в БД
        pass

    # -------------------------------------------------- helpers
    def _send(self, code: int, payload: bytes, ctype: str, extra: dict | None = None):
        self._resp_status = code
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Request-ID", getattr(self, "request_id", ""))
        self.send_header("X-Correlation-ID", getattr(self, "correlation_id", "") or getattr(self, "request_id", ""))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _err(self, err: CoreError | Exception, code: int = 400):
        if isinstance(err, CoreError):
            e = err.error
            e.request_id = getattr(self, "request_id", None)
            self._err_code = e.code
            mapping = {"E_AUTH": 401, "E_FORBIDDEN": 403, "E_NOT_FOUND": 404, "E_VALIDATION": 422,
                       "E_STATE": 409, "E_QUOTA": 429, "E_RATE_LIMIT": 429, "E_POLICY": 403,
                       "E_ROBOTS": 403, "E_SCHEMA": 502, "E_PROVIDER": 502, "E_NETWORK": 503,
                       "E_INTERNAL": 500, "E_GONE": 410}
            self._json(mapping.get(e.code, code), {"error": e.to_dict()})
        else:
            # Непредвиденное исключение — это дефект: полный traceback сохраняется
            # в журнале действий (ред. 1.4.0) и находится по подписи, а клиенту
            # отдаётся код и request_id. Раньше traceback уходил в ответ и терялся.
            self._err_code = "E_INTERNAL"
            try:
                from .. import journal
                journal.error(err, "api", f"{getattr(self, '_method', '')} {getattr(self, '_path', '')}".strip(),
                              message=str(err), actor=(getattr(self, "session", None) or {}).get("login"),
                              role=(getattr(self, "session", None) or {}).get("role"),
                              http_status=500, error_code="E_INTERNAL",
                              research_id=(getattr(self, "qs", {}) or {}).get("research_id"),
                              detail={"path": getattr(self, "_path", ""), "peer": self.client_address[0]
                                      if getattr(self, "client_address", None) else ""})
            except Exception:
                pass
            body = {"code": "E_INTERNAL", "message": str(err)[:400],
                    "request_id": getattr(self, "request_id", None),
                    "hint": "Полный traceback — в журнале действий (UI-32) по этому request_id"}
            if SETTINGS.journal_stack_in_response:
                body["trace"] = traceback.format_exc()[-800:]
            self._json(500, {"error": body})

    # -------------------------------------------------- dispatch
    def _handle(self, method: str):
        """Единая точка входа: контекст трассировки охватывает весь запрос (P6).

        Здесь же пишется журнал действий (ред. 1.4.0): метод, путь, исход, код
        ошибки, длительность, пользователь и трассировка — по каждому обращению.
        """
        self.request_id = telemetry.sanitize(self.headers.get("X-Request-ID")) or new_id("req-")
        self.correlation_id = telemetry.sanitize(self.headers.get("X-Correlation-ID")) or self.request_id
        self._method = method
        self._path = urllib.parse.urlparse(self.path).path
        self._resp_status = None
        self._err_code = None
        t0 = time.perf_counter()
        with telemetry.scope(request=self.request_id, correlation=self.correlation_id):
            try:
                return self._dispatch(method)
            finally:
                self._journal_request(method, (time.perf_counter() - t0) * 1000)

    def _journal_request(self, method: str, duration_ms: float):
        """Одна запись журнала на обращение к API (статика — только при отказе)."""
        try:
            from .. import journal
            path = self._path or ""
            status = self._resp_status or 0
            is_api = path.startswith("/api/") or path == "/metrics"
            if not is_api and status < 400:
                return
            sess = getattr(self, "session", None) or {}
            level = ("error" if status >= 500 else "warn" if status >= 400 else
                     "info" if method != "GET" else "debug")
            qs = dict(getattr(self, "qs", {}) or {})
            rid = qs.pop("research_id", None)
            # путь с идентификаторами сводится к шаблону — иначе действия не группируются
            template = re.sub(r"/(?:res|doc|rep|job|req|aud|ev|rel|bkp|alr|jrn|cid)-[0-9a-zA-Z-]+",
                              "/{id}", path)
            template = re.sub(r"/[0-9a-f]{8}-[0-9a-f-]{20,}", "/{id}", template)
            journal.record(level, "api", f"{method} {template}",
                           message=(self._err_code or "") + (f" HTTP {status}" if status >= 400 else ""),
                           actor=sess.get("login"), role=sess.get("role"),
                           outcome="fail" if status >= 400 else "ok",
                           http_status=status or None, duration_ms=duration_ms,
                           research_id=rid, error_code=self._err_code,
                           detail={"path": path, "query": qs,
                                   "peer": self.client_address[0] if getattr(self, "client_address", None) else "",
                                   "user_agent": self.headers.get("User-Agent", "")[:200]})
        except Exception:
            pass

    def _dispatch(self, method: str):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        self.qs = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        body = {}
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except Exception:
                body = {}
        # --- метрики Prometheus (P6)
        if path == "/metrics" and method == "GET":
            from .metrics import render
            return self._send(200, render().encode("utf-8"), "text/plain; version=0.0.4; charset=utf-8")
        # --- журнал загрузки (выгрузка файлом, без аутентификации)
        if path == "/api/v1/boot-log/export" and method == "GET":
            from .. import boot
            fmt = (self.qs.get("fmt") or "txt").lower()
            if fmt not in ("txt", "json"):
                fmt = "txt"
            data = boot.export(fmt).encode("utf-8")
            ctype = "application/json; charset=utf-8" if fmt == "json" else "text/plain; charset=utf-8"
            return self._send(200, data, ctype,
                              {"Content-Disposition": f'attachment; filename="boot-log.{fmt}"'})
        # --- SSE
        if path == "/api/v1/events/stream" and method == "GET":
            return self._sse()
        # --- файлы отчётов
        mfile = re.match(r"^/api/v1/reports/([^/]+)/file$", path)
        if mfile and method == "GET":
            return self._report_file(mfile.group(1))
        # --- экспорт журнала
        if path == "/api/v1/logs/export" and method == "GET":
            return self._logs_export()
        # --- выгрузка журнала действий файлом (ред. 1.4.0)
        if path == "/api/v1/journal/export" and method == "GET":
            return self._journal_export()
        # --- API
        if path.startswith("/api/"):
            for meth, pat, fn in ROUTES:
                if meth != method:
                    continue
                m = pat.match(path)
                if not m:
                    continue
                try:
                    self.session = None
                    if path not in PUBLIC_PATHS:
                        auth = self.headers.get("Authorization") or ""
                        token = auth[7:] if auth.startswith("Bearer ") else self.qs.get("token")
                        self.session = S.session(token)
                    result = fn(self, m, body)
                    return self._json(200, result)
                except CoreError as e:
                    return self._err(e)
                except Exception as e:  # noqa: BLE001
                    return self._err(e)
            return self._json(404, {"error": {"code": "E_NOT_FOUND", "message": f"Маршрут не найден: {method} {path}"}})
        # --- статика UI
        return self._static(path)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_DELETE(self):
        self._handle("DELETE")

    def do_OPTIONS(self):
        self._send(204, b"", "text/plain", {"Allow": "GET, POST, DELETE, OPTIONS"})

    # -------------------------------------------------- special responses
    def _sse(self):
        token = self.qs.get("token")
        try:
            S.session(token)
        except CoreError as e:
            return self._err(e)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = events.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            for chunk in events.stream(q):
                rid = self.qs.get("research_id")
                if rid and '"research_id": "' + rid not in chunk and '"research_id": null' not in chunk:
                    continue
                self.wfile.write(chunk.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, GeneratorExit):
            pass
        finally:
            events.unsubscribe(q)

    def _report_file(self, report_id: str):
        try:
            auth = self.headers.get("Authorization") or ""
            token = auth[7:] if auth.startswith("Bearer ") else self.qs.get("token")
            sess = S.session(token)
            S.require(sess, "research.read")
            path = S.report_file(report_id, self.qs.get("fmt", "html"))
        except CoreError as e:
            return self._err(e)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if path.endswith(".csv"):
            ctype = "text/csv; charset=utf-8"
        with open(path, "rb") as f:
            data = f.read()
        self._send(200, data, ctype, {"Content-Disposition": f'inline; filename="{os.path.basename(path)}"'})

    def _journal_export(self):
        """Выгрузка журнала действий: TXT / JSON / CSV с теми же фильтрами, что и экран."""
        try:
            auth = self.headers.get("Authorization") or ""
            token = auth[7:] if auth.startswith("Bearer ") else self.qs.get("token")
            sess = S.session(token)
            S.require(sess, "logs.read")
            q = self.qs
            fmt = (q.get("fmt") or "txt").lower()
            if fmt not in ("txt", "json", "csv"):
                fmt = "txt"
            text = S.journal_export(fmt, level=q.get("level"), kind=q.get("kind"),
                                    actor=q.get("actor"), source=q.get("source"),
                                    research_id=q.get("research_id"),
                                    correlation_id=q.get("cid"), q=q.get("q"),
                                    since=q.get("since"), until=q.get("until"),
                                    fingerprint_=q.get("fingerprint"),
                                    limit=int(q.get("limit", "5000")))
        except CoreError as e:
            return self._err(e)
        ctype = {"json": "application/json; charset=utf-8",
                 "csv": "text/csv; charset=utf-8"}.get(fmt, "text/plain; charset=utf-8")
        return self._send(200, text.encode("utf-8"), ctype,
                          {"Content-Disposition": f'attachment; filename="journal.{fmt}"'})

    def _logs_export(self):
        try:
            auth = self.headers.get("Authorization") or ""
            token = auth[7:] if auth.startswith("Bearer ") else self.qs.get("token")
            sess = S.session(token)
            S.require(sess, "logs.read")
            fmt = self.qs.get("fmt", "json")
            text = S.logs_export(self.qs.get("research_id"), fmt)
        except CoreError as e:
            return self._err(e)
        ctype = {"json": "application/json; charset=utf-8", "csv": "text/csv; charset=utf-8"}.get(fmt, "text/plain; charset=utf-8")
        self._send(200, text.encode("utf-8"), ctype,
                   {"Content-Disposition": f'attachment; filename="isheika-log.{fmt if fmt != "txt" else "txt"}"'})

    def _static(self, path: str):
        rel = static_target(path)
        if rel is None:
            return self._json(403, {"error": {"code": "E_FORBIDDEN",
                                              "message": "Недопустимый путь к ресурсу"}})
        full = os.path.join(WEB_DIR, *rel.split("/"))
        if not os.path.isfile(full):
            # Ресурс с расширением обязан существовать: подстановка index.html
            # вместо .js/.css давала «белый экран» без единой ошибки в консоли.
            if "." in rel.rsplit("/", 1)[-1]:
                return self._json(404, {"error": {"code": "E_NOT_FOUND",
                                                  "message": f"Ресурс интерфейса не найден: {rel}"}})
            full = os.path.join(WEB_DIR, "index.html")
            if not os.path.isfile(full):
                return self._json(404, {"error": {"code": "E_NOT_FOUND", "message": "UI не собран"}})
        with open(full, "rb") as f:
            data = f.read()
        self._send(200, data, static_ctype(full))


class Server(ThreadingHTTPServer):
    """HTTP-сервер с понятным отказом при исчерпании ресурсов ОС.

    Без этого исчерпание лимита потоков приводило к обрыву соединения без
    ответа — браузер показывал пустой экран без причины. Теперь возвращается
    503 с текстом ошибки, а отказ попадает в журнал загрузки.
    """

    daemon_threads = True

    def process_request(self, request, client_address):
        try:
            return super().process_request(request, client_address)
        except RuntimeError as exc:
            from .. import boot
            boot.record("Отказ обработки запроса", "fail", f"{type(exc).__name__}: {exc}")
            payload = json.dumps({"error": {"code": "E_STATE",
                                            "message": f"Сервер перегружен: {exc}. Повторите запрос."}},
                                 ensure_ascii=False).encode("utf-8")
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\n"
                                b"Content-Type: application/json; charset=utf-8\r\n"
                                b"Connection: close\r\nContent-Length: " + str(len(payload)).encode()
                                + b"\r\n\r\n" + payload)
            except Exception:
                pass
            self.shutdown_request(request)


def serve(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    from .. import boot
    from ..storage import db
    from ..registry import loader
    with boot.step("Конфигурация") as info:
        info["detail"] = (f"профиль {SETTINGS.profile}, сеть {'вкл' if SETTINGS.network_enabled else 'выкл'}, "
                          f"платный ИИ {'разрешён' if SETTINGS.allow_paid_ai else 'запрещён'}")
    with boot.step("Каталоги данных") as info:
        SETTINGS.ensure_dirs()
        info["detail"] = SETTINGS.data_dir if hasattr(SETTINGS, "data_dir") else ""
    with boot.step("База данных и миграции") as info:
        db.init_db()
        info["detail"] = ", ".join(r["version"] for r in db.query("SELECT version FROM meta_migrations ORDER BY version"))
    with boot.step("Реестры источников и методик") as info:
        loader.seed_all()
        info["detail"] = (f"источников {db.count('registry_sources')}, стран {db.count('dict_countries')}, "
                          f"коннекторов {db.count('registry_connectors')}")
    with boot.step("Обработчики этапов") as info:
        from ..workflow import pipeline  # noqa: F401  регистрация обработчиков этапов
        info["detail"] = "workflow.pipeline импортирован"
    with boot.step("Ресурсы интерфейса") as info:
        assets = boot.ui_assets()
        bad = [a["asset"] for a in assets if not a["ok"]]
        info["detail"] = f"проверено {len(assets)}" + (("; ОТСУТСТВУЮТ: " + ", ".join(bad)) if bad else "")
        if bad:
            raise CoreError("E_STATE", "Ресурсы интерфейса отсутствуют: " + ", ".join(bad))
    with boot.step("Маршруты API") as info:
        info["detail"] = f"{len(ROUTES)} маршрутов"
    with boot.step("Привязка порта") as info:
        httpd = Server((host or SETTINGS.host, port or SETTINGS.port), Handler)
        httpd.daemon_threads = True
        info["detail"] = f"{httpd.server_address[0]}:{httpd.server_address[1]}"
    return httpd


def serve_auto(host: str | None = None, port: int | None = None, *,
               port_auto: bool = False, attempts: int = 20) -> ThreadingHTTPServer:
    """Запуск сервера с поиском свободного порта (единый файл запуска, ROADMAP).

    Без port_auto занятый порт — ошибка с понятным сообщением; с port_auto
    перебираются следующие порты. Возвращает уже связанный сервер.
    """
    base = port or SETTINGS.port
    last: OSError | None = None
    for attempt in range(attempts if port_auto else 1):
        try:
            return serve(host=host, port=base + attempt)
        except OSError as e:
            last = e
    raise CoreError("E_STATE", f"Не удалось занять порт {base}"
                    + (f"–{base + attempts - 1}" if port_auto else "")
                    + f": {last}. Закройте другую копию программы или укажите порт: --port 8080")


def start_slo_scheduler(interval: int | None = None) -> "threading.Thread | None":
    """Фоновые самопроверки доступности и пересчёт правил (ROADMAP P6).

    Поток демон: он не удерживает процесс при остановке сервера. Любой сбой
    наблюдения подавляется — эксплуатационное наблюдение не должно ронять
    предметную работу. Отключается SETTINGS.slo_scheduler = False.
    """
    if not getattr(SETTINGS, "slo_scheduler", True):
        return None
    from .. import slo

    period = int(interval or slo.PROBE_INTERVAL_SEC)

    def _loop():
        from .. import journal
        cycles = 0
        while True:
            try:
                slo.tick()
            except Exception as exc:  # noqa: BLE001
                try:
                    journal.error(exc, "system", "slo.tick", source="scheduler",
                                  message="Сбой цикла эксплуатационного наблюдения")
                except Exception:
                    pass
            cycles += 1
            # Политика хранения журнала: ротация раз в час, а не на каждой записи.
            if cycles % max(1, int(3600 / max(1, period))) == 0:
                try:
                    res = journal.prune()
                    if res["removed_by_age"] or res["removed_by_cap"]:
                        journal.record("info", "system", "journal.prune", source="scheduler",
                                       message=f"Удалено по сроку: {res['removed_by_age']}, "
                                               f"по объёму: {res['removed_by_cap']}", detail=res)
                except Exception:
                    pass
            time.sleep(period)

    th = threading.Thread(target=_loop, name="slo-scheduler", daemon=True)
    th.start()
    return th


def main(*, open_browser: bool = False, port_auto: bool = False) -> int:
    from ..config import configure_console
    configure_console()
    httpd = serve_auto(port=SETTINGS.port, port_auto=port_auto)
    start_slo_scheduler()
    host, bound = httpd.server_address[:2]
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{bound}/"
    print(f"ИЩЕЙКА НТР AI · профиль {SETTINGS.profile} · {url}", flush=True)
    from .. import boot
    boot.record("Планировщик самопроверок", "ok" if getattr(SETTINGS, "slo_scheduler", True) else "off",
                "шаг 60 с" if getattr(SETTINGS, "slo_scheduler", True) else "отключён")
    print(boot.console_report(), flush=True)
    files = boot.write_files()
    if files.get("txt"):
        print(f"Журнал загрузки: {files['txt']}", flush=True)
    print(f"Диагностика в браузере: {url}api/v1/boot-log", flush=True)
    if open_browser:
        import threading
        import webbrowser

        def _open():
            try:
                webbrowser.open(url)
            except Exception:
                print(f"Откройте интерфейс вручную: {url}", flush=True)
        threading.Timer(1.0, _open).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
