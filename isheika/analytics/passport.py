"""Паспорт технологии (ТЗ-01 §6, ТЗ-05 §6.1).

Каждый ключевой тезис имеет Claim ID и связь с Evidence. Утверждения
маркируются FACT / ANALYSIS / HYPOTHESIS / FORECAST.
"""
from __future__ import annotations

from collections import Counter

from ..contracts import iso_now, new_id
from ..storage import db
from . import evidence as E


def build(research_id: str) -> dict:
    research = db.dec(db.one("SELECT * FROM core_researches WHERE id=?", (research_id,)),
                      "settings", "country_codes", "language_codes")
    query = db.dec(db.one("SELECT * FROM search_queries WHERE research_id=? ORDER BY created_at DESC LIMIT 1",
                          (research_id,)), "parsed", "expansions")
    docs = [db.dec(r, "authors", "organizations", "identifiers") for r in
            db.query("SELECT * FROM research_documents WHERE research_id=? AND relevance_class IN ('DIRECT','ADJACENT')", (research_id,))]
    trl = db.dec(db.one("SELECT * FROM analytics_trl WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,)),
                 "criteria", "gaps")
    fea = db.dec(db.one("SELECT * FROM analytics_feasibility WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,)),
                 "factors", "sensitivity")
    from ..ai import agents as A
    tech = A.signals(research_id, "A06") or {}
    claims = db.query("SELECT * FROM knowledge_claims WHERE research_id=? ORDER BY claim_type, created_at", (research_id,))

    def claim_refs(section: str | None = None, ctype: str | None = None, limit: int = 12) -> list[dict]:
        out = []
        for c in claims:
            if section and c["section"] != section:
                continue
            if ctype and c["claim_type"] != ctype:
                continue
            ev = db.query("SELECT id, document_id, url, quote, locator, evidence_class, quality, status FROM evidence_items WHERE claim_id=? LIMIT 3",
                          (c["id"],))
            out.append({"claim_id": c["id"], "text": c["claim_text"], "type": c["claim_type"],
                        "status": c["status"], "confidence": c["confidence"], "evidence": ev})
            if len(out) >= limit:
                break
        return out

    countries = Counter(d["country_code"] for d in docs if d["country_code"])
    orgs = Counter(o for d in docs for o in (d["organizations"] or []) if o)
    years = sorted(int(d["published_at"][:4]) for d in docs if (d["published_at"] or "")[:4].isdigit())
    passport = {
        "identification": {
            "name": research["title"], "research_id": research_id,
            "query": (query or {}).get("raw_text"),
            "entities": ((query or {}).get("parsed") or {}).get("entities"),
            "purpose": ((query or {}).get("parsed") or {}).get("purpose"),
        },
        "purpose_and_principle": {
            "principle": tech.get("principle") or "Недостаточно данных для описания принципа действия",
            "claims": claim_refs("A06", limit=6),
        },
        "architecture_components": {"components": tech.get("components") or [],
                                    "note": "Компоненты извлечены из корпуса; требуют экспертного подтверждения"},
        "parameters": {"measured": tech.get("parameters") or [],
                       "note": "Только значения, присутствующие в источниках. Отсутствующее значение не подставляется."},
        "science_base": {"documents": sum(1 for d in docs if d["evidence_class"] in ("primary_peer_reviewed", "preprint")),
                         "claims": claim_refs("A02", limit=10)},
        "patent_base": {"documents": sum(1 for d in docs if d["doc_type"] == "patent"),
                        "claims": claim_refs("A03", limit=10),
                        "note": "Патент не подтверждает работоспособность изделия"},
        "industry_base": {"organizations": orgs.most_common(15),
                          "claims": claim_refs("A04", limit=10)},
        "countries": [{"iso2": k, "documents": v} for k, v in countries.most_common(40)],
        "period": {"first_year": years[0] if years else None, "last_year": years[-1] if years else None},
        "trl": {"value": (trl or {}).get("trl"), "confidence": (trl or {}).get("confidence"),
                "gaps": (trl or {}).get("gaps", [])[:12], "assessment_id": (trl or {}).get("id")},
        "feasibility": {"value": (fea or {}).get("score"), "coverage": (fea or {}).get("coverage"),
                        "range": [(fea or {}).get("range_low"), (fea or {}).get("range_high")],
                        "interpretation": (fea or {}).get("interpretation"),
                        "assessment_id": (fea or {}).get("id")},
        "barriers": [db.dec(r, "evidence_ids") for r in
                     db.query("SELECT * FROM analytics_barriers WHERE research_id=? ORDER BY criticality DESC LIMIT 12", (research_id,))],
        "alternatives": [db.dec(r, "criteria") for r in
                         db.query("SELECT * FROM analytics_alternatives WHERE research_id=? LIMIT 12", (research_id,))],
        "evidence_summary": E.summary(research_id),
        "claim_type_counts": dict(Counter(c["claim_type"] for c in claims)),
        "limitations": [
            "Открытые источники не покрывают закрытые и ведомственные материалы",
            "Квоты API ограничивают полноту выборки",
            "Калибровка методик не завершена (стартовые веса и пороги)",
        ],
    }
    tid = db.one("SELECT id FROM knowledge_technologies WHERE research_id=? LIMIT 1", (research_id,))
    if tid:
        db.update("knowledge_technologies", "id", tid["id"],
                  {"passport": passport, "trl": (trl or {}).get("trl"),
                   "feasibility": (fea or {}).get("score"), "coverage": (fea or {}).get("coverage"),
                   "status": "ready", "updated_at": iso_now()})
        technology_id = tid["id"]
    else:
        technology_id = new_id("tec-")
        db.insert("knowledge_technologies", {
            "id": technology_id, "research_id": research_id, "name": research["title"],
            "passport": passport, "trl": (trl or {}).get("trl"), "feasibility": (fea or {}).get("score"),
            "coverage": (fea or {}).get("coverage"), "status": "ready",
            "created_at": iso_now(), "updated_at": iso_now()})
    db.execute("UPDATE knowledge_claims SET technology_id=? WHERE research_id=? AND technology_id IS NULL",
               (technology_id, research_id))
    return {"technology_id": technology_id, "passport": passport}


def get(research_id: str) -> dict | None:
    row = db.one("SELECT * FROM knowledge_technologies WHERE research_id=? ORDER BY updated_at DESC LIMIT 1", (research_id,))
    return db.dec(row, "passport")
