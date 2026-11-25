"""Реестр агентов A01–A12 и постановка задач (ТЗ-02 §4).

Агент извлекает признаки и предлагает гипотезы. Итоговые численные TRL и
реализуемость определяет расчётное ядро ТЗ-03 — агент не может их выставить.
"""
from __future__ import annotations

from ..contracts import iso_now, new_id
from ..storage import db
from ..workflow import events
from . import orchestrator

AGENT_TASKS = [
    ("A01", "query_expansion"), ("A02", "science_analysis"), ("A03", "patent_analysis"),
    ("A04", "industry_analysis"), ("A05", "country_analysis"), ("A06", "tech_analysis"),
    ("A07", "trl_signals"), ("A08", "feasibility_signals"), ("A09", "alternatives"),
    ("A10", "forecast_assumptions"), ("A11", "critique"),
]


def document_package(research_id: str, limit: int = 40) -> list[dict]:
    rows = db.query("""SELECT d.* FROM research_documents d
                       WHERE d.research_id=? AND d.relevance_class IN ('DIRECT','ADJACENT')
                         AND d.decision IN ('INCLUDE','MANUAL_INCLUDE')
                       ORDER BY d.relevance_score DESC LIMIT ?""", (research_id, limit))
    out = []
    for r in rows:
        r = db.dec(r, "authors", "organizations", "identifiers")
        out.append({"id": r["id"], "title": r["title"], "abstract": (r["abstract"] or "")[:1200],
                    "doc_type": r["doc_type"], "evidence_class": r["evidence_class"],
                    "country_code": r["country_code"], "published_at": r["published_at"],
                    "source_code": r["source_code"], "marker": r["marker"],
                    "organizations": r["organizations"], "independence_group": r["independence_group"],
                    "url": r["url"], "relevance": r["relevance_score"], "relevance_class": r["relevance_class"],
                    "simulated": bool((r["identifiers"] or {}).get("simulated"))})
    return out


def run_agents(research_id: str, *, agents: list[str] | None = None, progress_cb=None) -> dict:
    docs = document_package(research_id)
    research = db.dec(db.one("SELECT * FROM core_researches WHERE id=?", (research_id,)),
                      "settings", "country_codes", "language_codes")
    query = db.dec(db.one("SELECT * FROM search_queries WHERE research_id=? ORDER BY created_at DESC LIMIT 1",
                          (research_id,)), "parsed", "expansions", "branches", "exclusions")
    base_payload = {"documents": docs,
                    "query": (query or {}).get("raw_text"),
                    "parsed_query": (query or {}).get("parsed"),
                    "goal": research.get("goal"),
                    "countries": research.get("country_codes"),
                    "period": [research.get("period_from"), research.get("period_to")]}
    selected = agents or [a for a, _ in AGENT_TASKS]
    results, ok, failed, simulated = {}, 0, 0, 0
    for i, (code, task_class) in enumerate([t for t in AGENT_TASKS if t[0] in selected], 1):
        res = orchestrator.execute(research_id, code, task_class, base_payload)
        results[code] = res
        if res["ok"]:
            ok += 1
            if res.get("simulated"):
                simulated += 1
            _claims_from_agent(research_id, code, res)
        else:
            failed += 1
        if progress_cb:
            progress_cb(i, len(selected), f"Агент {code}: {'ok' if res['ok'] else 'нет маршрута'}")
    return {"agents_planned": len(selected), "agents_ok": ok, "agents_failed": failed,
            "simulated_responses": simulated, "documents_in_package": len(docs),
            "results": {k: {"ok": v["ok"], "provider": v.get("provider"), "model": v.get("model"),
                            "simulated": v.get("simulated"), "error": v.get("error")} for k, v in results.items()},
            "_state": "completed" if ok and not failed else ("partial" if ok else "failed")}


def _claims_from_agent(research_id: str, agent_code: str, res: dict) -> None:
    """Преобразование результатов агентов в утверждения (Claim) с типом."""
    s = res.get("structured") or {}
    producer = f'{agent_code}:{res.get("provider")}' + (":simulated" if res.get("simulated") else "")
    items: list[tuple[str, str, list[str]]] = []
    for f in s.get("findings", []) or []:
        items.append((f.get("claim", ""), f.get("claim_type", "ANALYSIS"), f.get("document_ids") or []))
    for c in s.get("countries", []) or []:
        items.append((f'{c.get("iso2")}: {c.get("activity")}', "ANALYSIS", c.get("document_ids") or []))
    for a in s.get("alternatives", []) or []:
        items.append((f'Альтернатива: {a.get("name")} — {a.get("principle", "")[:160]}', "ANALYSIS", a.get("document_ids") or []))
    for a in s.get("assumptions", []) or []:
        items.append((a.get("text", ""), "FORECAST", a.get("document_ids") or []))
    for issue in s.get("issues", []) or []:
        items.append((f'[{issue.get("kind")}] {issue.get("text")}', "ANALYSIS", issue.get("document_ids") or []))
    if s.get("principle"):
        items.append((s["principle"][:900], "ANALYSIS", s.get("document_ids") or []))
    valid_ids = {r["id"] for r in db.query("SELECT id FROM research_documents WHERE research_id=?", (research_id,))}
    for text, ctype, doc_ids in items:
        if not text:
            continue
        if ctype not in ("FACT", "ANALYSIS", "HYPOTHESIS", "FORECAST"):
            ctype = "ANALYSIS"
        doc_ids = [d for d in doc_ids if d in valid_ids]
        if ctype == "FACT" and not doc_ids:
            ctype = "HYPOTHESIS"       # факт без источника не допускается
        if res.get("simulated") and ctype == "FACT":
            ctype = "ANALYSIS"         # имитационный ответ не порождает FACT
        # ИД-24: повторный прогон обновляет утверждение, а не создаёт второе.
        from ..analytics.evidence import upsert_claim
        upsert_claim(research_id, text=text, ctype=ctype, section=agent_code,
                     produced_by=producer, doc_ids=doc_ids, link_from_kind="agent")
    events.emit("evidence.added", research_id=research_id,
                payload={"agent": agent_code, "claims": len(items)})


def signals(research_id: str, agent_code: str) -> dict | None:
    row = db.one("""SELECT r.structured_result FROM ai_results r
                    WHERE r.research_id=? AND r.agent_code=? ORDER BY r.created_at DESC LIMIT 1""",
                 (research_id, agent_code))
    return db.dec(row, "structured_result")["structured_result"] if row else None
