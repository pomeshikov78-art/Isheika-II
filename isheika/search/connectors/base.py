"""Базовый коннектор (ТЗ-01 §5, ТЗ-05 C-компоненты поискового контура).

Каждый коннектор обязан:
  * вернуть документы в единой схеме (normalize);
  * сообщить фактические лимиты/остатки, а не выдуманные;
  * уметь health_check (HTTP-код + проверка структуры ответа);
  * не обходить авторизацию, paywall, CAPTCHA и robots.txt.
Коннектор без ключа не «притворяется» работающим: он возвращает понятный
статус RESTRICTED / requires_key.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

from ...config import SETTINGS
from ...contracts import CoreError, Document, iso_now, new_id
from ...storage import db
from ...storage.secrets import SecretStore
from .. import http


class BaseConnector:
    code = "CON-BASE"
    protocol = "REST"
    doc_type_default = "article"
    evidence_class_default = "unknown"
    heavy = False

    def __init__(self, meta: dict):
        self.meta = meta
        self.code = meta["code"]
        self.base_url = meta.get("base_url") or ""
        self.limits = meta.get("limits") or {}
        self.capabilities = meta.get("capabilities") or {}

    # -------------------------------------------------- служебное
    def secret(self) -> str | None:
        ref = self.meta.get("secret_ref")
        if not ref:
            return None
        if ref == "contact_email":
            return SETTINGS.contact_email or None
        return SecretStore.get(ref)

    def available(self) -> tuple[bool, str]:
        if not self.meta.get("enabled", 1):
            return False, "Коннектор отключён"
        if self.meta.get("implementation") == "manual":
            return False, "Только ручной режим аналитика (автоматизация запрещена ToS)"
        if self.meta.get("implementation") == "stub":
            return False, "Реализация коннектора не завершена (каталог ≠ подключение)"
        if self.meta.get("requires_key") and not self.secret():
            return False, "Требуется ключ/регистрация — источник в статусе RESTRICTED"
        if self.meta.get("paid") and not SETTINGS.allow_paid_ai:
            return False, "Платный маршрут заблокирован политикой"
        return True, ""

    robots_policy = "respect"

    def get(self, url: str, *, headers: dict | None = None, research_id: str | None = None,
            ttl_s: int = 7 * 86400, timeout: float | None = None) -> dict:
        meta = dict(self.meta)
        meta["robots_policy"] = self.meta.get("robots_policy") or self.robots_policy
        return http.request(url, headers=headers, connector=meta, research_id=research_id,
                            ttl_s=ttl_s, timeout=timeout, heavy=self.heavy)

    def get_json(self, url: str, **kw: Any) -> Any:
        res = self.get(url, **kw)
        import json
        try:
            return json.loads(res["body"])
        except Exception as e:
            raise CoreError("E_SCHEMA", f"{self.code}: ответ не JSON ({e})", url=url)

    @staticmethod
    def terms(expression: str) -> list[str]:
        """Термы выражения: фразы в кавычках и одиночные слова (без операторов)."""
        out = []
        for m in re.finditer(r'"([^"]+)"|([A-Za-zА-Яа-яЁё0-9][\w\-]*)', expression or ""):
            t = (m.group(1) or m.group(2) or "").strip()
            if t and t.upper() not in ("OR", "AND", "NOT"):
                out.append(t)
        return list(dict.fromkeys(out))

    def simplify(self, expression: str, max_terms: int = 4, *, quote_all: bool = False) -> str:
        """Адаптация выражения под ограничения конкретного API (напр. OpenAIRE: ≤4 оператора)."""
        terms = self.terms(expression)[:max_terms]
        if not terms:
            return expression
        return " OR ".join(f'"{t}"' if (quote_all or " " in t) else t for t in terms)

    @staticmethod
    def qs(params: dict) -> str:
        return urllib.parse.urlencode({k: v for k, v in params.items() if v is not None},
                                      quote_via=urllib.parse.quote)

    # -------------------------------------------------- переопределяемое
    def search(self, expression: str, *, limit: int = 20, year_from: int | None = None,
               year_to: int | None = None, languages: list[str] | None = None,
               research_id: str | None = None) -> list[Document]:
        raise NotImplementedError

    def health_check(self) -> dict:
        """Фактическая проверка: HTTP-код, структура ответа, время."""
        ok, reason = self.available()
        if not ok:
            return {"code": self.code, "status": "restricted" if "ключ" in reason else "unavailable",
                    "reason": reason, "checked_at": iso_now()}
        try:
            docs = self.search("test", limit=1)
            return {"code": self.code, "status": "active" if docs else "degraded",
                    "sample": len(docs), "checked_at": iso_now(),
                    "reason": "" if docs else "Ответ получен, но документы не извлечены"}
        except CoreError as e:
            return {"code": self.code, "status": "error", "reason": e.error.message,
                    "error_code": e.error.code, "checked_at": iso_now()}
        except Exception as e:  # noqa: BLE001
            return {"code": self.code, "status": "error", "reason": str(e)[:200], "checked_at": iso_now()}

    # -------------------------------------------------- фабрика документов
    def doc(self, *, title: str, url: str, external_id: str | None = None,
            abstract: str = "", authors: list[str] | None = None,
            organizations: list[str] | None = None, published_at: str | None = None,
            language: str | None = None, country: str | None = None,
            doc_type: str | None = None, evidence_class: str | None = None,
            doi: str | None = None, identifiers: dict | None = None,
            license_: str | None = None, oa_status: str | None = None,
            marker: str = "Р", excerpt: str = "") -> Document:
        return Document(
            document_id=new_id("doc-"), source_code=self.meta.get("source_code") or self.code,
            connector_code=self.code, external_id=external_id, title=(title or "").strip()[:900],
            url=url, doc_type=doc_type or self.doc_type_default,
            authors=authors or [], organizations=organizations or [],
            country_iso2=country, language=language, published_at=published_at,
            abstract=(abstract or "")[:6000], text_excerpt=(excerpt or "")[:4000],
            license=license_, oa_status=oa_status, doi=doi, identifiers=identifiers or {},
            evidence_class=evidence_class or self.evidence_class_default, marker=marker,
            state="discovered",
        )


REGISTRY: dict[str, type[BaseConnector]] = {}


def register(cls: type[BaseConnector]) -> type[BaseConnector]:
    REGISTRY[cls.code] = cls
    return cls


def build_connector(meta: dict) -> BaseConnector | None:
    cls = REGISTRY.get(meta["code"])
    if cls is None:
        return None
    return cls(meta)


def mark_source_status(source_code: str | None, status: str, http_status: int | None = None) -> None:
    if not source_code:
        return
    db.execute("UPDATE registry_sources SET integration_status=?, last_http_status=?, updated_at=? WHERE code=?",
               (status, http_status, iso_now(), source_code))
