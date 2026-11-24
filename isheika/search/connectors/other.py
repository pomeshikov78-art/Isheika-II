"""Прочие коннекторы: организации, форумы, код, имитационный DEV-коннектор."""
from __future__ import annotations

import hashlib
import random
import re

from ...contracts import CoreError, Document
from .base import BaseConnector, register


@register
class Ror(BaseConnector):
    code = "CON-ROR"
    evidence_class_default = "official_register"
    doc_type_default = "organization"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        data = self.get_json(self.base_url + "?" + self.qs({"query": expression}), research_id=research_id)
        out = []
        for r in (data.get("items") or [])[:limit]:
            names = r.get("names") or []
            name = next((n.get("value") for n in names if "ror_display" in (n.get("types") or [])), None) or \
                   (names[0].get("value") if names else r.get("id"))
            locs = r.get("locations") or []
            country = ((locs[0].get("geonames_details") or {}).get("country_code")) if locs else None
            out.append(self.doc(
                title=name or "", url=r.get("id") or "", external_id=r.get("id"),
                abstract="Запись реестра организаций ROR (CC0).", country=country,
                doc_type="organization", evidence_class="official_register",
                identifiers={"ror": r.get("id"), "types": r.get("types")}, marker="П"))
        return out


@register
class StackExchange(BaseConnector):
    code = "CON-STACKEXCHANGE"
    evidence_class_default = "forum"
    doc_type_default = "forum"

    SITES = ["electronics", "engineering", "physics", "stackoverflow", "robotics", "space"]

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        terms = [t for t in re.findall(r'"([^"]+)"|(\w+)', expression)]
        words = " ".join((a or b) for a, b in terms if (a or b))[:120]
        out: list[Document] = []
        for site in self.SITES[:3]:
            params = {"order": "desc", "sort": "relevance", "q": words, "site": site,
                      "pagesize": max(3, min(limit // 3, 20)), "filter": "withbody"}
            key = self.secret()
            if key:
                params["key"] = key
            data = self.get_json(self.base_url + "/search/advanced?" + self.qs(params),
                                 research_id=research_id, ttl_s=86400)
            for it in (data.get("items") or []):
                body = re.sub(r"<[^>]+>", " ", it.get("body") or "")
                out.append(self.doc(
                    title=it.get("title") or "", url=it.get("link") or "",
                    external_id=f'{site}:{it.get("question_id")}',
                    abstract=re.sub(r"\s+", " ", body)[:1500],
                    authors=[(it.get("owner") or {}).get("display_name")],
                    published_at=None, language="en", doc_type="forum", evidence_class="forum",
                    identifiers={"site": site, "score": it.get("score"), "is_answered": it.get("is_answered")},
                    license_="CC BY-SA", marker="Р"))
        return out[:limit]


@register
class GitHub(BaseConnector):
    code = "CON-GITHUB"
    evidence_class_default = "dataset"
    doc_type_default = "software"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        words = re.sub(r'["()]', " ", expression)
        words = re.sub(r"\b(OR|AND)\b", " ", words)
        words = re.sub(r"\s+", " ", words).strip()[:120]
        headers = {"Accept": "application/vnd.github+json"}
        tok = self.secret()
        if tok:
            headers["Authorization"] = "Bearer " + tok
        data = self.get_json(self.base_url + "/search/repositories?" + self.qs(
            {"q": words, "per_page": min(limit, 30)}), headers=headers,
            research_id=research_id, ttl_s=86400)
        out = []
        for r in (data.get("items") or []):
            out.append(self.doc(
                title=r.get("full_name") or "", url=r.get("html_url") or "",
                external_id=str(r.get("id")), abstract=r.get("description") or "",
                organizations=[(r.get("owner") or {}).get("login")],
                published_at=(r.get("pushed_at") or "")[:10] or None,
                language="en", doc_type="software", evidence_class="dataset",
                license_=((r.get("license") or {}) or {}).get("spdx_id"),
                identifiers={"stars": r.get("stargazers_count"), "language": r.get("language")},
                marker="Р"))
        return out


@register
class SimConnector(BaseConnector):
    """Имитационный коннектор DEV-профиля.

    Данные НЕ являются реальными источниками: каждый документ помечается
    simulated и не может служить доказательством FACT. Нужен для отладки
    workflow, UI и расчётного ядра без сети и ключей.
    """
    code = "CON-SIM"
    protocol = "SIM"

    TEMPLATES = [
        ("article", "primary_peer_reviewed", "Experimental study of {t}: measured performance",
         "Reported measurements of {t} under laboratory conditions; parameters and test setup described."),
        ("report", "primary_report", "Technical report: {t} prototype trials",
         "Prototype of {t} tested in relevant environment; test protocol and results included."),
        ("patent", "patent", "Patent application: apparatus for {t}",
         "Disclosure of an apparatus for {t}. Legal status: application published. Работоспособность не подтверждена патентом."),
        ("preprint", "preprint", "Preprint: advances in {t}",
         "Early results on {t}; not peer reviewed."),
        ("press_release", "press_release", "Company announces {t} system",
         "Пресс-релиз: заявлены характеристики {t}. Подтверждает факт заявления, не характеристику."),
    ]

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        seed = int(hashlib.sha256((expression or "").encode()).hexdigest()[:8], 16)
        rnd = random.Random(seed)
        topic = re.sub(r'["()]', "", expression)[:60] or "technology"
        out = []
        for i in range(min(limit, 12)):
            dtype, eclass, title_t, abs_t = self.TEMPLATES[i % len(self.TEMPLATES)]
            year = rnd.randint(max(2012, year_from or 2012), min(2026, year_to or 2026))
            country = rnd.choice(["US", "CN", "JP", "DE", "RU", "KR", "FR", "GB", "IN", "SE"])
            out.append(self.doc(
                title=title_t.format(t=topic) + f" [{i+1}]",
                url=f"https://example.invalid/sim/{seed}/{i}",
                external_id=f"SIM-{seed}-{i}", abstract=abs_t.format(t=topic),
                authors=["Simulation Author"], organizations=["SIM Institute"],
                published_at=f"{year}-06-01", language="en", country=country,
                doc_type=dtype, evidence_class=eclass,
                identifiers={"simulated": True}, marker="Д"))
        return out

    def health_check(self) -> dict:
        from ...contracts import iso_now
        return {"code": self.code, "status": "active", "simulated": True, "checked_at": iso_now(),
                "reason": "Имитационный адаптер DEV-профиля"}
