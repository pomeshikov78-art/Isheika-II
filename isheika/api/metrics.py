"""Метрики для системы наблюдения (ROADMAP P6, формат Prometheus 0.0.4).

Экспортируются: состояние исследований и этапов, длительности этапов, доля
partial, счётчики квот, здоровье коннекторов и провайдеров, объём данных.
Значения берутся из БД — метрики не изменяют предметное состояние.
"""
from __future__ import annotations

from ..storage import db


def _esc(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"')


def render() -> str:
    lines: list[str] = []

    def metric(name: str, help_text: str, mtype: str, samples: list[tuple[dict, float]]):
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} {mtype}")
        for labels, value in samples:
            if labels:
                lbl = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
                lines.append(f"{name}{{{lbl}}} {value}")
            else:
                lines.append(f"{name} {value}")

    metric("isheika_researches", "Число исследований по статусам", "gauge",
           [({"status": r["status"]}, r["n"]) for r in
            db.query("SELECT status, COUNT(*) AS n FROM core_researches GROUP BY status")])
    metric("isheika_workflow_jobs", "Этапы workflow по статусам", "gauge",
           [({"stage": r["stage"], "status": r["status"]}, r["n"]) for r in
            db.query("SELECT stage, status, COUNT(*) AS n FROM workflow_jobs GROUP BY stage, status")])
    metric("isheika_documents_total", "Логические документы (глобально)", "gauge",
           [({}, db.count("content_documents"))])
    metric("isheika_document_occurrences_total", "Вхождения документов в источниках", "gauge",
           [({}, db.count("content_occurrences"))])
    metric("isheika_document_clusters_total", "Кластеры связанных документов", "gauge",
           [({}, db.count("content_clusters"))])
    metric("isheika_search_results", "Результаты оценки по классам релевантности", "gauge",
           [({"class": r["relevance_class"]}, r["n"]) for r in
            db.query("SELECT relevance_class, COUNT(*) AS n FROM search_results GROUP BY relevance_class")])
    metric("isheika_ai_requests", "Вызовы ИИ по состояниям", "gauge",
           [({"state": r["state"], "simulated": str(bool(r["simulated"]))}, r["n"]) for r in
            db.query("SELECT state, simulated, COUNT(*) AS n FROM ai_requests GROUP BY state, simulated")])
    metric("isheika_ai_latency_ms_avg", "Средняя задержка ответа провайдера, мс", "gauge",
           [({"provider": r["provider_id"] or "unknown"}, round(r["ms"] or 0, 1)) for r in
            db.query("SELECT provider_id, AVG(latency_ms) AS ms FROM ai_requests GROUP BY provider_id")])
    metric("isheika_connectors_health", "Состояние коннекторов (1 = active)", "gauge",
           [({"code": r["code"], "health": r["health_status"]}, 1 if r["health_status"] == "active" else 0)
            for r in db.query("SELECT code, health_status FROM registry_connectors")])
    metric("isheika_quota_used", "Использование квот источников", "counter",
           [({"scope": r["scope"], "key": r["key"], "window": r["window"]}, r["used"]) for r in
            db.query("""SELECT scope, key, window, SUM(used) AS used FROM audit_quota_usage
                        GROUP BY scope, key, window""")])
    metric("isheika_evidence_items", "Доказательства по происхождению", "gauge",
           [({"origin": r["origin_class"]}, r["n"]) for r in
            db.query("SELECT origin_class, COUNT(*) AS n FROM evidence_items GROUP BY origin_class")])
    metric("isheika_independence_groups", "Группы независимости доказательств", "gauge",
           [({}, db.count("evidence_independence_groups"))])
    metric("isheika_methodologies", "Версии методик по статусу утверждения", "gauge",
           [({"code": r["code"], "approval": r["approval_status"]}, 1) for r in
            db.query("SELECT code, approval_status FROM analytics_methodologies WHERE is_active=1")])
    metric("isheika_forecast_points", "Точки прогноза по режиму представления", "gauge",
           [({"mode": r["display_mode"]}, r["n"]) for r in
            db.query("SELECT display_mode, COUNT(*) AS n FROM forecast_points GROUP BY display_mode")])
    metric("isheika_workflow_stage_duration_ms_avg", "Средняя длительность этапа, мс", "gauge",
           [({"stage": r["stage"]}, round(r["ms"] or 0, 1)) for r in
            db.query("""SELECT stage, AVG(duration_ms) AS ms FROM workflow_jobs
                        WHERE duration_ms IS NOT NULL GROUP BY stage""")])
    metric("isheika_workflow_stage_duration_ms_max", "Максимальная длительность этапа, мс", "gauge",
           [({"stage": r["stage"]}, r["ms"] or 0) for r in
            db.query("""SELECT stage, MAX(duration_ms) AS ms FROM workflow_jobs
                        WHERE duration_ms IS NOT NULL GROUP BY stage""")])
    jp = db.one("""SELECT SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END) AS p, COUNT(*) AS n
                   FROM workflow_jobs WHERE status IN ('completed','partial','failed')""") or {}
    metric("isheika_workflow_partial_share", "Доля этапов со статусом partial", "gauge",
           [({}, round((jp.get("p") or 0) / jp["n"], 4) if jp.get("n") else 0.0)])
    metric("isheika_traced_events_total", "События с идентификатором трассировки", "counter",
           [({}, db.count("workflow_events", "correlation_id IS NOT NULL"))])
    metric("isheika_api_calls_duration_ms_avg", "Средняя длительность вызова внешнего API, мс", "gauge",
           [({"target": r["target"]}, round(r["ms"] or 0, 1)) for r in
            db.query("SELECT target, AVG(duration_ms) AS ms FROM audit_api_calls GROUP BY target")])
    partial = db.one("""SELECT SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END) AS p, COUNT(*) AS n
                        FROM core_researches WHERE status IN ('completed','partial','failed')""") or {}
    share = (partial.get("p") or 0) / partial["n"] if partial.get("n") else 0.0
    metric("isheika_research_partial_share", "Доля исследований со статусом partial", "gauge",
           [({}, round(share, 4))])

    # --- ROADMAP P6 (ред. 1.3): SLO доступности, алерты, резервные копии ---
    from .. import slo
    metric("isheika_slo_target", "Целевая доступность, %", "gauge", [({}, slo.TARGET_AVAILABILITY)])
    metric("isheika_slo_availability", "Доступность по самопроверкам, %", "gauge",
           [({"window": name}, st["availability_pct"]) for name, hours in slo.WINDOWS
            for st in [slo.window_stats(hours)] if st["availability_pct"] is not None])
    metric("isheika_slo_error_budget_used", "Израсходовано бюджета ошибок, %", "gauge",
           [({"window": name}, st["error_budget_used_pct"]) for name, hours in slo.WINDOWS
            for st in [slo.window_stats(hours)] if st["error_budget_used_pct"] is not None])
    metric("isheika_slo_probes_total", "Самопроверки по компонентам и результату", "counter",
           [({"component": r["component"], "ok": str(bool(r["ok"]))}, r["n"]) for r in
            db.query("SELECT component, ok, COUNT(*) AS n FROM service_probes GROUP BY component, ok")])
    metric("isheika_slo_probe_latency_ms_avg", "Средняя длительность самопроверки, мс", "gauge",
           [({"component": r["component"]}, round(r["ms"] or 0, 3)) for r in
            db.query("SELECT component, AVG(latency_ms) AS ms FROM service_probes GROUP BY component")])
    metric("isheika_alerts_open", "Открытые алерты эксплуатации", "gauge",
           [({"rule": r["rule_code"], "severity": r["severity"]}, r["n"]) for r in
            db.query("""SELECT rule_code, severity, COUNT(*) AS n FROM ops_alerts
                        WHERE state<>'closed' GROUP BY rule_code, severity""")])
    metric("isheika_backups_total", "Резервные копии по типу", "counter",
           [({"kind": r["kind"] or "manual"}, r["n"]) for r in
            db.query("SELECT kind, COUNT(*) AS n FROM ops_backups GROUP BY kind")])
    return "\n".join(lines) + "\n"
