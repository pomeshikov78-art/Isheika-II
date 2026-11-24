"""Патентные коннекторы (слой S2).

EPO OPS — OAuth2 client credentials, недельный бюджет байт, ночное окно.
USPTO ODP — X-API-KEY, миграция PatentsView 20.03.2026 учтена.
Патент подтверждает раскрытие/заявку/правовой статус, но НЕ работоспособность.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.parse

from ...contracts import CoreError, Document
from ...storage.secrets import SecretStore
from .base import BaseConnector, register

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


@register
class EpoOps(BaseConnector):
    code = "CON-EPO-OPS"
    evidence_class_default = "patent"
    doc_type_default = "patent"
    heavy = True

    def _token(self) -> str:
        raw = SecretStore.get("epo_ops_key") or ""
        if ":" not in raw:
            raise CoreError("E_AUTH", "EPO OPS: ожидается ключ в формате consumer_key:consumer_secret")
        cached = _TOKEN_CACHE.get(raw)
        if cached and cached[1] > time.time() + 30:
            return cached[0]
        from .. import http
        auth = base64.b64encode(raw.encode()).decode()
        res = http.request("https://ops.epo.org/3.2/auth/accesstoken", method="POST",
                           headers={"Authorization": "Basic " + auth,
                                    "Content-Type": "application/x-www-form-urlencoded"},
                           data=b"grant_type=client_credentials", connector=self.meta, ttl_s=-1)
        try:
            tok = json.loads(res["body"])["access_token"]
        except Exception:
            raise CoreError("E_AUTH", "EPO OPS: не удалось получить токен")
        _TOKEN_CACHE[raw] = (tok, time.time() + 1100)
        return tok

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        token = self._token()
        q = "txt=" + urllib.parse.quote(expression.replace('"', ""))
        if year_from or year_to:
            q += f" and pd within \"{year_from or 1900},{year_to or 2100}\""
        url = f"{self.base_url}/published-data/search?" + self.qs({"q": q, "Range": f"1-{min(limit,25)}"})
        res = self.get(url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
                       research_id=research_id, ttl_s=30 * 86400)
        try:
            data = json.loads(res["body"])
        except Exception:
            raise CoreError("E_SCHEMA", "EPO OPS: ответ не JSON")
        wpd = data.get("ops:world-patent-data", {})
        bib = wpd.get("ops:biblio-search", {})
        refs = (((bib.get("ops:search-result") or {}).get("ops:publication-reference")) or
                ((bib.get("ops:search-result") or {}).get("exchange-documents")) or [])
        if isinstance(refs, dict):
            refs = [refs]
        out = []
        for r in refs:
            docid = r.get("document-id", {})
            if isinstance(docid, list):
                docid = docid[0]
            country = docid.get("country", {}).get("$")
            number = docid.get("doc-number", {}).get("$")
            kind = docid.get("kind", {}).get("$")
            date = docid.get("date", {}).get("$")
            pub = f"{country}{number}{kind}" if country and number else None
            if not pub:
                continue
            out.append(self.doc(
                title=f"Патентная публикация {pub}",
                url=f"https://worldwide.espacenet.com/patent/search?q=pn%3D{pub}",
                external_id=pub, abstract="Библиографические данные EPO OPS. Правовой статус требует отдельного запроса INPADOC.",
                published_at=f"{date[:4]}-{date[4:6]}-{date[6:8]}" if date and len(date) == 8 else None,
                country=country, doc_type="patent", evidence_class="patent",
                identifiers={"publication": pub, "kind": kind}, marker="П"))
        return out


@register
class UsptoOdp(BaseConnector):
    code = "CON-USPTO-ODP"
    evidence_class_default = "patent"
    doc_type_default = "patent"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        key = self.secret()
        if not key:
            raise CoreError("E_POLICY", "USPTO ODP требует ключ (USPTO.gov + ID.me)")
        params = {"q": expression, "pagination[limit]": min(limit, 25),
                  "pagination[offset]": 0}
        data = self.get_json(self.base_url + "?" + self.qs(params),
                             headers={"X-API-KEY": key, "Accept": "application/json"},
                             research_id=research_id, ttl_s=30 * 86400)
        out = []
        items = data.get("patentFileWrapperDataBag") or data.get("results") or data.get("data") or []
        for r in items:
            meta = r.get("applicationMetaData") or r
            app_no = r.get("applicationNumberText") or meta.get("applicationNumberText")
            title = meta.get("inventionTitle") or r.get("title") or f"USPTO application {app_no}"
            date = meta.get("filingDate") or r.get("filingDate")
            assignees = [a.get("assigneeName") for a in (meta.get("assigneeBag") or []) if isinstance(a, dict)]
            out.append(self.doc(
                title=title, url=f"https://patentcenter.uspto.gov/applications/{app_no}" if app_no else "https://developer.uspto.gov/",
                external_id=str(app_no), abstract=(meta.get("abstractText") or "")[:4000],
                organizations=[a for a in assignees if a], country="US",
                published_at=date, doc_type="patent", evidence_class="patent",
                identifiers={"application": app_no, "status": meta.get("applicationStatusCode")}, marker="П"))
        return out


@register
class Kipris(BaseConnector):
    code = "CON-KIPRIS"
    evidence_class_default = "patent"
    doc_type_default = "patent"

    def search(self, expression, *, limit=20, year_from=None, year_to=None, languages=None, research_id=None):
        raise CoreError("E_POLICY", "KIPRIS Plus: коннектор в статусе CANDIDATE (реализация не завершена). "
                                    "Используйте EPO OPS как резервный маршрут.")
