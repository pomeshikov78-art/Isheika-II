#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ISHEIKA-NTR-AI / TOOL-01
Парсер «Перечня источников открытой информации» -> seed-данные реестра.

Вход:  uploads/Новый документ (4).docx  (Перечень источников открытой информации)
Выход: isheika/registry/seed/sources.json
       isheika/registry/seed/countries.json
       isheika/registry/seed/stoplist.json
       isheika/registry/seed/registry_changelog.json

Требования ТЗ, которые реализует инструмент:
  * реестр источников и реестр коннекторов — РАЗНЫЕ сущности (ТЗ-05 §21.2);
  * класс доступа A0..A4, маркер достоверности П/Р/Д, дата проверки (Прил. А §0);
  * статус интеграции CANDIDATE по умолчанию — наличие URL != умение получать данные;
  * жёсткий стоп-лист (Прил. А §11);
  * «кладбище API» — закрытые/сломанные интерфейсы 2025–2026 (Прил. А §0.3).
Никакие лимиты и квоты не выдумываются: если в источнике нет числа — null + «неизвестно».
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import zipfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKSPACE = os.path.dirname(ROOT)
UPLOAD = os.path.join(WORKSPACE, "uploads", "Новый документ (4).docx")
SEED = os.path.join(ROOT, "isheika", "registry", "seed")

# ---------------------------------------------------------------- docx -> text


def docx_lines(path: str) -> list[str]:
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    text = html.unescape(xml)
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if "chatgpt-mermaid" in line or "font-family" in line:
            continue
        out.append(line)
    return out


# ---------------------------------------------------------------- cleaning

CITE_RE = re.compile(r"\[\[?\d+\]?\]")
JUNK_RE = re.compile(r"\{\{\{.*?\}\}\}", re.S)


def clean(cell: str) -> str:
    cell = JUNK_RE.sub("", cell)
    cell = CITE_RE.sub("", cell)
    cell = cell.replace("**", "").replace("\\", "")
    cell = re.sub(r"\s+", " ", cell).strip()
    return cell.strip(" ·•-–—")


def norm_key(name: str) -> str:
    n = name.lower()
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.sub(r"[^a-zа-я0-9]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


# ---------------------------------------------------------------- classification

CATEGORIES = {
    "C01": "Научные публикации",
    "C02": "Патенты",
    "C03": "Диссертации",
    "C04": "Научные данные",
    "C05": "Университеты и лаборатории",
    "C06": "НИОКР, гранты, программы",
    "C07": "Промышленность и изделия",
    "C08": "Нормативно-техническая документация",
    "C09": "Форумы и сообщества",
    "C10": "Научно-техническая журналистика",
    "C11": "Форсайт и прогнозы",
    "C12": "Государственные данные и стратегии",
}

CAT_RULES = [
    ("C02", r"патент|изобрет|полезн\w* модел|patent|invention|utility model"),
    ("C03", r"диссерта|thesis|dissertation"),
    ("C08", r"стандарт|норматив|ISO|IEC|ITU|ETSI|3GPP|ГОСТ|MIL-STD|стандартиз"),
    ("C11", r"форсайт|прогноз|foresight|roadmap|дорожн\w* карт|Delphi|сценари"),
    ("C12", r"государственн|госпрограмм|open data|открыт\w* данн|стратеги|министерств|OECD|World Bank"),
    ("C06", r"грант|НИОКР|проект\w* финансирован|award|grant|CORDIS|UKRI|NSF|фонд"),
    ("C04", r"датасет|набор\w* данн|экспериментальн\w* (данн|результат)|dataset|репозитори\w* данн|Zenodo|Figshare"),
    ("C05", r"университет|вуз|лаборатор|институт|ROR|ORCID|организац|учрежден"),
    ("C07", r"промышлен|издели|прототип|производ|industr|hardware|отраслев"),
    ("C09", r"форум|сообществ|Stack ?Exchange|Reddit|GitHub|Habr|форумы"),
    ("C10", r"журналистик|новост|СМИ|пресс-релиз|news|Phys\.org|EurekAlert"),
    ("C01", r"публикац|стать|препринт|журнал|статьи|paper|scholar|bibli|DOI"),
]

ACCESS_RULES = [
    ("A3", r"платн|коммерческ|подписк|paid|subscription|A3"),
    ("A2", r"договор|заявк|аффилиац|институциональн|по заявке|trial|A2"),
    ("A1", r"ключ|регистрац|api[ _-]?key|token|OAuth|e-?mail|mailto|ID\.me|A1"),
    ("A4", r"только метаданн|метаданные.*платн|закрыт.*текст|A4"),
    ("A0", r"без ключа|открыт|публичн|без авторизац|бесплатн|open|A0"),
]

API_TYPE_RULES = [
    ("BigQuery", r"BigQuery"),
    ("SPARQL", r"SPARQL|wikidata\.org/sparql"),
    ("OAI-PMH", r"OAI[-‑ ]?PMH|OAI\b"),
    ("SOAP", r"SOAP"),
    ("GraphQL", r"GraphQL"),
    ("CKAN", r"CKAN"),
    ("SRU", r"\bSRU\b"),
    ("RSS", r"RSS|Atom"),
    ("REST", r"REST|API|JSON|XML"),
    ("BULK", r"bulk|дамп|снапшот|snapshot|выгрузк"),
    ("PARSE", r"парсинг|скрапинг|скрейпинг|краулинг|GUI|веб-портал|веб-поиск|поиск"),
]

URL_RE = re.compile(r"(?:https?://)?[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}(?:/[^\s`|,;)]*)?", re.I)
COUNTRY_ISO = {
    "США": "US", "Канада": "CA", "Мексика": "MX", "Бразилия": "BR", "Аргентина": "AR",
    "Колумбия": "CO", "Чили": "CL", "Перу": "PE", "Япония": "JP", "Южная Корея": "KR",
    "Ю. Корея": "KR", "Малайзия": "MY", "Австралия": "AU", "Индия": "IN", "Китай": "CN",
    "ОАЭ": "AE", "Объединённые Арабские Эмираты": "AE", "Турция": "TR", "Египет": "EG",
    "Тунис": "TN", "Алжир": "DZ", "ЮАР": "ZA", "Южно-Африканская Республика": "ZA",
    "Вьетнам": "VN", "Великобритания": "GB", "Франция": "FR", "Германия": "DE",
    "Испания": "ES", "Италия": "IT", "Португалия": "PT", "Польша": "PL", "Чехия": "CZ",
    "Болгария": "BG", "Греция": "GR", "Швеция": "SE", "Норвегия": "NO",
    "Финляндия": "FI", "Россия": "RU",
}


def classify_category(text: str, section: str) -> str:
    blob = (section + " " + text)
    for code, pattern in CAT_RULES:
        if re.search(pattern, blob, re.I):
            return code
    return "C01"


def classify_access(text: str) -> tuple[str, str]:
    m = re.search(r"\bA([0-4])\b", text)
    if m:
        return "A" + m.group(1), "явно указан класс в перечне"
    for code, pattern in ACCESS_RULES:
        if re.search(pattern, text, re.I):
            return code, "выведено из описания доступа"
    # ТЗ-02 §2: неизвестное значение не подменяется выдуманным
    return "UNKNOWN", "не указано — обязательная проверка перед включением в продуктив"


def classify_api_type(text: str) -> str:
    for code, pattern in API_TYPE_RULES:
        if re.search(pattern, text, re.I):
            return code
    return "UNKNOWN"


def extract_endpoints(text: str) -> list[str]:
    found = []
    for m in URL_RE.finditer(text):
        u = m.group(0).rstrip(".")
        if " " in u or len(u) < 6:
            continue
        if re.match(r"^\d+\.\d+$", u):
            continue
        if u.lower().startswith(("т.д", "и.т")):
            continue
        found.append(u)
    seen, out = set(), []
    for u in found:
        k = u.lower()
        if k not in seen:
            seen.add(k)
            out.append(u)
    return out[:6]


def extract_marker(cells: list[str]) -> str | None:
    for c in reversed(cells):
        cc = c.strip()
        if cc in ("П", "Р", "Д"):
            return cc
        if re.fullmatch(r"[ПРД](/[ПРД])?", cc):
            return cc[0]
    return None


PROTOCOL_NAMES = {
    "REST", "JSON", "XML", "ATOM", "RSS", "OAI-PMH", "OAI", "SPARQL", "CKAN", "SRU",
    "GRAPHQL", "SOAP", "PDF", "HTML", "CSV", "TEI", "JSON-LD", "MARC", "BULK", "API",
    "GRPC", "WEBSOCKET", "FTP", "S3", "OAI_PMH", "Z39.50",
}

NUM_RE = re.compile(r"(\d[\d\s.,]*)\s*(req/s|запрос\w*/с|req/сек|/сут|/мес|/нед|ГБ|МБ|req/ч|запросов/)", re.I)


def extract_limits(text: str) -> dict:
    """Числовые лимиты берутся ТОЛЬКО если они явно записаны в перечне."""
    out: dict = {"raw": None, "rps": None, "per_day": None, "per_month": None, "bytes_per_week": None}
    hits = []
    for m in NUM_RE.finditer(text):
        hits.append(m.group(0).strip())
    if hits:
        out["raw"] = "; ".join(hits[:4])
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:req/s|запросов/с|req/сек)", text, re.I)
    if m:
        out["rps"] = float(m.group(1).replace(",", "."))
    m = re.search(r"(\d[\d\s]{2,})\s*/\s*сут", text, re.I)
    if m:
        out["per_day"] = int(re.sub(r"\D", "", m.group(1)))
    m = re.search(r"(\d[\d\s]{2,})\s*/\s*мес", text, re.I)
    if m:
        out["per_month"] = int(re.sub(r"\D", "", m.group(1)))
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*ГБ\s*/\s*нед", text, re.I)
    if m:
        out["bytes_per_week"] = int(float(m.group(1).replace(",", ".")) * 1024**3)
    return out


# ---------------------------------------------------------------- table walker

def split_row(line: str) -> list[str]:
    parts = line.strip().strip("|").split("|")
    return [clean(p) for p in parts]


def is_sep(line: str) -> bool:
    return bool(re.fullmatch(r"\|[\s:|-]+\|?", line.strip()))


def header_index(headers: list[str], *keys: str) -> int | None:
    for i, h in enumerate(headers):
        hl = h.lower()
        if any(k in hl for k in keys):
            return i
    return None


def parse(lines: list[str]) -> tuple[list[dict], list[dict]]:
    records: dict[str, dict] = {}
    countries: dict[str, dict] = {}
    section = ""
    part = ""
    country_ctx = None
    headers: list[str] = []
    in_table = False
    verified = "2026-11-21"

    for line in lines:
        if line.startswith("#"):
            title = clean(line.lstrip("#").strip())
            if re.match(r"^ЧАСТЬ", title, re.I):
                part = title
                country_ctx = None
            else:
                section = title
                m = re.match(r"^\d+\.?\s*(.+)$", title)
                nm = m.group(1).strip() if m else title
                if nm in COUNTRY_ISO:
                    country_ctx = COUNTRY_ISO[nm]
                    if country_ctx not in countries:
                        countries[country_ctx] = {"iso2": country_ctx, "name_ru": nm, "sources": []}
                elif not re.match(r"^\d", title):
                    country_ctx = country_ctx if nm in COUNTRY_ISO else None
            in_table = False
            headers = []
            continue

        if line.startswith("|"):
            cells = split_row(line)
            if is_sep(line):
                in_table = True
                continue
            if not in_table:
                headers = cells
                continue
            if len(cells) < 2:
                continue
            # --- определение колонки имени
            i_name = header_index(headers, "источник", "ресурс", "платформа", "api", "ведомство", "организация", "поле")
            if i_name is None:
                i_name = 1 if re.fullmatch(r"№|n|#|\d+", headers[0] or "") else 0
            if i_name >= len(cells):
                continue
            name = cells[i_name]
            if not name or len(name) < 2 or name.lower() in ("источник", "api", "поле"):
                continue
            if re.fullmatch(r"[\d\-–—:. ]+", name):
                continue
            if name.upper() in PROTOCOL_NAMES:
                continue
            # пропуск служебных таблиц (описания полей, маркеров, статусов)
            if re.search(r"source_id|api_base_url|integration_status|Маркер|Класс|Поле", headers[0], re.I) and \
               re.search(r"описан|значени|смысл", " ".join(headers), re.I):
                continue

            i_ep = header_index(headers, "endpoint", "базовый адрес", "адрес", "api /", "тип api", "способ подключ", "доступ")
            i_purp = header_index(headers, "назначен", "содержан", "что даёт", "особенност", "описан", "покрытие")
            i_lim = header_index(headers, "лимит", "ограничен", "квот")
            i_geo = header_index(headers, "страна", "географ", "юрисдик")
            i_acc = header_index(headers, "доступ", "авторизац", "класс")

            blob = " | ".join(cells)
            ep_text = " ".join([cells[i] for i in (i_ep, i_lim, i_acc) if i is not None and i < len(cells)])
            endpoints = extract_endpoints(ep_text + " " + blob)
            access, access_reason = classify_access(ep_text or blob)
            marker = extract_marker(cells)
            limits = extract_limits(cells[i_lim] if i_lim is not None and i_lim < len(cells) else blob)
            api_type = classify_api_type(ep_text or blob)
            purpose = cells[i_purp] if i_purp is not None and i_purp < len(cells) else ""
            geo = cells[i_geo] if i_geo is not None and i_geo < len(cells) else ""
            iso = None
            if geo:
                for ru, code in COUNTRY_ISO.items():
                    if ru.lower() in geo.lower():
                        iso = code
                        break
                m = re.search(r"\(([A-Z]{2})\)", geo)
                if m:
                    iso = m.group(1)
            iso = iso or country_ctx
            category = classify_category(purpose + " " + name, section + " " + part)

            key = norm_key(name)
            if not key:
                continue
            rec = records.get(key)
            if rec is None:
                rec = {
                    "source_code": "",
                    "name": name,
                    "category": category,
                    "category_name": CATEGORIES[category],
                    "country_iso2": iso,
                    "scope": "national" if iso else "international",
                    "api_type": api_type,
                    "access_class": access,
                    "access_reason": access_reason,
                    "auth_type": {"A0": "none", "A1": "api_key", "A2": "contract", "A3": "subscription", "A4": "metadata_only"}.get(access, "unknown"),
                    "endpoints": endpoints,
                    "purpose": purpose,
                    "limits": limits,
                    "evidence_marker": marker or "Д",
                    "marker_reason": "указан в перечне" if marker else "не указан — принята худшая оценка «Д»",
                    "integration_status": "CANDIDATE",
                    "connector_code": None,
                    "priority": "P2",
                    "verified_at": verified if marker == "П" else None,
                    "registry_section": section,
                    "registry_part": part,
                    "response_format": "JSON" if re.search(r"JSON|REST", blob, re.I) else ("XML" if re.search(r"XML|OAI|Atom|RSS|SOAP", blob, re.I) else "UNKNOWN"),
                    "notes": [],
                }
                records[key] = rec
            else:
                if iso and not rec["country_iso2"]:
                    rec["country_iso2"] = iso
                    rec["scope"] = "national"
                for e in endpoints:
                    if e not in rec["endpoints"] and len(rec["endpoints"]) < 8:
                        rec["endpoints"].append(e)
                if purpose and len(purpose) > len(rec["purpose"]):
                    rec["purpose"] = purpose
                if marker == "П":
                    rec["evidence_marker"] = "П"
                    rec["marker_reason"] = "указан в перечне"
                    rec["verified_at"] = verified
                elif marker == "Р" and rec["evidence_marker"] == "Д":
                    rec["evidence_marker"] = "Р"
                if access in ("A3",) or (rec["access_class"] in ("A0", "A1") and access in ("A2", "A3")):
                    rec["access_class"] = access
                    rec["access_reason"] = access_reason
                if limits["raw"] and not rec["limits"]["raw"]:
                    rec["limits"] = limits
                if rec["api_type"] in ("UNKNOWN", "PARSE") and api_type not in ("UNKNOWN",):
                    rec["api_type"] = api_type
            if iso and iso in countries:
                countries[iso]["sources"].append(name)

    out = list(records.values())
    for i, r in enumerate(sorted(out, key=lambda r: (r["category"], r["name"].lower())), 1):
        r["source_code"] = f"SRC-{i:04d}"
    return out, list(countries.values())


# ---------------------------------------------------------------- fixed seed parts

COUNTRY_ORDER = [
    ("US", "США", "USPTO", "Северная Америка"), ("CA", "Канада", "CIPO", "Северная Америка"),
    ("MX", "Мексика", "IMPI", "Латинская Америка"), ("BR", "Бразилия", "INPI BR", "Латинская Америка"),
    ("AR", "Аргентина", "INPI AR", "Латинская Америка"), ("CO", "Колумбия", "SIC", "Латинская Америка"),
    ("CL", "Чили", "INAPI", "Латинская Америка"), ("PE", "Перу", "INDECOPI", "Латинская Америка"),
    ("JP", "Япония", "JPO", "Азия"), ("KR", "Южная Корея", "KIPO", "Азия"),
    ("MY", "Малайзия", "MyIPO", "Азия"), ("AU", "Австралия", "IP Australia", "Океания"),
    ("IN", "Индия", "IPO India", "Азия"), ("CN", "Китай", "CNIPA", "Азия"),
    ("AE", "ОАЭ", "MOIP", "Ближний Восток"), ("TR", "Турция", "TÜRKPATENT", "Ближний Восток"),
    ("EG", "Египет", "EGPO", "Африка"), ("TN", "Тунис", "INNORPI", "Африка"),
    ("DZ", "Алжир", "INAPI DZ", "Африка"), ("ZA", "ЮАР", "CIPC", "Африка"),
    ("VN", "Вьетнам", "NOIP", "Азия"), ("GB", "Великобритания", "IPO UK", "Европа"),
    ("FR", "Франция", "INPI FR", "Европа"), ("DE", "Германия", "DPMA", "Европа"),
    ("ES", "Испания", "OEPM", "Европа"), ("IT", "Италия", "UIBM", "Европа"),
    ("PT", "Португалия", "INPI PT", "Европа"), ("PL", "Польша", "UPRP", "Европа"),
    ("CZ", "Чехия", "ÚPV", "Европа"), ("BG", "Болгария", "BPO", "Европа"),
    ("GR", "Греция", "OBI", "Европа"), ("SE", "Швеция", "PRV", "Европа"),
    ("NO", "Норвегия", "Patentstyret", "Европа"), ("FI", "Финляндия", "PRH", "Европа"),
    ("RU", "Россия", "Роспатент", "Евразия"),
]

LANGS = {
    "US": ["en"], "CA": ["en", "fr"], "MX": ["es"], "BR": ["pt"], "AR": ["es"], "CO": ["es"],
    "CL": ["es"], "PE": ["es"], "JP": ["ja", "en"], "KR": ["ko", "en"], "MY": ["ms", "en"],
    "AU": ["en"], "IN": ["en", "hi"], "CN": ["zh", "en"], "AE": ["ar", "en"], "TR": ["tr"],
    "EG": ["ar"], "TN": ["ar", "fr"], "DZ": ["ar", "fr"], "ZA": ["en"], "VN": ["vi"],
    "GB": ["en"], "FR": ["fr"], "DE": ["de"], "ES": ["es"], "IT": ["it"], "PT": ["pt"],
    "PL": ["pl"], "CZ": ["cs"], "BG": ["bg"], "GR": ["el"], "SE": ["sv"], "NO": ["no"],
    "FI": ["fi", "sv"], "RU": ["ru"],
}

STOPLIST = [
    {"code": "STOP-01", "pattern": r"sci-?hub|libgen|зеркал\w* платн", "reason": "Обход paywall/авторизации запрещён (ТЗ БЕЗ-01)", "action": "block"},
    {"code": "STOP-02", "pattern": r"scholar\.google|researchgate|linkedin\.com|academia\.edu|(^|\.)x\.com|twitter\.com", "reason": "Автоматический сбор запрещён ToS / нет открытого API", "action": "block"},
    {"code": "STOP-03", "pattern": r"worldwide\.espacenet\.com|register\.epo\.org", "reason": "GUI Espacenet/Register: роботы запрещены EPO, только REST OPS", "action": "block_automation"},
    {"code": "STOP-04", "pattern": r"fileserver-az\.core\.ac\.uk", "reason": "Скачивание PDF CORE в обход API ведёт к блокировке ключа", "action": "block"},
    {"code": "STOP-05", "pattern": r"ГОСТ\s*РВ|ДСП|для служебного пользования|секретно", "reason": "Материалы ограниченного распространения вне контура системы", "action": "block"},
    {"code": "STOP-06", "pattern": r"контент-ферм|хищническ|predatory|seo-текст", "reason": "Фильтр ПОИСК-10: недостоверные источники", "action": "downgrade"},
]

API_GRAVEYARD = [
    {"name": "PatentsView api.patentsview.org", "closed_at": "2026-03-20", "replacement": "USPTO ODP api.uspto.gov", "note": "Старые endpoint'ы подлежат замене"},
    {"name": "USPTO PEDS / BDSS", "closed_at": "2026-03-20", "replacement": "USPTO ODP + mapping-таблицы", "note": "Выведены из строя"},
    {"name": "OpenAIRE XML Search API", "closed_at": "2026-05-31", "replacement": "OpenAIRE JSON Graph API", "note": "Остался только Graph API"},
    {"name": "Cristin (Норвегия)", "closed_at": "2025-12-15", "replacement": "NVA", "note": "API закрыт 19.08.2025"},
    {"name": "Papers with Code", "closed_at": "2025-07-28", "replacement": "Архивный снапшот Hugging Face", "note": "Живого API нет"},
    {"name": "Open Access Button / InstantILL", "closed_at": "2025-11-18", "replacement": "Unpaywall / OpenAlex / CORE", "note": "OA-поиск через альтернативы"},
]

CRITICAL_CHANGES = [
    {"id": "CH-01", "subject": "OpenAlex", "change": "Кредитная модель: бесплатный ключ — бюджет $1/сут, 30 req/s; без ключа 10 req/s и только первая страница", "since": "2026", "impact": "quota_scheduler"},
    {"id": "CH-02", "subject": "Crossref", "change": "Списочные запросы 1 req/s (public) / 3 req/s (polite pool через mailto)", "since": "2026-07-21", "impact": "rate_limit"},
    {"id": "CH-03", "subject": "EPO OPS", "change": "Бесплатный порог 4 ГБ в НЕДЕЛЮ (не в месяц), ~1 Мбит/с; тяжёлые выгрузки 19:00–07:00 GMT", "since": "2026", "impact": "weekly_byte_budget"},
    {"id": "CH-04", "subject": "USPTO ODP", "change": "Ключ: аккаунт USPTO.gov + ID.me; ключ удаляется после 90 дней неиспользования; bulk — без ключа", "since": "2026-03-20", "impact": "auth"},
    {"id": "CH-05", "subject": "KIPRIS Plus", "change": "Бесплатно до 1000 обращений/мес, далее деградация на OPS", "since": "2026", "impact": "monthly_counter"},
    {"id": "CH-06", "subject": "UKRI GtR", "change": "Новый портал и новый API (ноябрь 2026) — старые инструменты требуют обновления", "since": "2026-11", "impact": "connector_rewrite"},
    {"id": "CH-07", "subject": "Trove (AU)", "change": "Ограничение выдачи ключей и throttling открытого доступа", "since": "2025", "impact": "fallback"},
]


def parse_plain_offices(lines: list[str]) -> list[dict]:
    """Раздел 1.2 «Национальные патентные ведомства (35 стран)» дан простым текстом."""
    out: dict[str, dict] = {}
    active = False
    names = sorted(COUNTRY_ISO.keys(), key=len, reverse=True)
    for line in lines:
        if line.startswith("1.2."):
            active = True
            continue
        if active and (line.startswith("2.") or line.startswith("Важно:")):
            break
        if not active:
            continue
        hit = next((n for n in names if line.startswith(n + " ")), None)
        if not hit:
            continue
        rest = line[len(hit):].strip()
        m = re.match(r"^(.+?)\s*\(([A-Z]{2})\)\s*(.*)$", rest)
        if not m:
            continue
        office, iso, tail = m.group(1).strip(), m.group(2), m.group(3).strip()
        access, reason = classify_access(tail)
        out[norm_key(office + " " + iso)] = {
            "source_code": "", "name": f"{office} ({iso})", "category": "C02",
            "category_name": CATEGORIES["C02"], "country_iso2": iso, "scope": "national",
            "api_type": classify_api_type(tail), "access_class": access, "access_reason": reason,
            "auth_type": {"A0": "none", "A1": "api_key", "A2": "contract", "A3": "subscription"}.get(access, "unknown"),
            "endpoints": extract_endpoints(tail), "purpose": "Национальное патентное ведомство: " + tail,
            "limits": extract_limits(tail), "evidence_marker": "Д",
            "marker_reason": "раздел 1.2 перечня, маркер не указан",
            "integration_status": "CANDIDATE", "connector_code": None, "priority": "P1",
            "verified_at": None, "registry_section": "1.2. Национальные патентные ведомства (35 стран)",
            "registry_part": "Перечень источников, часть 1", "response_format": "UNKNOWN",
            "notes": ["Добавлено из текстового (не табличного) раздела перечня"],
        }
    return list(out.values())


def main() -> int:
    if not os.path.exists(UPLOAD):
        print("Не найден файл перечня:", UPLOAD, file=sys.stderr)
        return 2
    lines = docx_lines(UPLOAD)
    sources, parsed_countries = parse(lines)
    known = {norm_key(s["name"]) for s in sources}
    for rec in parse_plain_offices(lines):
        if norm_key(rec["name"]) not in known:
            sources.append(rec)
            known.add(norm_key(rec["name"]))
    for i, r in enumerate(sorted(sources, key=lambda r: (r["category"], r["name"].lower())), 1):
        r["source_code"] = f"SRC-{i:04d}"

    countries = []
    for iso, name, office, region in COUNTRY_ORDER:
        countries.append({
            "iso2": iso, "name_ru": name, "region": region,
            "patent_office": office, "languages": LANGS[iso],
            "enabled": True,
            "national_sources": [],
            "coverage": {"documents": 0, "class_P": 0, "last_success": None},
        })
    by_iso = {c["iso2"]: c for c in countries}
    for s in sources:
        iso = s.get("country_iso2")
        if iso in by_iso:
            by_iso[iso]["national_sources"].append(s["source_code"])

    os.makedirs(SEED, exist_ok=True)
    with open(os.path.join(SEED, "sources.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "GSR-1.0", "generated_from": "Перечень источников открытой информации",
                   "generated_at": str(date.today()), "categories": CATEGORIES, "items": sources},
                  f, ensure_ascii=False, indent=1)
    with open(os.path.join(SEED, "countries.json"), "w", encoding="utf-8") as f:
        json.dump({"version": "GSR-1.0", "count": len(countries), "items": countries}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(SEED, "stoplist.json"), "w", encoding="utf-8") as f:
        json.dump({"items": STOPLIST}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(SEED, "registry_changelog.json"), "w", encoding="utf-8") as f:
        json.dump({"graveyard": API_GRAVEYARD, "critical_changes": CRITICAL_CHANGES}, f, ensure_ascii=False, indent=1)

    print(f"Источников: {len(sources)}  Стран: {len(countries)}")
    from collections import Counter
    print("по категориям:", dict(Counter(s["category"] for s in sources)))
    print("по доступу:", dict(Counter(s["access_class"] for s in sources)))
    print("по маркерам:", dict(Counter(s["evidence_marker"] for s in sources)))
    print("с endpoint:", sum(1 for s in sources if s["endpoints"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
