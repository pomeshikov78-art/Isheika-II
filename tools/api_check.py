#!/usr/bin/env python3
"""TOOL-03. Проверка HTTP-транспорта и маршрутов API (ТЗ-05 §9, ТЗ-06 §7).

    python3 tools/api_check.py --base http://127.0.0.1:8000

Проверяет: аутентификацию, RBAC, статику UI, все группы маршрутов, SSE,
выдачу файлов отчёта и экспорт журнала. Печатает таблицу «маршрут → код».
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token = None

    def call(self, method: str, path: str, body=None, expect=200, raw=False):
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = r.read()
                code = r.status
                ctype = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            payload = e.read()
            code = e.code
            ctype = e.headers.get("Content-Type", "")
        ok = code == expect
        if raw:
            return ok, code, len(payload), ctype
        try:
            obj = json.loads(payload.decode("utf-8"))
        except Exception:
            obj = {"_raw": payload[:120].decode("utf-8", "replace")}
        return ok, code, obj, ctype


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--login", default="analyst")
    ap.add_argument("--password", default=None)
    ap.add_argument("--run", action="store_true", help="полный цикл: создать исследование, выполнить, собрать отчёт")
    ap.add_argument("--query", default="тропосферная связь за горизонтом")
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--wait", type=int, default=240)
    args = ap.parse_args()
    c = Client(args.base)
    results: list[tuple[bool, str, int, str]] = []

    rights: set[str] = set()

    def need(right):
        """Ожидаемый код с учётом RBAC текущей роли."""
        return 200 if ("*" in rights or right in rights) else 403

    def check(name, method, path, body=None, expect=200, raw=False, right=None):
        if right:
            expect = need(right)
        ok, code, obj, ctype = c.call(method, path, body, expect, raw)
        note = ""
        if isinstance(obj, dict) and "error" in obj:
            note = obj["error"].get("code", "") + ": " + str(obj["error"].get("message"))[:70]
        elif isinstance(obj, dict):
            note = ", ".join(list(obj.keys())[:5])
        elif isinstance(obj, int):
            note = f"{obj} байт {ctype.split(';')[0]}"
        results.append((ok, f"{method} {name}", code, note))
        return obj

    # --- статика UI
    for f in ("/", "/styles.css", "/app.js", "/charts.js", "/screens_core.js", "/screens_registry.js", "/screens_v11.js"):
        check(f, "GET", f, raw=True)

    # --- аутентификация и RBAC
    check("auth/login (неверный пароль)", "POST", "/api/v1/auth/login",
          {"login": args.login, "password": "wrong"}, expect=401)
    d = check("auth/login", "POST", "/api/v1/auth/login",
              {"login": args.login, "password": args.password or "dev:" + args.login})
    c.token = d.get("token") if isinstance(d, dict) else None
    rights.update((d.get("user", {}) or {}).get("rights", []) if isinstance(d, dict) else [])
    if not c.token:
        print("Не удалось войти — дальнейшие проверки бессмысленны")
        return 1
    check("auth/me", "GET", "/api/v1/auth/me")
    check("settings", "GET", "/api/v1/settings", right="settings.read")

    # --- система и реестры
    sysd = check("system", "GET", "/api/v1/system")
    check("methodology", "GET", "/api/v1/methodology")
    check("system/dashboard", "GET", "/api/v1/system/dashboard", right="research.read")
    check("countries", "GET", "/api/v1/countries")
    check("sources", "GET", "/api/v1/sources?limit=5", right="registry.read")
    check("sources/stats", "GET", "/api/v1/sources/stats", right="registry.read")
    check("connectors", "GET", "/api/v1/connectors", right="registry.read")
    check("registry/changelog", "GET", "/api/v1/registry/changelog", right="registry.read")
    check("users", "GET", "/api/v1/users", right="settings.read")

    # --- ИИ
    check("ai/providers", "GET", "/api/v1/ai/providers", right="ai.read")
    check("ai/agents", "GET", "/api/v1/ai/agents", right="ai.read")
    check("ai/route", "GET", "/api/v1/ai/route?task_class=tech_analysis", right="ai.read")
    check("queries/preview", "POST", "/api/v1/queries/preview", {"query": "тропосферная связь"}, right="research.read")

    # --- исследование
    rid = None
    lst = check("researches", "GET", "/api/v1/researches?limit=5", right="research.read")
    if isinstance(lst, dict) and lst.get("items"):
        rid = lst["items"][0]["id"]
    if not rid:
        created = check("researches (создание)", "POST", "/api/v1/researches",
                        {"query": "тропосферная связь за горизонтом", "title": "API-проверка", "countries": ["RU", "US"]},
                        right="research.write")
        rid = created.get("id") if isinstance(created, dict) else None
    if rid:
        check("researches/{id}", "GET", f"/api/v1/researches/{rid}")
        check("researches/{id}/status", "GET", f"/api/v1/researches/{rid}/status")
        check("documents", "GET", f"/api/v1/documents?research_id={rid}&limit=5")
        check("analytics", "GET", f"/api/v1/analytics/{rid}", right="analytics.read")
        check("passport", "GET", f"/api/v1/technologies/{rid}/passport", right="analytics.read")
        check("claims", "GET", f"/api/v1/claims?research_id={rid}")
        check("evidence", "GET", f"/api/v1/evidence?research_id={rid}")
        check("forecasts", "GET", f"/api/v1/forecasts/{rid}", right="analytics.read")
        check("ai-tasks", "GET", f"/api/v1/ai-tasks?research_id={rid}", right="ai.read")
        check("reports", "GET", f"/api/v1/reports?research_id={rid}")
        check("logs", "GET", f"/api/v1/logs?research_id={rid}&limit=20", right="logs.read")
        check("events", "GET", f"/api/v1/events?research_id={rid}&limit=20")
        reps = c.call("GET", f"/api/v1/reports?research_id={rid}")[2]
        if isinstance(reps, dict) and reps.get("items"):
            r0 = reps["items"][0]
            for fmt in list((r0.get("files") or {}).keys())[:3]:
                check(f"reports/file?fmt={fmt}", "GET", f"/api/v1/reports/{r0['id']}/file?fmt={fmt}", raw=True, right="research.read")
        check("logs/export", "GET", f"/api/v1/logs/export?research_id={rid}&fmt=csv", raw=True, right="logs.read")
        # --- каталог v1.1 (ИД-04) и новые ресурсы
        check("search-tasks", "GET", f"/api/v1/search-tasks?research_id={rid}")
        check("search-results", "GET", f"/api/v1/search-results?research_id={rid}&limit=5")
        check("technologies", "GET", f"/api/v1/technologies?research_id={rid}", right="analytics.read")
        check("trl-assessments", "GET", f"/api/v1/trl-assessments?research_id={rid}", right="analytics.read")
        check("trl-criteria", "GET", "/api/v1/trl-criteria", right="analytics.read")
        check("feasibility-assessments", "GET", f"/api/v1/feasibility-assessments?research_id={rid}", right="analytics.read")
        check("confidence-assessments", "GET", f"/api/v1/confidence-assessments?research_id={rid}", right="analytics.read")
        check("forecasts (коллекция)", "GET", f"/api/v1/forecasts?research_id={rid}", right="analytics.read")
        check("methodologies", "GET", "/api/v1/methodologies", right="analytics.read")
        check("methodologies/RELEVANCE_V1", "GET", "/api/v1/methodologies/RELEVANCE_V1", right="analytics.read")
        check("document-clusters", "GET", f"/api/v1/document-clusters?research_id={rid}")
        check("document-relations", "GET", f"/api/v1/document-relations?research_id={rid}")
        check("independence-groups", "GET", f"/api/v1/independence-groups?research_id={rid}", right="analytics.read")
        check("research-runs", "GET", f"/api/v1/research-runs?research_id={rid}")
        # --- ROADMAP P4/P6: граф связей, сравнение версий, трассировка
        check("document-graph", "GET", f"/api/v1/document-graph?research_id={rid}")
        check("document-graph (фильтр типов)", "GET",
              f"/api/v1/document-graph?research_id={rid}&types=PREPRINT_OF,TRANSLATION_OF")
        fea_h = c.call("GET", f"/api/v1/feasibility-assessments?research_id={rid}")[2]
        hist = (fea_h or {}).get("history") or []
        if len(hist) >= 2:
            check("assessments/diff", "GET",
                  f"/api/v1/assessments/diff?kind=feasibility&a={hist[0]['id']}&b={hist[1]['id']}",
                  right="analytics.read")
        else:
            latest = (fea_h or {}).get("latest") or {}
            if latest.get("id"):
                check("assessments/diff (само-сравнение)", "GET",
                      f"/api/v1/assessments/diff?kind=feasibility&a={latest['id']}&b={latest['id']}",
                      right="analytics.read")
        ev = c.call("GET", f"/api/v1/events?research_id={rid}&limit=5")[2]
        cid = next((e.get("correlation_id") for e in (ev or {}).get("items", []) if e.get("correlation_id")), None)
        if cid:
            check("trace/{correlation_id}", "GET", f"/api/v1/trace/{cid}", right="logs.read")
        check("trace (некорректный id) → 422", "GET", "/api/v1/trace/bad%20id",
              expect=422 if need("logs.read") == 200 else 403)
        # заголовок трассировки пробрасывается обратно
        req = urllib.request.Request(c.base + "/api/v1/system")
        req.add_header("X-Request-ID", "req-apicheck-0001")
        req.add_header("X-Correlation-ID", "cid-apicheck-0001")
        with urllib.request.urlopen(req, timeout=30) as r:
            hdr_ok = r.headers.get("X-Request-ID") == "req-apicheck-0001" and \
                     r.headers.get("X-Correlation-ID") == "cid-apicheck-0001"
        results.append((hdr_ok, "заголовки X-Request-ID / X-Correlation-ID", 200,
                        "проброшены" if hdr_ok else "не проброшены"))
        check("openapi.json", "GET", "/api/v1/openapi.json")
        check("metrics (Prometheus)", "GET", "/metrics", raw=True)
        # --- ИД-04: устаревший маршрут обязан вернуть 410 Gone
        check("legacy /api/v1/research → 410", "GET", "/api/v1/research", expect=410)

    # --- полный цикл через HTTP (создание → запуск → ожидание → отчёт)
    if args.run:
        created = check("researches (создание, --run)", "POST", "/api/v1/researches",
                        {"query": args.query, "title": "E2E " + args.query,
                         "settings": {"max_docs_per_source": args.limit}}, right="research.write")
        rid = created.get("id") if isinstance(created, dict) else None
        if rid:
            check("researches/start", "POST", f"/api/v1/researches/{rid}/start", {}, right="research.run")
            t0 = time.time()
            state = "?"
            while time.time() - t0 < args.wait:
                time.sleep(4)
                st = c.call("GET", f"/api/v1/researches/{rid}/status")[2]
                if not isinstance(st, dict):
                    break
                jobs = st.get("jobs", [])
                done = sum(1 for j in jobs if j["status"] in ("completed", "failed", "cancelled", "partial"))
                state = st["research"]["status"]
                print(f"  … {int(time.time() - t0)} с: этапов {done}/{len(jobs)}, статус {state}", flush=True)
                if not st.get("running") and done == len(jobs):
                    break
            results.append((state in ("completed", "partial"), "полный цикл исследования", 200,
                            f"итоговый статус: {state}"))
            check("analytics (после прогона)", "GET", f"/api/v1/analytics/{rid}", right="analytics.read")
            check("recompute", "POST", f"/api/v1/analytics/{rid}/recompute", {}, right="analytics.write")
            rep = check("reports (генерация)", "POST", "/api/v1/reports", {"research_id": rid}, right="report.write")
            if isinstance(rep, dict) and rep.get("files"):
                for fmt in rep["files"]:
                    check(f"reports/file?fmt={fmt}", "GET", f"/api/v1/reports/{rep['report_id']}/file?fmt={fmt}", raw=True, right="research.read")

    # --- ошибки валидации и несуществующие объекты
    check("researches (пустой запрос) → 422", "POST", "/api/v1/researches", {"query": ""},
          expect=422 if need("research.write") == 200 else 403)
    check("несуществующее исследование → 404", "GET", "/api/v1/researches/res-does-not-exist", expect=404)
    check("несуществующий маршрут → 404", "GET", "/api/v1/nope", expect=404)

    # --- анонимный доступ
    anon = Client(args.base)
    ok, code, obj, _ = anon.call("GET", "/api/v1/researches", expect=401)
    results.append((code == 401, "GET researches без токена", code, "ожидается 401"))

    # --- SSE
    sse_ok, sse_note = False, "нет данных"
    try:
        req = urllib.request.Request(args.base + "/api/v1/events/stream?token=" + c.token)
        with urllib.request.urlopen(req, timeout=8) as r:
            t0 = time.time()
            while time.time() - t0 < 3:
                line = r.readline().decode("utf-8", "replace")
                if line.startswith(":") or line.startswith("data:"):
                    sse_ok, sse_note = True, line.strip()[:60]
                    break
    except Exception as e:
        sse_note = str(e)[:70]
    results.append((sse_ok, "GET events/stream (SSE)", 200 if sse_ok else 0, sse_note))

    width = max(len(n) for _, n, _, _ in results)
    passed = 0
    for ok, name, code, note in results:
        passed += bool(ok)
        print(f'{"OK " if ok else "FAIL"} {name.ljust(width)}  {code}  {note}')
    print(f"\nИтого: {passed}/{len(results)} проверок пройдено")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
