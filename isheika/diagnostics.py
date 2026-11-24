"""Поиск противоречий и дефектов по журналу и состоянию системы (ред. 1.4.0).

Журнал отвечает на вопрос «что происходило». Этот модуль отвечает на вопрос
«что из произошедшего противоречит правилам предметной области» — то есть ищет
не только упавшие операции, но и тихие расхождения, которые не дают ошибки:

* состояние против автомата и против этапов (исследование «completed» с проваленными этапами);
* расчёт против методики (класс релевантности не по порогу, TRL выше подтверждённого,
  неизвестный фактор учтён как ноль, немонотонный прогноз, количественный прогноз за 20 лет);
* доказательство против утверждения (SUPPORTED без доказательств, чужое исследование);
* политика против факта (платный ИИ при запрете, превышение квоты, секрет в журнале);
* повторяемость (одна подпись дефекта много раз — это баг, а не случайность).

Правила только читают данные. Каждое найденное противоречие сопровождается
числом случаев, конкретными идентификаторами (evidence) и рекомендацией.
"""
from __future__ import annotations

import os

from . import journal
from .config import SETTINGS
from .contracts import iso_now
from .storage import db

SEVERITY_ORDER = {"critical": 0, "error": 1, "warn": 2, "info": 3}


def _finding(code: str, severity: str, title: str, detail: str, count: int,
             evidence: list, recommendation: str, research_id: str | None = None) -> dict:
    return {"code": code, "severity": severity, "title": title, "detail": detail,
            "count": int(count), "evidence": evidence[:10], "recommendation": recommendation,
            "research_id": research_id}


def _scope(research_id: str | None, column: str = "research_id") -> tuple[str, list]:
    return (f" AND {column}=?", [research_id]) if research_id else ("", [])


# ------------------------------------------------------------------ правила
def rule_states(research_id=None) -> list[dict]:
    """DIA-01. Состояние исследования против фактического состояния этапов."""
    out = []
    sc, pr = _scope(research_id)
    rows = db.query("""SELECT r.id, r.status,
                              SUM(CASE WHEN j.status='failed' THEN 1 ELSE 0 END) AS failed,
                              SUM(CASE WHEN j.status IN ('queued','running','retry_wait') THEN 1 ELSE 0 END) AS active,
                              COUNT(j.id) AS jobs
                       FROM core_researches r LEFT JOIN workflow_jobs j ON j.research_id=r.id
                       WHERE 1=1""" + sc + " GROUP BY r.id", pr)
    bad_complete = [r for r in rows if r["status"] == "completed" and (r["failed"] or 0) > 0]
    if bad_complete:
        out.append(_finding("DIA-01a", "error", "Исследование «completed» с проваленными этапами",
                            "По ТЗ-01 итог при отказе части этапов — partial, а не completed.",
                            len(bad_complete),
                            [{"research_id": r["id"], "failed_jobs": r["failed"]} for r in bad_complete],
                            "Пересчитать итог исследования (workflow.engine) и проверить обработку отказов этапов."))
    stuck = [r for r in rows if r["status"] == "running" and (r["active"] or 0) == 0 and (r["jobs"] or 0) > 0]
    if stuck:
        out.append(_finding("DIA-01b", "warn", "Исследование «running» без активных заданий",
                            "Состояние не сходится с этапами: запуск оборвался или поток завершён без перевода состояния.",
                            len(stuck), [{"research_id": r["id"], "jobs": r["jobs"]} for r in stuck],
                            "Открыть журнал по исследованию (kind=workflow) и продолжить запуск (resume)."))
    stale = db.query("""SELECT id, research_id, stage, started_at FROM workflow_jobs
                        WHERE status='running' AND started_at IS NOT NULL
                          AND started_at < datetime('now', '-30 minutes')""" + sc.replace("research_id", "research_id"), pr)
    if stale:
        out.append(_finding("DIA-01c", "warn", "Задание «running» дольше 30 минут",
                            "Признак зависшего этапа: нет ни завершения, ни отказа.",
                            len(stale), [{"job_id": r["id"], "stage": r["stage"], "started_at": r["started_at"]} for r in stale],
                            "Проверить этап в журнале (kind=workflow) и перезапустить исследование с продолжением."))
    return out


def rule_transitions(research_id=None) -> list[dict]:
    """DIA-02. Переходы состояний против конечных автоматов (ТЗ-05 §9)."""
    from .states import FSMS
    rows = db.query("""SELECT id, entity_kind, entity_id, from_state, to_state, created_at
                       FROM core_state_history ORDER BY created_at DESC LIMIT 3000""")
    bad = []
    for r in rows:
        fsm = FSMS.get(r["entity_kind"])
        if not fsm or not r["from_state"] or r["from_state"] == r["to_state"]:
            continue
        if r["to_state"] not in fsm.get(r["from_state"], set()):
            bad.append(r)
    if not bad:
        return []
    return [_finding("DIA-02", "error", "Переход состояния запрещён автоматом",
                     "Запись истории состояний противоречит конечному автомату: переход выполнен в обход assert_transition.",
                     len(bad), [{"entity": f"{r['entity_kind']}:{r['entity_id']}",
                                 "from": r["from_state"], "to": r["to_state"], "at": r["created_at"]} for r in bad],
                     "Найти место прямого изменения статуса (db.update) и перевести его на states.assert_transition.")]


def rule_report_files(research_id=None) -> list[dict]:
    """DIA-03. Запись отчёта против наличия файлов на диске."""
    sc, pr = _scope(research_id)
    rows = db.query("SELECT id, research_id, title, files FROM reporting_reports WHERE 1=1" + sc, pr)
    bad = []
    for r in rows:
        files = db.dec(r, "files").get("files") or {}
        missing = sorted(f for f, path in files.items() if not os.path.exists(path))
        if missing:
            bad.append({"report_id": r["id"], "research_id": r["research_id"], "missing": missing})
    if not bad:
        return []
    return [_finding("DIA-03", "warn", "Отчёт без файлов на диске",
                     "Запись отчёта сохранена, файлы отсутствуют (перенос состояния, чистка var/files).",
                     len(bad), bad, "Сформировать отчёт заново (M27) — записи и снимок сохранены.")]


def rule_claims(research_id=None) -> list[dict]:
    """DIA-04/05. Утверждения против доказательной базы (ТЗ-03)."""
    out = []
    sc, pr = _scope(research_id, "c.research_id")
    rows = db.query("""SELECT c.id, c.research_id, c.claim_text, c.status, c.produced_by,
                              (SELECT COUNT(*) FROM evidence_items e WHERE e.claim_id=c.id) AS evidence
                       FROM knowledge_claims c WHERE c.status IN ('SUPPORTED','PARTIAL')""" + sc, pr)
    bad = [r for r in rows if not r["evidence"]]
    if bad:
        out.append(_finding("DIA-04", "error", "Утверждение SUPPORTED/PARTIAL без доказательств",
                            "Статус подтверждённости не обеспечен ни одним Evidence — противоречие доказательной модели.",
                            len(bad), [{"claim_id": r["id"], "status": r["status"],
                                        "produced_by": r["produced_by"], "text": (r["claim_text"] or "")[:90]} for r in bad],
                            "Добавить доказательства либо вернуть статус UNVERIFIED; мнение модели доказательством не является."))
    cross_scope, cross_params = _scope(research_id, "e.research_id")
    cross = db.query("""SELECT e.id, e.research_id AS evidence_research, c.research_id AS claim_research,
                               e.claim_id, e.document_id
                        FROM evidence_items e JOIN knowledge_claims c ON c.id=e.claim_id
                        WHERE e.research_id <> c.research_id""" + cross_scope + " LIMIT 50", cross_params)
    if cross:
        out.append(_finding("DIA-05", "error", "Доказательство привязано к чужому исследованию",
                            "Evidence и Claim относятся к разным исследованиям — нарушена изоляция предметных данных.",
                            len(cross), [{"evidence_id": r["id"], "claim_id": r["claim_id"],
                                          "evidence_research": r["evidence_research"],
                                          "claim_research": r["claim_research"]} for r in cross],
                            "Удалить связь и добавить доказательство в рамках своего исследования (E_POLICY)."))
    return out


def rule_relevance(research_id=None) -> list[dict]:
    """DIA-06/07. Релевантность против порогов и полноты компонент (ТЗ-03)."""
    out = []
    sc, pr = _scope(research_id)
    rows = db.query("""SELECT id, research_id, document_id, relevance_score, relevance_class,
                              score_s, score_t, score_c, score_e, score_k, score_f, components
                       FROM search_results WHERE 1=1""" + sc + " ORDER BY created_at DESC LIMIT 4000", pr)
    wrong_class, no_components = [], []
    for r in rows:
        score = r["relevance_score"]
        if score is None:
            continue
        expect = ("DIRECT" if score >= SETTINGS.relevance_direct else
                  "ADJACENT" if score >= SETTINGS.relevance_adjacent else "BELOW_THRESHOLD")
        if r["relevance_class"] != expect:
            wrong_class.append({"result_id": r["id"], "score": score,
                                "class": r["relevance_class"], "expected": expect})
        if any(r[k] is None for k in ("score_s", "score_t", "score_c", "score_e", "score_k", "score_f")):
            no_components.append({"result_id": r["id"], "document_id": r["document_id"]})
    if wrong_class:
        out.append(_finding("DIA-06", "error", "Класс релевантности не соответствует порогу",
                            f"Пороги: DIRECT ≥ {SETTINGS.relevance_direct}, ADJACENT ≥ {SETTINGS.relevance_adjacent}.",
                            len(wrong_class), wrong_class,
                            "Пересчитать релевантность с текущей версией методики; UI не имеет права менять класс."))
    if no_components:
        out.append(_finding("DIA-07", "warn", "Оценка релевантности без всех шести компонент",
                            "ИД-01: все компоненты S/T/C/E/K/F обязаны сохраняться — иначе расчёт невоспроизводим.",
                            len(no_components), no_components,
                            "Пересчитать оценку (search.relevance.assess) и проверить сохранение компонент."))
    return out


def rule_trl(research_id=None) -> list[dict]:
    """DIA-08. TRL против обязательных критериев (усреднение запрещено, ТЗ-03)."""
    sc, pr = _scope(research_id)
    rows = db.query("SELECT id, research_id, trl, criteria FROM analytics_trl WHERE 1=1" + sc
                    + " ORDER BY created_at DESC LIMIT 500", pr)
    bad = []
    for r in rows:
        criteria = db.dec(r, "criteria").get("criteria") or []
        if not criteria:
            continue
        ok_levels = set()
        for lvl in range(1, 10):
            mandatory = [c for c in criteria if int(c.get("level", 0)) == lvl
                         and (c.get("is_mandatory") or c.get("required"))]
            if mandatory and all(c.get("confirmed") for c in mandatory):
                ok_levels.add(lvl)
        allowed = max(ok_levels) if ok_levels else 0
        if r["trl"] > allowed and allowed > 0:
            bad.append({"assessment_id": r["id"], "trl": r["trl"], "confirmed_max": allowed})
    if not bad:
        return []
    return [_finding("DIA-08", "error", "TRL выше уровня с выполненными обязательными критериями",
                     "ТЗ-03: TRL = максимальный уровень с выполненными обязательными критериями, усреднение запрещено.",
                     len(bad), bad, "Пересчитать TRL (analytics.trl) и проверить полноту критериев и доказательств.")]


def rule_feasibility(research_id=None) -> list[dict]:
    """DIA-09/10. Реализуемость против правила «неизвестный фактор ≠ 0» (ИД-02)."""
    out = []
    sc, pr = _scope(research_id)
    rows = db.query("""SELECT id, research_id, score, coverage, interpretation, interpretation_allowed,
                              factors, coverage_warning, parameters FROM analytics_feasibility
                       WHERE 1=1""" + sc + " ORDER BY created_at DESC LIMIT 500", pr)
    zero_unknown, bad_interpretation = [], []
    for r in rows:
        for f in db.dec(r, "factors").get("factors") or []:
            if f.get("assessment") == "unknown" and f.get("x") is not None:
                zero_unknown.append({"assessment_id": r["id"], "factor": f.get("code"), "x": f.get("x")})
        # Словесная интерпретация заполняется всегда, а показывает её UI по флагу
        # interpretation_allowed. Противоречие — разрешённая интерпретация при
        # покрытии ниже порога (или без оценки) и запрет без объяснения.
        min_cov = float(db.dec(r, "parameters").get("min_coverage_for_interpretation", 0.6))
        if r["interpretation_allowed"] and (r["score"] is None or r["coverage"] < min_cov):
            bad_interpretation.append({"assessment_id": r["id"], "coverage": r["coverage"],
                                       "min_coverage": min_cov, "score": r["score"],
                                       "interpretation": r["interpretation"],
                                       "reason": "интерпретация разрешена ниже порога покрытия"})
        elif not r["interpretation_allowed"] and r["score"] is not None and not r["coverage_warning"]:
            bad_interpretation.append({"assessment_id": r["id"], "coverage": r["coverage"],
                                       "min_coverage": min_cov, "score": r["score"],
                                       "interpretation": r["interpretation"],
                                       "reason": "ограничение интерпретации не объяснено (нет coverage_warning)"})
    if zero_unknown:
        out.append(_finding("DIA-09", "error", "Неизвестный фактор учтён как число",
                            "ИД-02: неизвестный фактор исключается из расчёта (x = NULL), а не приравнивается к нулю.",
                            len(zero_unknown), zero_unknown,
                            "Пересчитать реализуемость; проверить формирование факторов агентом A08."))
    if bad_interpretation:
        out.append(_finding("DIA-10", "warn", "Интерпретация при недостаточном покрытии",
                            "Флаг интерпретации расходится с покрытием: либо интерпретация разрешена ниже порога, "
                            "либо запрет не сопровождается предупреждением coverage_warning.",
                            len(bad_interpretation), bad_interpretation,
                            "Показывать только число и покрытие с предупреждением (interpretation_allowed = 0)."))
    return out


def rule_forecast(research_id=None) -> list[dict]:
    """DIA-11/12. Прогноз против монотонности и горизонта качественных сценариев."""
    out = []
    sc, pr = _scope(research_id)
    rows = db.query("""SELECT forecast_id, research_id, target, scenario_id, years_from,
                              probability_value, display_mode FROM forecast_points
                       WHERE 1=1""" + sc + """ ORDER BY forecast_id, target, scenario_id, years_from""", pr)
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((r["forecast_id"], r["target"], r["scenario_id"]), []).append(r)
    nonmono, quantitative_far = [], []
    for key, points in groups.items():
        prev = None
        for p in points:
            v = p["probability_value"]
            if v is not None and prev is not None and v < prev - 1e-9:
                nonmono.append({"forecast_id": key[0], "scenario": key[2], "years_from": p["years_from"],
                                "probability": v, "previous": prev})
            if v is not None:
                prev = v
            if p["years_from"] >= 20 and p["display_mode"] in ("EXACT", "INTERVAL"):
                quantitative_far.append({"forecast_id": key[0], "years_from": p["years_from"],
                                         "display_mode": p["display_mode"]})
    if nonmono:
        out.append(_finding("DIA-11", "error", "Немонотонная вероятность P(T ≤ t)",
                            "Накопленная вероятность не может убывать с ростом горизонта (ТЗ-03).",
                            len(nonmono), nonmono, "Пересчитать прогноз (analytics.forecast) и проверить сценарные веса."))
    if quantitative_far:
        out.append(_finding("DIA-12", "warn", "Количественный прогноз на горизонте 20–50 лет",
                            "На дальних горизонтах допускаются только качественные сценарии (COARSE/SCENARIO).",
                            len(quantitative_far), quantitative_far,
                            "Переключить режим отображения дальних горизонтов на качественные сценарии."))
    return out


def rule_policy(research_id=None) -> list[dict]:
    """DIA-13/14. Политика против фактических вызовов и квот."""
    out = []
    if not SETTINGS.allow_paid_ai:
        rows = db.query("""SELECT r.id, r.research_id, r.provider_id, r.estimated_cost
                           FROM ai_requests r JOIN ai_providers p ON p.id=r.provider_id
                           WHERE p.paid=1 LIMIT 50""")
        if rows:
            out.append(_finding("DIA-13", "error", "Платный провайдер при запрете платного ИИ",
                                "ТЗ-02: платные вызовы только при явном разрешении (allow_paid_ai).",
                                len(rows), [{"request_id": r["id"], "provider_id": r["provider_id"],
                                             "cost": r["estimated_cost"]} for r in rows],
                                "Проверить маршрутизацию orchestrator (free-first) и флаг разрешения."))
    over = db.query("""SELECT scope, key, window, used, limit_value FROM audit_quota_usage
                       WHERE limit_value IS NOT NULL AND used > limit_value LIMIT 50""")
    if over:
        out.append(_finding("DIA-14", "warn", "Квота израсходована сверх лимита",
                            "Фактический расход выше лимита реестра — счётчик или ограничитель расходятся.",
                            len(over), [dict(r) for r in over],
                            "Проверить search.quota: учёт расхода и блокировку до обращения к источнику."))
    return out


def rule_journal(research_id=None) -> list[dict]:
    """DIA-15…18. Дефекты по самому журналу: повторяемость, браузер, секреты, сбои записи."""
    out = []
    groups = journal.errors(limit=20)["items"]
    repeated = [g for g in groups if g["occurrences"] >= 3]
    if repeated:
        out.append(_finding("DIA-15", "error", "Повторяющийся дефект (одна подпись ≥ 3 раз)",
                            "Одинаковые падения с одной подписью — устойчивый баг, а не случайный сбой.",
                            len(repeated),
                            [{"fingerprint": g["fingerprint"], "action": g["action"],
                              "error_code": g["error_code"], "occurrences": g["occurrences"],
                              "last_seen": g["last_seen"],
                              "sample_id": (g.get("sample") or {}).get("id")} for g in repeated],
                            "Открыть ошибку по подписи в UI-32 → «Ошибки», разобрать traceback и закрыть дефект."))
    browser = db.query("""SELECT fingerprint, action, COUNT(*) AS occurrences, MAX(at) AS last_seen
                          FROM ops_journal WHERE source='browser' AND level IN ('error','critical')
                          GROUP BY fingerprint HAVING COUNT(*) >= 2 ORDER BY occurrences DESC LIMIT 20""")
    if browser:
        out.append(_finding("DIA-16", "warn", "Повторяющиеся ошибки интерфейса",
                            "Ошибки браузера доходят до сервера и группируются: дефект виден без доступа к машине пользователя.",
                            len(browser), [dict(r) for r in browser],
                            "Открыть UI-32 → «Браузер», сопоставить с версией интерфейса и экраном."))
    leaks = db.query("""SELECT id, at, action, message FROM ops_journal
                        WHERE message LIKE '%Bearer %' OR detail LIKE '%"password"%'
                           OR detail LIKE '%"api_key"%' OR message LIKE '%api_key=%' LIMIT 20""")
    leaks = [r for r in leaks if journal.MASK not in (r["message"] or "")]
    if leaks:
        out.append(_finding("DIA-17", "critical", "Похоже на секрет в журнале",
                            "Маскировка не сработала: в журнале не должно быть ключей, паролей и токенов.",
                            len(leaks), [{"journal_id": r["id"], "action": r["action"], "at": r["at"]} for r in leaks],
                            "Немедленно проверить journal.redact и источник записи; журнал выгружается наружу."))
    if journal.FAILED_WRITES:
        out.append(_finding("DIA-18", "warn", "Сбои записи журнала",
                            "Часть записей не попала в БД и сохранена в резервный файл journal-fallback.log.",
                            journal.FAILED_WRITES, [{"failed_writes": journal.FAILED_WRITES,
                                                    "fallback": "var/journal-fallback.log"}],
                            "Проверить целостность БД (PRAGMA quick_check) и место на диске."))
    return out


def rule_methodology(research_id=None) -> list[dict]:
    """DIA-19. Версия методики в расчётах против реестра методик."""
    # В расчётах версия хранится в виде «CODE version» (см. analytics/snapshot.py),
    # в реестре — раздельно. Сравнивать нужно оба представления, иначе правило
    # объявляет невоспроизводимым каждый нормальный расчёт (ложная находка).
    pairs = {(r["code"], r["version"]) for r in db.query("SELECT code, version FROM analytics_methodologies")}
    known = {v for _c, v in pairs} | {f"{c} {v}" for c, v in pairs}
    known.add(SETTINGS.methodology_version)
    if not known:
        return []
    sc, pr = _scope(research_id)
    bad = []
    for table, label in (("search_results", "релевантность"), ("analytics_trl", "TRL"),
                         ("analytics_feasibility", "реализуемость")):
        rows = db.query(f"SELECT id, research_id, methodology_version FROM {table} WHERE 1=1" + sc
                        + " ORDER BY created_at DESC LIMIT 2000", pr)
        for r in rows:
            if r["methodology_version"] and r["methodology_version"] not in known:
                bad.append({"table": table, "kind": label, "id": r["id"],
                            "version": r["methodology_version"]})
    if not bad:
        return []
    return [_finding("DIA-19", "warn", "Расчёт ссылается на неизвестную версию методики",
                     "Версионируемость нарушена: результат нельзя воспроизвести по реестру методик.",
                     len(bad), bad, "Зарегистрировать версию методики либо пересчитать с действующей.")]


# Реестр правил хранит ИМЯ функции, а не ссылку: правило можно подменить или
# расширить (в том числе в испытаниях), не переписывая прогон.
RULES = [
    ("DIA-01", "Состояния исследований и этапов", "rule_states"),
    ("DIA-02", "Переходы против конечных автоматов", "rule_transitions"),
    ("DIA-03", "Отчёты и наличие файлов", "rule_report_files"),
    ("DIA-04/05", "Утверждения и доказательства", "rule_claims"),
    ("DIA-06/07", "Релевантность и компоненты", "rule_relevance"),
    ("DIA-08", "TRL и обязательные критерии", "rule_trl"),
    ("DIA-09/10", "Реализуемость и покрытие", "rule_feasibility"),
    ("DIA-11/12", "Прогноз: монотонность и горизонты", "rule_forecast"),
    ("DIA-13/14", "Политика ИИ и квоты", "rule_policy"),
    ("DIA-15…18", "Дефекты по журналу", "rule_journal"),
    ("DIA-19", "Версии методик", "rule_methodology"),
]


def rule_fn(name: str):
    return globals()[name]


def run(*, research_id: str | None = None, to_journal: bool = False, actor: str = "system") -> dict:
    """Прогон всех правил. Отказ одного правила не отменяет остальные."""
    findings, broken = [], []
    for code, title, name in RULES:
        try:
            findings.extend(rule_fn(name)(research_id) or [])
        except Exception as exc:  # noqa: BLE001
            broken.append({"rule": code, "error": str(exc)[:200]})
            journal.error(exc, "analytics", f"diagnostics.{code}", source="server",
                          message=f"Правило проверки не выполнилось: {title}")
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), -f["count"], f["code"]))
    counts = {sev: sum(1 for f in findings if f["severity"] == sev)
              for sev in ("critical", "error", "warn", "info")}
    result = {"checked_at": iso_now(), "rules": len(RULES), "scope": research_id or "вся система",
              "findings": findings, "counts": counts, "broken_rules": broken,
              "cases": sum(f["count"] for f in findings),
              "ok": not findings and not broken,
              "note": "Правила только читают данные; противоречие — это расхождение с ТЗ, а не мнение модели"}
    if to_journal:
        for f in findings:
            journal.record("error" if f["severity"] in ("critical", "error") else "warn",
                           "analytics", f"diagnostics.{f['code']}", message=f["title"],
                           actor=actor, outcome="contradiction", research_id=f.get("research_id"),
                           detail={"count": f["count"], "evidence": f["evidence"],
                                   "recommendation": f["recommendation"]})
        journal.record("info", "analytics", "diagnostics.run", actor=actor,
                       message=f"Правил: {len(RULES)}, противоречий: {len(findings)}, случаев: {result['cases']}",
                       detail={"counts": counts, "scope": result["scope"]})
    return result
