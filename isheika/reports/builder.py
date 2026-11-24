"""Генератор отчётов и экспорт (ТЗ-01 §7, ТЗ-04 §6).

Форматы: HTML (интерактивный, самодостаточный), JSON, CSV, XLSX, DOCX, PDF-печать.
Отчёт содержит постановку задачи, методику и её версию, поисковую стратегию,
охват источников, паспорт, TRL, реализуемость, барьеры, альтернативы, тренды,
сценарии, доказательства, ограничения и предупреждения.

XLSX/DOCX формируются минимальным OOXML-писателем на стандартной библиотеке,
чтобы не тянуть зависимости в DEV-профиле. Файлы валидны для Excel/Word.
"""
from __future__ import annotations

import csv
import html
import io
import json
import os
import zipfile
from datetime import datetime

from .. import __version__ as APP_VERSION
from ..config import SETTINGS
from ..contracts import iso_now, new_id
from ..storage import db
from ..analytics import evidence as E, methodologies as M, passport as P, quality as Q, trends as TR
from ..registry.loader import methodology
from ..search import manager as SM

REPORT_SECTIONS = [
    "Постановка задачи", "Методика и версии", "Поисковая стратегия", "Охват источников",
    "Описание технологии", "Научная база", "Патентная база", "Промышленная база",
    "TRL 1–9", "Реализуемость", "Барьеры и риски", "Альтернативы", "Тренды",
    "Прогноз 0–50 лет", "Доказательства", "Ограничения и предупреждения", "Выводы",
]


def collect(research_id: str) -> dict:
    r = db.dec(db.one("SELECT * FROM core_researches WHERE id=?", (research_id,)),
               "settings", "country_codes", "language_codes")
    q = db.dec(db.one("SELECT * FROM search_queries WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,)),
               "parsed", "expansions", "branches", "exclusions")
    docs = [db.dec(x, "authors", "organizations", "identifiers") for x in
            db.query("""SELECT d.*, d.relevance_score AS score, d.relevance_class AS rclass,
                               rel.reason, rel.components, rel.reason_codes
                        FROM research_documents d
                        LEFT JOIN search_results rel ON rel.document_id=d.id AND rel.research_id=d.research_id
                             AND rel.id=(SELECT s2.id FROM search_results s2 WHERE s2.document_id=d.id
                                         AND s2.research_id=d.research_id
                                         ORDER BY s2.created_at DESC, s2.rowid DESC LIMIT 1)
                        WHERE d.research_id=? ORDER BY d.relevance_score DESC""", (research_id,))]
    # Технический перевод найденной НТИ (ред. 1.5.0): русский текст рядом с оригиналом
    from .. import translation as TRANSL
    trans = {t["document_id"]: t for t in
             [db.dec(x, "untranslated") for x in
              db.query("""SELECT t.* FROM document_translations t
                          JOIN content_occurrences o ON o.document_id=t.document_id
                          WHERE o.research_id=?""", (research_id,))]}
    for d in docs:
        t = trans.get(d["id"]) or {}
        d["title_ru"] = t.get("title_ru") or d["title"]
        d["abstract_ru"] = t.get("abstract_ru") or d.get("abstract") or ""
        d["translation_mode"] = t.get("mode") or "нет"
        d["translation_coverage"] = t.get("coverage")
        d["translation_review"] = bool(t.get("review_required"))
    jobs = [db.dec(x, "depends_on", "result") for x in
            db.query("SELECT * FROM workflow_jobs WHERE research_id=? ORDER BY created_at", (research_id,))]
    sjobs = db.query("SELECT * FROM search_jobs WHERE research_id=?", (research_id,))
    return {
        "research": r, "query": q, "documents": docs, "jobs": jobs, "search_jobs": sjobs,
        "passport": P.get(research_id),
        "trl": db.dec(db.one("SELECT * FROM analytics_trl WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,)), "criteria", "gaps"),
        "feasibility": db.dec(db.one("SELECT * FROM analytics_feasibility WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,)), "factors", "sensitivity", "weights"),
        "barriers": [db.dec(x, "evidence_ids") for x in db.query("SELECT * FROM analytics_barriers WHERE research_id=?", (research_id,))],
        "alternatives": [db.dec(x, "criteria") for x in db.query("SELECT * FROM analytics_alternatives WHERE research_id=?", (research_id,))],
        "forecast": db.dec(db.one("SELECT * FROM forecast_runs WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,)), "horizons", "scenarios", "assumptions", "intervals"),
        "trends": TR.latest(research_id),
        "evidence": _with_quote_translation(E.evidence_for(research_id)),
        "evidence_summary": E.summary(research_id),
        "claims": db.query("SELECT * FROM knowledge_claims WHERE research_id=?", (research_id,)),
        "coverage": SM.coverage_by_country(research_id),
        "quality": Q.latest(research_id),
        "consensus": [db.dec(x, "positions", "conflicts", "resolution", "synthesis") for x in
                      db.query("SELECT * FROM ai_consensus WHERE research_id=?", (research_id,))],
        "ai_requests": db.query("SELECT * FROM ai_requests WHERE research_id=? ORDER BY created_at", (research_id,)),
        "methodology": methodology(),
        "methodology_registry": M.used_in_research(research_id),   # ИД-09: версии из реестра
        "translation": TRANSL.summary(research_id),
        "generated_at": iso_now(),
        "api_version": "v1", "app_version": APP_VERSION,
    }



def _with_quote_translation(items: list[dict]) -> list[dict]:
    """Русский перевод цитат доказательств (ред. 1.5.0): оригинал сохраняется рядом."""
    from .. import translation as TRANSL
    for e in items:
        quote = e.get("quote") or ""
        if not quote:
            e["quote_ru"], e["quote_mode"] = "", "нет"
            continue
        if TRANSL.detect_language(quote) == "ru":
            e["quote_ru"], e["quote_mode"] = quote, "original"
            continue
        t = TRANSL.translate_text(quote[:1200])
        e["quote_ru"], e["quote_mode"] = t["text"], t["mode"]
        e["quote_coverage"] = t["coverage"]
    return items


def warnings(data: dict) -> list[str]:
    w = []
    if data["quality"] is None or not (data["quality"].get("search") or {}).get("calibrated"):
        w.append("Калибровка методик не завершена: веса и пороги стартовые (ТЗ-03).")
    sim = sum(1 for d in data["documents"] if (d.get("identifiers") or {}).get("simulated"))
    if sim:
        w.append(f"В выборке {sim} имитационных документов DEV-профиля — они не являются доказательствами.")
    sim_ai = sum(1 for r in data["ai_requests"] if r["simulated"])
    if sim_ai:
        w.append(f"{sim_ai} ответов получено детерминированным экстрактором (не моделью ИИ).")
    gaps = [c["iso2"] for c in data["coverage"] if c["gap"]]
    if gaps:
        w.append("Карта пробелов: нет данных по странам — " + ", ".join(gaps))
    failed = [j["stage"] for j in data["jobs"] if j["status"] in ("failed", "skipped")]
    if failed:
        w.append("Незавершённые этапы: " + ", ".join(failed))
    fea = data["feasibility"] or {}
    if fea and (fea.get("coverage") or 0) < 0.6:
        w.append(f"Низкое покрытие факторов реализуемости: {round((fea.get('coverage') or 0)*100)}%.")
    if not data["documents"]:
        w.append("Документы не получены: проверьте ключи, квоты и доступность источников.")
    return w


# ------------------------------------------------------------------ HTML
def build_html(data: dict) -> str:
    r = data["research"]
    pp = (data["passport"] or {}).get("passport") or {}
    trl = data["trl"] or {}
    fea = data["feasibility"] or {}
    reg = data.get("methodology_registry") or {}
    rel = reg.get("RELEVANCE") or M.active("RELEVANCE")
    fea_m = reg.get("FEASIBILITY") or M.active("FEASIBILITY")
    esc = html.escape

    def table(headers: list[str], rows: list[list[str]]) -> str:
        th = "".join(f"<th>{esc(h)}</th>" for h in headers)
        trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
        return f'<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>'

    docs_rows = []
    for d in data["documents"][:200]:
        ru = d.get("title_ru") or d["title"]
        original = d["title"] if ru != d["title"] else ""
        mark = {"terminology": "терминологический перевод", "ai_technical": "перевод ИИ",
                "original": "оригинал на русском"}.get(d.get("translation_mode"), "")
        cell = f'<a href="{esc(d["url"])}">{esc(ru[:160])}</a>'
        if original:
            cell += (f'<div class="tiny muted">{esc(original[:160])}'
                     + (f' · {esc(mark)}' if mark else "") + "</div>")
        docs_rows.append([
            cell,
            esc(d["doc_type"]), esc(d["source_code"]), esc(d["country_code"] or "—"),
            esc((d["published_at"] or "")[:10]), f'{(d.get("score") or 0):.2f}',
            esc(d.get("rclass") or "—"), esc(d["evidence_class"]),
        ])
    trn_rows = []
    for mode, info in ((data.get("translation") or {}).get("modes") or {}).items():
        name = {"original": "оригинал на русском", "terminology": "терминологический перевод (черновик)",
                "ai_technical": "перевод моделью ИИ"}.get(mode, mode)
        trn_rows.append([esc(name), str(info["count"]), f'{info["coverage"]}'])
    ev_rows = [[(esc((e.get("quote_ru") or e["quote"] or ""))[:240]
                 + (f'<div class="tiny muted">{esc((e["quote"] or "")[:200])}'
                    + (" · терминологический перевод" if e.get("quote_mode") == "terminology" else "")
                    + "</div>" if e.get("quote_mode") == "terminology" else "")),
                f'<a href="{esc(e["url"] or "")}">источник</a>',
                esc(e["evidence_class"]), esc(e["status"]), f'{(e["quality"] or 0):.2f}',
                esc(e["locator"] or "")] for e in data["evidence"][:120]]
    trl_rows = [[str(c["level"]), esc(c["criterion_id"]), esc(c["text"]),
                 "✔ подтверждено" if c["confirmed"] else "✖ не подтверждено",
                 ", ".join(c["evidence_classes"]) or "—"] for c in (trl.get("criteria") or [])]
    fea_rows = [[esc(f["name"]), f'{f["weight"]:.2f}',
                 ("неизвестно" if f.get("x") is None else f'{f["x"]:.2f}'),
                 esc(f["assessment"]), esc(f.get("rationale", ""))] for f in (fea.get("factors") or [])]
    cov_rows = [[esc(c["name_ru"]), esc(c["iso2"]), str(c["documents"]), str(c["class_P"]),
                 "ПРОБЕЛ" if c["gap"] else "есть данные"] for c in data["coverage"]]
    warn_html = "".join(f"<li>{esc(w)}</li>" for w in warnings(data))
    ladder = "".join(
        f'<div class="step {"on" if (trl.get("trl") or 0) >= i else ""}"><b>{i}</b><span>{esc(l["title"])}</span></div>'
        for i, l in enumerate(methodology()["trl"]["levels"], 1))
    scen_html = ""
    fc = data["forecast"] or {}
    for target, scen in (fc.get("scenarios") or {}).items():
        rows = []
        for h in (fc.get("horizons") or []):
            row = [f'{h["from"]}–{h["to"]} лет']
            for name in ("optimistic", "base", "pessimistic"):
                pt = next((p for p in scen.get(name, []) if p["horizon"] == h["code"]), {})
                row.append(pt.get("qualitative") or (f'{pt["probability"]:.2f} [{pt["interval"][0]:.2f}; {pt["interval"][1]:.2f}]'
                                                     if pt.get("probability") is not None else "нет данных"))
            rows.append(row)
        scen_html += f"<h4>{esc(target)}</h4>" + table(["Горизонт", "Оптимистичный", "Базовый", "Пессимистичный"], rows)

    return f"""<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">
<title>Отчёт НТР — {esc(r['title'])}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{{font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;color:#16202c;background:#f6f8fb}}
 .wrap{{max-width:1180px;margin:0 auto;padding:28px}}
 h1{{font-size:26px;margin:0 0 6px}} h2{{font-size:19px;margin:26px 0 10px;border-bottom:2px solid #dbe4f0;padding-bottom:6px}}
 h4{{margin:14px 0 6px}}
 table{{border-collapse:collapse;width:100%;background:#fff;font-size:13px;margin:8px 0}}
 th,td{{border:1px solid #dde5ef;padding:6px 8px;text-align:left;vertical-align:top}}
 th{{background:#eef3fa}} tr:nth-child(even) td{{background:#fafcff}}
 .cards{{display:flex;gap:12px;flex-wrap:wrap;margin:14px 0}}
 .card{{background:#fff;border:1px solid #dde5ef;border-radius:10px;padding:12px 16px;min-width:170px}}
 .card b{{display:block;font-size:24px}}
 .warn{{background:#fff8e6;border:1px solid #f0d79a;border-radius:10px;padding:12px 18px}}
 .ladder{{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}}
 .step{{border:1px solid #cfd9e6;border-radius:8px;padding:6px 10px;background:#fff;font-size:12px;max-width:220px}}
 .step.on{{background:#e8f6ec;border-color:#7cc08f}}
 .step b{{display:block;font-size:16px}}
 .meta{{color:#5a6b80;font-size:13px}}
 code{{background:#eef2f7;padding:1px 5px;border-radius:4px}}
</style></head><body><div class="wrap">
<h1>Аналитический отчёт НТР: {esc(r['title'])}</h1>
<p class="meta">ИЩЕЙКА НТР AI · исследование <code>{esc(r['id'])}</code> · сформирован {esc(data['generated_at'])} ·
версия методики <code>{esc(data['methodology']['version'])}</code> · API {esc(data['api_version'])}</p>

<div class="cards">
 <div class="card"><span>Документов</span><b>{len(data['documents'])}</b></div>
 <div class="card"><span>Прямых совпадений</span><b>{sum(1 for d in data['documents'] if d.get('rclass')=='DIRECT')}</b></div>
 <div class="card"><span>TRL</span><b>{trl.get('trl','—')}</b></div>
 <div class="card"><span>Реализуемость</span><b>{(str(fea.get('score'))+'%') if fea.get('score') is not None else '—'}</b></div>
 <div class="card"><span>Покрытие факторов</span><b>{round((fea.get('coverage') or 0)*100)}%</b></div>
 <div class="card"><span>Доказательств</span><b>{data['evidence_summary']['total']}</b></div>
</div>

<div class="warn"><b>Предупреждения</b><ul>{warn_html}</ul></div>

<h2>1. Постановка задачи</h2>
<p><b>Запрос:</b> {esc((data['query'] or {}).get('raw_text') or '')}</p>
<p><b>Цель:</b> {esc(r.get('goal') or '—')}</p>
<p><b>Период:</b> {r.get('period_from') or '—'}–{r.get('period_to') or '—'} ·
<b>Страны:</b> {len(r.get('country_codes') or [])} · <b>Языки:</b> {esc(', '.join(r.get('language_codes') or []))}</p>

<h2>2. Методика и версии</h2>
<p>Релевантность (<code>{esc(rel['code'])}</code>): <code>{esc(rel['formula_definition'].get('expression', ''))}</code>, пороги
 DIRECT ≥ {rel['thresholds']['DIRECT']}, ADJACENT ≥ {rel['thresholds']['ADJACENT']}, иначе BELOW_THRESHOLD.</p>
<p>Реализуемость (<code>{esc(fea_m['code'])}</code>): <code>{esc(fea_m['formula_definition'].get('expression', ''))}</code>;
 покрытие <code>{esc(fea_m['formula_definition'].get('coverage', ''))}</code>. TRL — максимальный уровень с выполненными обязательными критериями; усреднение запрещено.</p>
{table(["Семейство", "Методика", "Статус", "Источник версии", "Контрольная сумма"],
       [[esc(k), esc(v['code'] + " " + v['version']), esc(v.get('approval_status') or ''),
         esc('результат расчёта' if v.get('source') == 'result' else 'активная версия'),
         esc((v.get('config_checksum') or '')[:16])] for k, v in data['methodology_registry'].items()])}
<p>Хеши входов расчётов: TRL <code>{esc(trl.get('input_hash') or '—')}</code>, F <code>{esc(fea.get('input_hash') or '—')}</code>.</p>

<h2>3. Поисковая стратегия</h2>
{table(["Ветвь", "Тип", "Выражение"], [[esc(b.get('name','')), esc(b.get('kind','')), esc(b.get('expression',''))] for b in ((data['query'] or {}).get('expansions') or {}).get('branches', [])])}

<h2>4. Охват источников</h2>
{table(["Коннектор", "Статус", "Найдено", "Ошибка"], [[esc(j['connector_code']), esc(j['status']), str(j['found_count']), esc(j['error_message'] or '—')] for j in data['search_jobs']])}

<h2>5. Описание технологии</h2>
<p>{esc((pp.get('purpose_and_principle') or {}).get('principle') or '—')}</p>
<p><b>Компоненты:</b> {esc(', '.join((pp.get('architecture_components') or {}).get('components') or []) or '—')}</p>

<h2>6–8. Научная, патентная и промышленная база</h2>
{table(["Раздел", "Документов", "Примечание"], [
  ["Научная база", str((pp.get('science_base') or {}).get('documents', 0)), "Первичные публикации и препринты"],
  ["Патентная база", str((pp.get('patent_base') or {}).get('documents', 0)), esc((pp.get('patent_base') or {}).get('note',''))],
  ["Промышленная база", str(len((pp.get('industry_base') or {}).get('organizations') or [])), "Организации-разработчики"],
])}

<h2>9. TRL 1–9</h2>
<div class="ladder">{ladder}</div>
<p><b>Итоговый TRL: {trl.get('trl','—')}</b> (уверенность: {trl.get('confidence') or 'не определена'})</p>
{table(["Уровень", "Критерий", "Формулировка", "Статус", "Классы доказательств"], trl_rows)}

<h2>10. Реализуемость</h2>
<p><b>F = {fea.get('score') if fea.get('score') is not None else 'не определена'}%</b>,
диапазон [{fea.get('range_low')}; {fea.get('range_high')}], консервативная оценка {fea.get('conservative')},
покрытие {round((fea.get('coverage') or 0)*100)}%. Интерпретация: {esc(fea.get('interpretation') or '—')}.</p>
{table(["Фактор", "Вес", "Оценка x", "Статус", "Обоснование"], fea_rows)}

<h2>11. Барьеры и риски</h2>
{table(["Тип", "Критичность", "Вероятность", "Документов"], [[esc(b['barrier_type']), str(b['criticality']), str(b['probability']), str(len(b['evidence_ids']))] for b in data['barriers']])}

<h2>12. Альтернативы</h2>
{table(["Название", "Принцип/функция"], [[esc(a['name']), esc((a['criteria'] or {}).get('принцип действия') or '—')] for a in data['alternatives']])}

<h2>13. Тренды</h2>
{table(["Год", "Публикации"], [[str(p['year']), ('нет данных' if p['value'] is None else str(p['value']))] for p in (data['trends'].get('publications') or [])])}

<h2>14. Прогноз 0–50 лет</h2>
{scen_html}
<p class="meta">Метод: {esc(fc.get('method') or '—')}. Монотонность P(T≤t): {'соблюдена' if fc.get('monotonic_ok') else 'НАРУШЕНА'}.
На горизонтах 20–50 лет приводятся качественные сценарии.</p>

<h2>15. Доказательства</h2>
{table(["Фрагмент", "Ссылка", "Класс", "Статус", "Качество", "Локатор"], ev_rows)}

<h2>16. Карта пробелов по странам</h2>
{table(["Страна", "ISO", "Документов", "Класс П", "Статус"], cov_rows)}

<h2>17. Технический перевод найденных материалов</h2>
<p class="meta">Переведено материалов: {(data.get('translation') or {}).get('translated', 0)};
требуют вычитки: {(data.get('translation') or {}).get('review_required', 0)};
словарь терминов <code>{esc((data.get('translation') or {}).get('glossary_version') or '—')}</code>.
Терминологический режим — черновик технического перевода: числа, единицы измерения,
обозначения и идентификаторы сохранены, формулировки требуют вычитки специалистом.</p>
{table(["Режим перевода", "Материалов", "Доля переведённого"], trn_rows)}

<h2>Приложение А. Найденные материалы (русский перевод и оригинал)</h2>
{table(["Название", "Тип", "Источник", "Страна", "Дата", "R", "Класс R", "Класс доказательства"], docs_rows)}

<h2>18. Ограничения</h2>
<ul>{''.join(f'<li>{esc(x)}</li>' for x in (pp.get('limitations') or []))}</ul>

<h2>19. Выводы</h2>
<p>Отчёт сформирован автоматически по открытым источникам. Численные оценки получены расчётным ядром
с версией методики {esc(data['methodology']['version'])}; утверждения разделены на FACT / ANALYSIS / HYPOTHESIS / FORECAST.
Незавершённая калибровка означает, что абсолютные значения оценок следует трактовать как ориентировочные.</p>
</div></body></html>"""


# ------------------------------------------------------------------ CSV / JSON
def build_csv(data: dict, kind: str = "documents") -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    if kind == "evidence":
        w.writerow(["claim_id", "document_id", "url", "locator", "quote_ru", "quote_original", "quote_mode",
                    "evidence_class", "status", "quality", "published_at", "accessed_at"])
        for e in data["evidence"]:
            w.writerow([e["claim_id"], e["document_id"], e["url"], e["locator"],
                        e.get("quote_ru") or e["quote"], e["quote"], e.get("quote_mode") or "",
                        e["evidence_class"], e["status"], e["quality"], e["published_at"], e["accessed_at"]])
    elif kind == "claims":
        w.writerow(["claim_id", "type", "status", "confidence", "text", "produced_by"])
        for c in data["claims"]:
            w.writerow([c["id"], c["claim_type"], c["status"], c["confidence"], c["claim_text"], c["produced_by"]])
    else:
        w.writerow(["document_id", "title_ru", "abstract_ru", "translation_mode", "translation_coverage",
                    "title_original", "url", "type", "source", "country", "language",
                    "published_at", "relevance", "class", "evidence_class", "marker", "doi"])
        for d in data["documents"]:
            w.writerow([d["id"], d.get("title_ru") or d["title"], d.get("abstract_ru") or "",
                        d.get("translation_mode") or "", d.get("translation_coverage"),
                        d["title"], d["url"], d["doc_type"], d["source_code"], d["country_code"],
                        d["language"], d["published_at"], d.get("score"), d.get("rclass"),
                        d["evidence_class"], d["marker"], d["doi"]])
    return buf.getvalue()


# ------------------------------------------------------------------ XLSX (минимальный OOXML)
def _xlsx_sheet(rows: list[list]) -> str:
    def cell(v, r, c):
        ref = f"{_col(c)}{r}"
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return f'<c r="{ref}"><v>{v}</v></c>'
        s = html.escape(str(v if v is not None else ""))[:32000]
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{s}</t></is></c>'
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
    for i, row in enumerate(rows, 1):
        out.append(f'<row r="{i}">' + "".join(cell(v, i, j) for j, v in enumerate(row, 1)) + "</row>")
    out.append("</sheetData></worksheet>")
    return "".join(out)


def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def build_xlsx(data: dict, path: str) -> str:
    sheets = {
        "Документы": [["ID", "Заголовок (рус.)", "Аннотация (рус.)", "Режим перевода", "Доля перевода",
                       "Заголовок (оригинал)", "URL", "Тип", "Источник", "Страна", "Дата", "R", "Класс", "Класс доказательства"]] +
                     [[d["id"], d.get("title_ru") or d["title"], (d.get("abstract_ru") or "")[:2000],
                       d.get("translation_mode") or "", d.get("translation_coverage"),
                       d["title"], d["url"], d["doc_type"], d["source_code"], d["country_code"],
                       d["published_at"], d.get("score"), d.get("rclass"), d["evidence_class"]] for d in data["documents"]],
        "TRL": [["Уровень", "Критерий", "Формулировка", "Подтверждено", "Классы"]] +
               [[c["level"], c["criterion_id"], c["text"], "да" if c["confirmed"] else "нет",
                 ", ".join(c["evidence_classes"])] for c in ((data["trl"] or {}).get("criteria") or [])],
        "Реализуемость": [["Фактор", "Вес", "x", "Статус", "Обоснование"]] +
                         [[f["name"], f["weight"], f.get("x"), f["assessment"], f.get("rationale")]
                          for f in ((data["feasibility"] or {}).get("factors") or [])],
        "Доказательства": [["Claim", "URL", "Фрагмент (рус.)", "Фрагмент (оригинал)", "Класс", "Статус", "Качество"]] +
                          [[e["claim_id"], e["url"], e.get("quote_ru") or e["quote"], e["quote"],
                            e["evidence_class"], e["status"], e["quality"]]
                           for e in data["evidence"]],
        "Покрытие": [["Страна", "ISO", "Документов", "Класс П", "Пробел"]] +
                    [[c["name_ru"], c["iso2"], c["documents"], c["class_P"], "да" if c["gap"] else "нет"] for c in data["coverage"]],
        "Предупреждения": [["Предупреждение"]] + [[w] for w in warnings(data)],
    }
    names = list(sheets)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
                   "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                           for i in range(1, len(names) + 1)) + '</Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
                   "".join(f'<sheet name="{html.escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1)) +
                   '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
                   "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
                           for i in range(1, len(names) + 1)) + '</Relationships>')
        for i, n in enumerate(names, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _xlsx_sheet(sheets[n]))
    return path


# ------------------------------------------------------------------ DOCX (минимальный OOXML)
def build_docx(data: dict, path: str) -> str:
    r = data["research"]
    trl = data["trl"] or {}
    fea = data["feasibility"] or {}
    blocks: list[tuple[str, str]] = [
        ("h1", f"Аналитический отчёт НТР: {r['title']}"),
        ("p", f"Исследование {r['id']} · сформирован {data['generated_at']} · комплект методик {data['methodology']['version']}"),
        ("h2", "1. Постановка задачи"),
        ("p", f"Запрос: {(data['query'] or {}).get('raw_text') or ''}"),
        ("p", f"Цель: {r.get('goal') or '—'}"),
        ("h2", "2. Ключевые показатели"),
        ("p", f"Документов: {len(data['documents'])}; прямых совпадений: {sum(1 for d in data['documents'] if d.get('rclass')=='DIRECT')}"),
        ("p", f"TRL: {trl.get('trl','—')} (уверенность {trl.get('confidence') or 'не определена'})"),
        ("p", f"Реализуемость F: {fea.get('score') if fea.get('score') is not None else 'не определена'}%, "
              f"диапазон [{fea.get('range_low')}; {fea.get('range_high')}], покрытие {round((fea.get('coverage') or 0)*100)}%"),
        ("h2", "3. Предупреждения"),
    ]
    for w in warnings(data):
        blocks.append(("p", "• " + w))
    blocks.append(("h2", "4. Критерии TRL"))
    for c in (trl.get("criteria") or []):
        blocks.append(("p", f'[{c["level"]}] {c["criterion_id"]} — {c["text"]}: '
                            f'{"подтверждено" if c["confirmed"] else "не подтверждено"}'))
    blocks.append(("h2", "5. Факторы реализуемости"))
    for f in (fea.get("factors") or []):
        blocks.append(("p", f'{f["name"]} (вес {f["weight"]}): '
                            f'{"неизвестно" if f.get("x") is None else f["x"]} — {f.get("rationale","")}'))
    blocks.append(("h2", "6. Доказательства (выборка)"))
    for e in data["evidence"][:40]:
        blocks.append(("p", f'[{e["evidence_class"]}/{e["status"]}] {(e.get("quote_ru") or e["quote"] or "")[:220]} — {e["url"]}'))
        if e.get("quote_mode") == "terminology":
            blocks.append(("p", f'   оригинал: {(e["quote"] or "")[:200]}'))
    trn = data.get("translation") or {}
    blocks.append(("h2", "7. Технический перевод найденных материалов"))
    blocks.append(("p", f'Переведено материалов: {trn.get("translated", 0)}; '
                        f'требуют вычитки: {trn.get("review_required", 0)}; '
                        f'словарь терминов {trn.get("glossary_version", "—")}'))
    for mode, info in (trn.get("modes") or {}).items():
        name = {"original": "оригинал на русском", "terminology": "терминологический перевод (черновик)",
                "ai_technical": "перевод моделью ИИ"}.get(mode, mode)
        blocks.append(("p", f'• {name}: {info["count"]}, доля переведённого {info["coverage"]}'))
    for d in data["documents"][:25]:
        if (d.get("title_ru") or d["title"]) != d["title"]:
            blocks.append(("p", f'{d["title_ru"]}'))
            blocks.append(("p", f'   оригинал: {d["title"]}'))
            if d.get("abstract_ru"):
                blocks.append(("p", f'   {d["abstract_ru"][:600]}'))
    blocks.append(("h2", "8. Ограничения"))
    for lim in ((data["passport"] or {}).get("passport") or {}).get("limitations", []):
        blocks.append(("p", "• " + lim))

    def para(style: str, text: str) -> str:
        st = {"h1": "Title", "h2": "Heading1", "p": "Normal"}[style]
        return (f'<w:p><w:pPr><w:pStyle w:val="{st}"/></w:pPr><w:r><w:t xml:space="preserve">'
                f'{html.escape(text)}</w:t></w:r></w:p>')

    body = "".join(para(s, t) for s, t in blocks)
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f'<w:body>{body}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
              '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:rPr><w:b/><w:sz w:val="28"/></w:rPr></w:style>'
              '</w:styles>')
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                   '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/_rels/document.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
    return path


# ------------------------------------------------------------------ сборка
def generate(research_id: str, formats: list[str] | None = None) -> dict:
    formats = formats or ["html", "pdf", "json", "csv", "xlsx", "docx"]
    rid = new_id("rep-")
    db.insert("reporting_reports", {"id": rid, "research_id": research_id,
                                    "title": (db.one("SELECT title FROM core_researches WHERE id=?", (research_id,)) or {}).get("title", "Отчёт"),
                                    "status": "preparing", "formats": formats, "files": {},
                                    "warnings": [], "methodology_version": methodology()["version"],
                                    "created_at": iso_now()})
    data = collect(research_id)
    db.update("reporting_reports", "id", rid, {"status": "generating"})
    outdir = os.path.join(SETTINGS.files_dir, research_id)
    os.makedirs(outdir, exist_ok=True)
    files = {}
    if "html" in formats:
        p = os.path.join(outdir, f"report-{rid}.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write(build_html(data))
        files["html"] = p
    if "json" in formats:
        p = os.path.join(outdir, f"report-{rid}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, default=str)
        files["json"] = p
    if "csv" in formats:
        for kind in ("documents", "evidence", "claims"):
            p = os.path.join(outdir, f"{kind}-{rid}.csv")
            with open(p, "w", encoding="utf-8-sig") as f:
                f.write(build_csv(data, kind))
            files["csv_" + kind] = p
    if "xlsx" in formats:
        files["xlsx"] = build_xlsx(data, os.path.join(outdir, f"report-{rid}.xlsx"))
    if "docx" in formats:
        files["docx"] = build_docx(data, os.path.join(outdir, f"report-{rid}.docx"))
    if "pdf" in formats:
        from .pdf import build_pdf
        files["pdf"] = build_pdf(data, os.path.join(outdir, f"report-{rid}.pdf"))
    w = warnings(data)
    db.update("reporting_reports", "id", rid, {"status": "validating"})
    ok = all(os.path.exists(p) and os.path.getsize(p) > 0 for p in files.values())
    db.update("reporting_reports", "id", rid,
              {"status": "ready" if ok else "failed", "files": files, "warnings": w,
               "snapshot_hash": (data["trl"] or {}).get("input_hash"), "finished_at": iso_now()})
    return {"report_id": rid, "status": "ready" if ok else "failed", "files": files, "warnings": w}


def latest(research_id: str) -> dict | None:
    row = db.one("SELECT * FROM reporting_reports WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,))
    return db.dec(row, "formats", "files", "warnings")
