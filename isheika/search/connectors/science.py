"""Коннекторы научных публикаций, препринтов, отчётов и данных (слой S1/S3/S6).

Все реализации используют официальные открытые API. Ни один коннектор не
обходит paywall: полные тексты берутся только там, где это разрешено (OA).
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from ...contracts import CoreError, Document
from .base import BaseConnector, register


def _year(date_str: str | None) -> str | None:
    if not date_str:
        return None
    m = re.search(r"(19|20)\d{2}", str(date_str))
    return m.group(0) + "-01-01" if m else None


def _clean_html(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ------------------------------------------------------------------ OpenAlex
@register
class OpenAlex(BaseConnector):
    code = "CON-OPENALEX"
    evidence_class_default = "primary_peer_reviewed"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        filt = []
        if year_from and year_to:
            filt.append(f"from_publication_date:{year_from}-01-01,to_publication_date:{year_to}-12-31")
        elif year_from:
            filt.append(f"from_publication_date:{year_from}-01-01")
        if languages:
            langs = [l for l in languages if l in ("ru", "en", "de", "fr", "zh", "ja", "es", "pt")]
            if langs and len(langs) < 8:
                filt.append("language:" + "|".join(langs[:4]))
        params = {"search": expression, "per-page": min(limit, 50),
                  "filter": ",".join(filt) if filt else None,
                  "select": "id,doi,title,display_name,publication_year,publication_date,type,language,authorships,primary_location,open_access,abstract_inverted_index,cited_by_count,ids"}
        key = self.secret()
        if key:
            params["api_key"] = key
        if _email():
            params["mailto"] = _email()
        data = self.get_json(self.base_url + "/works?" + self.qs(params), research_id=research_id)
        out = []
        for w in data.get("results", []):
            abstract = _deinvert(w.get("abstract_inverted_index"))
            auths, orgs, countries = [], [], set()
            for a in (w.get("authorships") or [])[:20]:
                au = (a.get("author") or {}).get("display_name")
                if au:
                    auths.append(au)
                for inst in a.get("institutions") or []:
                    if inst.get("display_name"):
                        orgs.append(inst["display_name"])
                    if inst.get("country_code"):
                        countries.add(inst["country_code"])
            loc = w.get("primary_location") or {}
            src = (loc.get("source") or {})
            url = loc.get("landing_page_url") or w.get("id")
            oa = (w.get("open_access") or {})
            dtype = w.get("type") or "article"
            out.append(self.doc(
                title=w.get("display_name") or w.get("title") or "", url=url or w.get("id"),
                external_id=w.get("id"), abstract=abstract, authors=auths, organizations=list(dict.fromkeys(orgs)),
                published_at=w.get("publication_date"), language=w.get("language"),
                country=sorted(countries)[0] if countries else None,
                doc_type="article" if dtype in ("article", "journal-article") else dtype,
                evidence_class="preprint" if dtype == "preprint" else "primary_peer_reviewed",
                doi=(w.get("doi") or "").replace("https://doi.org/", "") or None,
                identifiers={"openalex": w.get("id"), "cited_by_count": w.get("cited_by_count")},
                license_=src.get("license"), oa_status=oa.get("oa_status"), marker="П"))
        return out


def _deinvert(idx: dict | None) -> str:
    if not idx:
        return ""
    pos: dict[int, str] = {}
    for word, places in idx.items():
        for p in places:
            pos[p] = word
    return " ".join(pos[k] for k in sorted(pos))[:6000]


# ------------------------------------------------------------------ Crossref
@register
class Crossref(BaseConnector):
    code = "CON-CROSSREF"
    evidence_class_default = "primary_peer_reviewed"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        filt = []
        if year_from:
            filt.append(f"from-pub-date:{year_from}-01-01")
        if year_to:
            filt.append(f"until-pub-date:{year_to}-12-31")
        params = {"query": expression, "rows": min(limit, 50),
                  "filter": ",".join(filt) if filt else None,
                  "select": "DOI,title,author,container-title,published,type,abstract,URL,license,subject,issued"}
        if _email():
            params["mailto"] = _email()     # polite pool: 3 req/s
        data = self.get_json(self.base_url + "/works?" + self.qs(params), research_id=research_id)
        out = []
        for w in (data.get("message", {}).get("items") or []):
            title = (w.get("title") or [""])[0]
            date_parts = ((w.get("issued") or {}).get("date-parts") or [[None]])[0]
            pub = "-".join(f"{int(x):02d}" if i else str(x) for i, x in enumerate(date_parts) if x) if date_parts and date_parts[0] else None
            auths = [f'{a.get("given","")} {a.get("family","")}'.strip() for a in (w.get("author") or [])[:20]]
            orgs = [a.get("name") for a in (w.get("author") or []) if a.get("name")]
            out.append(self.doc(
                title=_clean_html(title), url=w.get("URL") or ("https://doi.org/" + w.get("DOI", "")),
                external_id=w.get("DOI"), abstract=_clean_html(w.get("abstract")),
                authors=[a for a in auths if a], organizations=[o for o in orgs if o],
                published_at=pub, language=None,
                doc_type=w.get("type") or "article",
                evidence_class="primary_peer_reviewed" if w.get("type") in ("journal-article", "proceedings-article") else "unknown",
                doi=w.get("DOI"), identifiers={"crossref_subject": w.get("subject")},
                license_=(w.get("license") or [{}])[0].get("URL"), marker="П"))
        return out


# ------------------------------------------------------------------ arXiv
@register
class Arxiv(BaseConnector):
    code = "CON-ARXIV"
    robots_policy = "api_terms"
    protocol = "ATOM"
    evidence_class_default = "preprint"
    doc_type_default = "preprint"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        terms = re.findall(r'"([^"]+)"|(\S+)', expression)
        parts = [a or b for a, b in terms if (a or b) and a not in ("OR", "AND") and b not in ("OR", "AND")]
        parts = [p for p in parts if p not in ("OR", "AND", "(", ")")][:6]
        query = " OR ".join(f'all:"{p}"' for p in parts) or f"all:{expression}"
        url = self.base_url + "?" + self.qs({"search_query": query, "start": 0,
                                             "max_results": min(limit, 50),
                                             "sortBy": "relevance", "sortOrder": "descending"})
        res = self.get(url, research_id=research_id)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        try:
            root = ET.fromstring(res["body"])
        except ET.ParseError as e:
            raise CoreError("E_SCHEMA", f"arXiv: некорректный Atom ({e})")
        out = []
        for e in root.findall("a:entry", ns):
            title = (e.findtext("a:title", "", ns) or "").strip()
            link = e.findtext("a:id", "", ns)
            summary = _clean_html(e.findtext("a:summary", "", ns))
            published = e.findtext("a:published", "", ns)
            auths = [a.findtext("a:name", "", ns) for a in e.findall("a:author", ns)]
            out.append(self.doc(title=title, url=link, external_id=link.rsplit("/", 1)[-1],
                                abstract=summary, authors=auths, published_at=published[:10] or None,
                                language="en", doc_type="preprint", evidence_class="preprint",
                                identifiers={"arxiv": link.rsplit("/", 1)[-1]}, marker="П"))
        return out


# ------------------------------------------------------------------ DOAJ
@register
class Doaj(BaseConnector):
    code = "CON-DOAJ"
    evidence_class_default = "primary_peer_reviewed"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        import urllib.parse
        q = urllib.parse.quote(expression, safe="")
        url = f"{self.base_url}/search/articles/{q}?" + self.qs({"pageSize": min(limit, 50)})
        data = self.get_json(url, research_id=research_id)
        out = []
        for r in data.get("results", []):
            b = r.get("bibjson", {})
            links = [l.get("url") for l in (b.get("link") or []) if l.get("url")]
            doi = next((i.get("id") for i in (b.get("identifier") or []) if i.get("type") == "doi"), None)
            out.append(self.doc(
                title=b.get("title", ""), url=links[0] if links else (f"https://doi.org/{doi}" if doi else "https://doaj.org/article/" + r.get("id", "")),
                external_id=r.get("id"), abstract=b.get("abstract", ""),
                authors=[a.get("name") for a in (b.get("author") or []) if a.get("name")],
                organizations=[a.get("affiliation") for a in (b.get("author") or []) if a.get("affiliation")],
                published_at=f'{b.get("year")}-{str(b.get("month") or 1).zfill(2)}-01' if b.get("year") else None,
                language=(b.get("language") or [None])[0], country=None,
                doc_type="article", evidence_class="primary_peer_reviewed", doi=doi,
                license_=b.get("license", [{}])[0].get("type") if b.get("license") else None,
                oa_status="gold", identifiers={"journal": (b.get("journal") or {}).get("title")}, marker="П"))
        return out


# ------------------------------------------------------------------ Europe PMC
@register
class EuropePMC(BaseConnector):
    code = "CON-EUROPEPMC"
    evidence_class_default = "primary_peer_reviewed"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        q = expression
        if year_from or year_to:
            q += f' AND (FIRST_PDATE:[{year_from or 1900}-01-01 TO {year_to or 2100}-12-31])'
        data = self.get_json(self.base_url + "/search?" + self.qs(
            {"query": q, "format": "json", "pageSize": min(limit, 50), "resultType": "core"}),
            research_id=research_id)
        out = []
        for r in (data.get("resultList", {}).get("result") or []):
            doi = r.get("doi")
            url = f'https://europepmc.org/article/{r.get("source")}/{r.get("id")}'
            out.append(self.doc(
                title=_clean_html(r.get("title")), url=url, external_id=r.get("id"),
                abstract=_clean_html(r.get("abstractText")),
                authors=[a.strip() for a in (r.get("authorString") or "").split(",") if a.strip()][:20],
                organizations=[], published_at=r.get("firstPublicationDate"),
                language=r.get("language"), doc_type="article",
                evidence_class="preprint" if r.get("source") == "PPR" else "primary_peer_reviewed",
                doi=doi, oa_status="oa" if r.get("isOpenAccess") == "Y" else None,
                identifiers={"pmid": r.get("pmid"), "pmcid": r.get("pmcid")}, marker="П"))
        return out


# ------------------------------------------------------------------ DataCite
@register
class DataCite(BaseConnector):
    code = "CON-DATACITE"
    evidence_class_default = "dataset"
    doc_type_default = "dataset"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        data = self.get_json(self.base_url + "/dois?" + self.qs(
            {"query": expression, "page[size]": min(limit, 50)}), research_id=research_id)
        out = []
        for r in data.get("data", []):
            a = r.get("attributes", {})
            titles = a.get("titles") or [{}]
            desc = " ".join(d.get("description", "") for d in (a.get("descriptions") or []))
            creators = [c.get("name") for c in (a.get("creators") or []) if c.get("name")]
            out.append(self.doc(
                title=titles[0].get("title", ""), url=a.get("url") or f'https://doi.org/{a.get("doi")}',
                external_id=a.get("doi"), abstract=desc[:4000], authors=creators[:20],
                published_at=str(a.get("publicationYear")) + "-01-01" if a.get("publicationYear") else None,
                language=a.get("language"), doc_type=(a.get("types") or {}).get("resourceTypeGeneral", "dataset").lower(),
                evidence_class="dataset", doi=a.get("doi"),
                identifiers={"datacite": r.get("id")}, marker="Р"))
        return out


# ------------------------------------------------------------------ OSTI.GOV
@register
class Osti(BaseConnector):
    code = "CON-OSTI"
    protocol = "XML"
    evidence_class_default = "primary_report"
    doc_type_default = "report"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        expr = self.simplify(expression, max_terms=6)
        res = self.get(self.base_url + "?" + self.qs({"q": expr, "rows": min(limit, 50)}),
                       headers={"Accept": "application/json"}, research_id=research_id)
        body = res["body"].lstrip()
        if body.startswith("[") or body.startswith("{"):
            import json as _json
            try:
                data = _json.loads(body)
            except Exception as e:
                raise CoreError("E_SCHEMA", f"OSTI: некорректный JSON ({e})")
            recs = data if isinstance(data, list) else data.get("records", [])
            out = []
            for r in recs:
                osti_id = str(r.get("osti_id") or r.get("ostiId") or "")
                links = r.get("links") or []
                url = next((l.get("href") for l in links if isinstance(l, dict) and l.get("href")),
                           f"https://www.osti.gov/biblio/{osti_id}")
                authors = r.get("authors") or []
                out.append(self.doc(
                    title=r.get("title") or "", url=url, external_id=osti_id,
                    abstract=(r.get("description") or "")[:4000],
                    authors=[a if isinstance(a, str) else a.get("name", "") for a in authors][:20],
                    organizations=r.get("research_orgs") or [], country="US",
                    published_at=r.get("publication_date") or r.get("entry_date"),
                    language="en", doc_type="report", evidence_class="primary_report",
                    doi=r.get("doi"), identifiers={"osti": osti_id}, marker="П"))
            return out
        try:
            root = ET.fromstring(res["body"])
        except ET.ParseError as e:
            raise CoreError("E_SCHEMA", f"OSTI: некорректный XML ({e})")
        out = []
        for rec in root.findall("record"):
            title = rec.findtext("title") or ""
            osti_id = rec.findtext("osti_id") or ""
            links = [l.text for l in rec.findall("link") if l.text]
            url = next((l for l in links if l.startswith("http")), f"https://www.osti.gov/biblio/{osti_id}")
            authors = [a.text for a in rec.findall("author") if a.text]
            orgs = [o.text for o in rec.findall("research_org") if o.text]
            out.append(self.doc(
                title=title, url=url, external_id=osti_id,
                abstract=(rec.findtext("description") or "")[:4000],
                authors=authors[:20], organizations=orgs[:10], country="US",
                published_at=(rec.findtext("publication_date") or None), language="en",
                doc_type="report", evidence_class="primary_report",
                doi=rec.findtext("doi"), identifiers={"osti": osti_id}, marker="П"))
        return out


# ------------------------------------------------------------------ HAL
@register
class Hal(BaseConnector):
    code = "CON-HAL"
    evidence_class_default = "primary_peer_reviewed"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        params = {"q": expression, "rows": min(limit, 50), "wt": "json",
                  "fl": "docid,title_s,abstract_s,authFullName_s,labStructName_s,producedDate_s,uri_s,language_s,docType_s,doiId_s,files_s,journalTitle_s"}
        data = self.get_json(self.base_url + "?" + self.qs(params), research_id=research_id)
        out = []
        for d in (data.get("response", {}).get("docs") or []):
            title = (d.get("title_s") or [""])[0]
            out.append(self.doc(
                title=title, url=d.get("uri_s") or f'https://hal.science/{d.get("docid")}',
                external_id=str(d.get("docid")), abstract=(d.get("abstract_s") or [""])[0],
                authors=d.get("authFullName_s") or [], organizations=d.get("labStructName_s") or [],
                published_at=(d.get("producedDate_s") or None), language=(d.get("language_s") or [None])[0],
                country="FR", doc_type=(d.get("docType_s") or "article").lower(),
                evidence_class="thesis" if d.get("docType_s") == "THESE" else "primary_peer_reviewed",
                doi=d.get("doiId_s"), identifiers={"hal": d.get("docid")}, marker="П"))
        return out


# ------------------------------------------------------------------ Zenodo
@register
class Zenodo(BaseConnector):
    code = "CON-ZENODO"
    evidence_class_default = "dataset"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        data = self.get_json(self.base_url + "?" + self.qs({"q": expression, "size": min(limit, 50)}),
                             research_id=research_id)
        out = []
        for h in (data.get("hits", {}).get("hits") or []):
            md = h.get("metadata", {})
            creators = [c.get("name") for c in (md.get("creators") or []) if c.get("name")]
            out.append(self.doc(
                title=md.get("title", ""), url=h.get("links", {}).get("self_html") or f'https://zenodo.org/records/{h.get("id")}',
                external_id=str(h.get("id")), abstract=_clean_html(md.get("description")),
                authors=creators[:20], published_at=md.get("publication_date"),
                doc_type=(md.get("resource_type") or {}).get("type", "dataset").lower(),
                evidence_class="dataset", doi=h.get("doi"),
                license_=(md.get("license") or {}).get("id"), oa_status="open",
                identifiers={"zenodo": h.get("id")}, marker="Р"))
        return out


# ------------------------------------------------------------------ OpenAIRE
@register
class OpenAIRE(BaseConnector):
    code = "CON-OPENAIRE"
    evidence_class_default = "primary_peer_reviewed"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        # OpenAIRE: не более 4 логических операторов в запросе
        expr = self.simplify(expression, max_terms=4)
        data = self.get_json(self.base_url + "?" + self.qs(
            {"search": expr, "pageSize": min(limit, 50)}), research_id=research_id)
        out = []
        for r in (data.get("results") or []):
            titles = r.get("mainTitle") or r.get("titles") or ""
            authors = [a.get("fullName") or a.get("name") for a in (r.get("authors") or []) if isinstance(a, dict)]
            pids = [p.get("value") for p in (r.get("pids") or []) if isinstance(p, dict)]
            doi = next((p for p in pids if p and p.startswith("10.")), None)
            url = r.get("websiteUrl") or (f"https://doi.org/{doi}" if doi else None) or r.get("id")
            out.append(self.doc(
                title=titles if isinstance(titles, str) else str(titles), url=url or "",
                external_id=r.get("id"), abstract=_clean_html(r.get("descriptions") if isinstance(r.get("descriptions"), str) else ""),
                authors=[a for a in authors if a][:20],
                published_at=r.get("publicationDate"), language=(r.get("language") or {}).get("code") if isinstance(r.get("language"), dict) else None,
                doc_type=(r.get("type") or "article").lower(), evidence_class="primary_peer_reviewed",
                doi=doi, identifiers={"openaire": r.get("id")}, marker="П"))
        return out


# ------------------------------------------------------------------ CORE
@register
class Core(BaseConnector):
    code = "CON-CORE"
    evidence_class_default = "primary_peer_reviewed"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        key = self.secret()
        if not key:
            raise CoreError("E_POLICY", "CORE требует API-ключ (A1)")
        payload = {"q": expression, "limit": min(limit, 50)}
        if year_from:
            payload["q"] += f" AND yearPublished>={year_from}"
        import json
        # CORE v3 search/works: GET с параметром q (скачивание PDF в обход API запрещено)
        url = self.base_url + "/search/works?" + self.qs({"q": payload["q"], "limit": payload["limit"]})
        data = self.get_json(url, headers={"Authorization": "Bearer " + key}, research_id=research_id)
        out = []
        for r in (data.get("results") or []):
            out.append(self.doc(
                title=r.get("title") or "", url=r.get("downloadUrl") or r.get("sourceFulltextUrls", [None])[0] or r.get("links", [{}])[0].get("url", ""),
                external_id=str(r.get("id")), abstract=r.get("abstract") or "",
                authors=[a.get("name") for a in (r.get("authors") or []) if isinstance(a, dict)][:20],
                published_at=r.get("publishedDate") or (str(r.get("yearPublished")) + "-01-01" if r.get("yearPublished") else None),
                language=(r.get("language") or {}).get("code") if isinstance(r.get("language"), dict) else None,
                doc_type="article", evidence_class="primary_peer_reviewed", doi=r.get("doi"),
                identifiers={"core": r.get("id"), "oai": r.get("oai")}, marker="П"))
        return out


# ------------------------------------------------------------------ Semantic Scholar
@register
class SemanticScholar(BaseConnector):
    code = "CON-S2AG"
    evidence_class_default = "primary_peer_reviewed"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        params = {"query": expression, "limit": min(limit, 50),
                  "fields": "title,abstract,year,publicationDate,externalIds,url,authors,openAccessPdf,publicationTypes,venue"}
        if year_from or year_to:
            params["year"] = f"{year_from or ''}-{year_to or ''}"
        headers = {}
        key = self.secret()
        if key:
            headers["x-api-key"] = key
        data = self.get_json(self.base_url + "/paper/search?" + self.qs(params),
                             headers=headers, research_id=research_id)
        out = []
        for r in (data.get("data") or []):
            ids = r.get("externalIds") or {}
            out.append(self.doc(
                title=r.get("title") or "", url=r.get("url") or "", external_id=r.get("paperId"),
                abstract=r.get("abstract") or "", authors=[a.get("name") for a in (r.get("authors") or [])][:20],
                published_at=r.get("publicationDate") or (str(r.get("year")) + "-01-01" if r.get("year") else None),
                doc_type="article", evidence_class="primary_peer_reviewed", doi=ids.get("DOI"),
                oa_status="oa" if r.get("openAccessPdf") else None,
                identifiers={"s2": r.get("paperId"), "arxiv": ids.get("ArXiv")}, marker="П"))
        return out


# ------------------------------------------------------------------ NASA NTRS
@register
class Ntrs(BaseConnector):
    code = "CON-NTRS"
    evidence_class_default = "primary_report"
    doc_type_default = "report"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        url = self.base_url + "?" + self.qs({"q": expression, "pageSize": min(limit, 50)})
        data = self.get_json(url, headers={"Accept": "application/json"}, research_id=research_id)
        out = []
        for r in (data.get("results") or data.get("data") or []):
            rid = str(r.get("id") or r.get("citationId") or "")
            out.append(self.doc(
                title=r.get("title") or "", url=f"https://ntrs.nasa.gov/citations/{rid}",
                external_id=rid, abstract=r.get("abstract") or "",
                authors=[a.get("name") for a in (r.get("authorAffiliations") or []) if isinstance(a, dict)][:20],
                published_at=r.get("publicationsDate") or r.get("created"), country="US",
                doc_type="report", evidence_class="primary_report",
                identifiers={"ntrs": rid}, marker="П"))
        return out


# ------------------------------------------------------------------ Unpaywall (обогащение)
@register
class Unpaywall(BaseConnector):
    code = "CON-UNPAYWALL"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        raise CoreError("E_POLICY", "Unpaywall — сервис обогащения по DOI, не поисковый источник")

    def lookup(self, doi: str, research_id: str | None = None) -> dict | None:
        email = _email()
        if not email:
            return None
        data = self.get_json(f"{self.base_url}/{doi}?" + self.qs({"email": email}), research_id=research_id)
        best = data.get("best_oa_location") or {}
        return {"is_oa": data.get("is_oa"), "oa_url": best.get("url_for_pdf") or best.get("url"),
                "license": best.get("license"), "host_type": best.get("host_type")}


from ...config import SETTINGS as _S


def _email() -> str:
    """Актуальный e-mail для polite pool / Unpaywall (не кэшируется)."""
    return _S.contact_email or ""
