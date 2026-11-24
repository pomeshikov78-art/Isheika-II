"""Нормализация и дедупликация документов (ТЗ-01 M10, ТЗ-05 §4.5).

Дедупликация: DOI -> нормализованный URL -> content hash -> simhash заголовка.
Повторные публикации одного сообщения НЕ считаются независимыми
подтверждениями: им присваивается одна группа независимости.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlparse, urlunparse

from ..contracts import Document

TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_cid|mc_eid|ref_src|ref_url)", re.I)

LANG_HINTS = [
    ("ru", r"[а-яё]{3}"), ("zh", r"[\u4e00-\u9fff]"), ("ja", r"[\u3040-\u30ff]"),
    ("ko", r"[\uac00-\ud7af]"), ("ar", r"[\u0600-\u06ff]"), ("el", r"[\u0370-\u03ff]"),
]

EVIDENCE_BY_TYPE = {
    "patent": "patent", "patent-application": "patent",
    "standard": "standard", "report": "primary_report",
    "dataset": "dataset", "software": "dataset",
    "preprint": "preprint", "posted-content": "preprint",
    "press_release": "press_release", "news": "media", "forum": "forum",
    "organization": "official_register", "thesis": "primary_report",
    "article": "primary_peer_reviewed", "journal-article": "primary_peer_reviewed",
    "proceedings-article": "primary_peer_reviewed",
}


def normalize_url(url: str) -> str:
    try:
        p = urlparse((url or "").strip())
        q = "&".join(kv for kv in (p.query or "").split("&") if kv and not TRACKING.match(kv))
        host = (p.netloc or "").lower().replace("www.", "")
        path = re.sub(r"/+$", "", p.path or "")
        return urlunparse(("https", host, path, "", q, ""))
    except Exception:
        return url or ""


def detect_language(text: str) -> str | None:
    t = (text or "")[:4000]
    for code, pat in LANG_HINTS:
        if re.search(pat, t, re.I):
            return code
    return "en" if re.search(r"[a-zA-Z]{3}", t) else None


def content_hash(doc: Document) -> str:
    base = re.sub(r"\W+", "", (doc.title or "").lower())[:200]
    year = (doc.published_at or "")[:4]
    return hashlib.sha256(f"{base}|{year}".encode()).hexdigest()


def simhash(text: str, bits: int = 64) -> str:
    tokens = re.findall(r"\w{3,}", (text or "").lower())
    if not tokens:
        return "0" * 16
    v = [0] * bits
    for t in tokens:
        h = int(hashlib.md5(t.encode()).hexdigest(), 16)
        for i in range(bits):
            v[i] += 1 if (h >> i) & 1 else -1
    out = 0
    for i in range(bits):
        if v[i] > 0:
            out |= 1 << i
    return f"{out:016x}"


def hamming(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count("1")
    except Exception:
        return 64


def independence_group(doc: Document) -> str:
    """Группа независимости: организация-первоисточник или домен издания."""
    if doc.organizations:
        org = re.sub(r"\W+", "", doc.organizations[0].lower())[:40]
        if org:
            return "org:" + org
    host = urlparse(doc.url or "").netloc.lower().replace("www.", "")
    return "dom:" + host


def normalize(doc: Document) -> Document:
    doc.title = unicodedata.normalize("NFKC", doc.title or "").strip()
    doc.url = doc.url or ""
    doc.abstract = re.sub(r"\s+", " ", doc.abstract or "").strip()
    if not doc.language:
        doc.language = detect_language(doc.title + " " + doc.abstract)
    if not doc.evidence_class or doc.evidence_class == "unknown":
        doc.evidence_class = EVIDENCE_BY_TYPE.get(doc.doc_type, "unknown")
    doc.content_hash = content_hash(doc)
    doc.simhash = simhash(doc.title + " " + doc.abstract[:400])
    doc.independence_group = independence_group(doc)
    doc.state = "normalized"
    return doc


class Deduplicator:
    """Инкрементальная дедупликация в рамках исследования."""

    def __init__(self) -> None:
        self.by_doi: dict[str, str] = {}
        self.by_url: dict[str, str] = {}
        self.by_hash: dict[str, str] = {}
        self.simhashes: list[tuple[str, str]] = []

    def check(self, doc: Document) -> tuple[bool, str | None, str]:
        doi = (doc.doi or "").lower().strip()
        if doi and doi in self.by_doi:
            return True, self.by_doi[doi], "doi"
        url = normalize_url(doc.url)
        if url and url in self.by_url:
            return True, self.by_url[url], "url"
        if doc.content_hash and doc.content_hash in self.by_hash:
            return True, self.by_hash[doc.content_hash], "content_hash"
        for sh, did in self.simhashes:
            if hamming(sh, doc.simhash or "") <= 3:
                return True, did, "simhash"
        if doi:
            self.by_doi[doi] = doc.document_id
        if url:
            self.by_url[url] = doc.document_id
        if doc.content_hash:
            self.by_hash[doc.content_hash] = doc.document_id
        self.simhashes.append((doc.simhash or "", doc.document_id))
        return False, None, ""
