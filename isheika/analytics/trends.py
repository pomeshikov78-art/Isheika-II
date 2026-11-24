"""Анализ трендов (ТЗ-03 §7): динамика публикаций, патентов, стран, организаций.

Отсутствие данных НЕ обозначается нулём: год без наблюдений помечается None.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from ..contracts import iso_now, new_id
from ..storage import db


def _series(rows: list[dict], key: str) -> list[dict]:
    counts = Counter(r[key] for r in rows if r[key])
    if not counts:
        return []
    years = sorted(int(y) for y in counts)
    lo, hi = min(years), max(years)
    out = []
    for y in range(lo, hi + 1):
        # год без наблюдений: None (данных нет), а не 0
        out.append({"year": y, "value": counts.get(str(y), counts.get(y, 0)) if (str(y) in counts or y in counts) else None})
    return out


def compute(research_id: str) -> dict:
    rows = db.query("""SELECT publication_year AS y, doc_type, country_code, organizations, evidence_class
                       FROM research_documents WHERE research_id=? AND relevance_class IN ('DIRECT','ADJACENT')""",
                    (research_id,))
    rows = [db.dec(r, "organizations") for r in rows]
    for r in rows:
        r["y"] = str(r["y"]) if r["y"] else None
    all_series = _series(rows, "y")
    patents = _series([r for r in rows if r["doc_type"] == "patent"], "y")
    articles = _series([r for r in rows if r["doc_type"] in ("article", "journal-article", "preprint")], "y")
    reports = _series([r for r in rows if r["doc_type"] == "report"], "y")
    countries = Counter(r["country_code"] for r in rows if r["country_code"])
    orgs = Counter(o for r in rows for o in (r["organizations"] or []) if o)

    out = {"publications": all_series, "patents": patents, "articles": articles, "reports": reports,
           "countries": [{"iso2": k, "documents": v} for k, v in countries.most_common(40)],
           "organizations": [{"name": k, "documents": v} for k, v in orgs.most_common(25)],
           "total_documents": len(rows)}
    for metric in ("publications", "patents", "articles", "reports"):
        db.insert("analytics_trends", {"id": new_id("trd-"), "research_id": research_id, "metric": metric,
                                       "series": out[metric], "method": "annual_counts",
                                       "created_at": iso_now()})
    # грубая оценка динамики для прогноза
    vals = [(p["year"], p["value"]) for p in all_series if p["value"] is not None]
    growth = None
    if len(vals) >= 4:
        first = sum(v for _, v in vals[:len(vals) // 2]) / max(1, len(vals) // 2)
        last = sum(v for _, v in vals[len(vals) // 2:]) / max(1, len(vals) - len(vals) // 2)
        growth = round((last - first) / first, 3) if first else None
    out["growth_rate"] = growth
    out["note"] = "Годы без наблюдений = None (нет данных), не ноль"
    return out


def latest(research_id: str) -> dict:
    rows = db.query("SELECT metric, series FROM analytics_trends WHERE research_id=? ORDER BY created_at DESC LIMIT 8",
                    (research_id,))
    out = {}
    for r in rows:
        r = db.dec(r, "series")
        out.setdefault(r["metric"], r["series"])
    return out
