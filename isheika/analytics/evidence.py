"""Доказательная модель (ТЗ-03 §3, ТЗ-01 §6).

Каждое утверждение (Claim) связано с Evidence: источник, URL, цитируемый
фрагмент, локатор, даты публикации и доступа, класс источника, группа
независимости, качество и статус проверки.

Правила:
  * первичный источник предпочтительнее пересказа;
  * пресс-релиз доказывает факт заявления, а не характеристику;
  * патент доказывает раскрытие/заявку/правовой статус, не работоспособность;
  * повторные публикации одного сообщения не независимы;
  * конфликтующие доказательства сохраняются, а не усредняются.
"""
from __future__ import annotations

import re
from collections import Counter

from ..contracts import iso_now, new_id
from ..registry.loader import methodology
from ..storage import db
from ..workflow import events
from ..search import normalize as norm

ORIGIN_BY_CLASS = {"primary_peer_reviewed": "PRIMARY", "primary_report": "PRIMARY",
                   "dataset": "PRIMARY", "official_register": "PRIMARY", "standard": "PRIMARY",
                   "patent": "PRIMARY", "preprint": "PRIMARY", "press_release": "PRIMARY",
                   "media": "REPRINT", "forum": "SUMMARY", "encyclopedia": "SUMMARY",
                   "unknown": "DERIVATIVE"}
DERIVED_ORIGINS = ("REPRINT", "SUMMARY", "DERIVATIVE")

CLASS_RULES = {
    "patent": ("patent", "Патент подтверждает раскрытие/заявку/правовой статус, но не работоспособность изделия"),
    "press_release": ("press_release", "Пресс-релиз подтверждает факт заявления, а не заявленную характеристику"),
    "media": ("media", "Вторичный пересказ: требуется первичный источник"),
    "forum": ("forum", "Мнение практиков: не является доказательством характеристики"),
    "preprint": ("preprint", "Не прошёл рецензирование: статус PARTIAL до подтверждения"),
    "primary_peer_reviewed": ("primary_peer_reviewed", "Первичный рецензированный источник"),
    "primary_report": ("primary_report", "Первичный технический отчёт"),
    "dataset": ("dataset", "Первичные данные эксперимента"),
    "official_register": ("official_register", "Официальный реестр"),
    "standard": ("standard", "Нормативный документ: подтверждает требования, не реализацию"),
}


def assign_independence(research_id: str) -> dict:
    """ИД-11: группировка доказательств по происхождению.

    Перепечатки и пересказы одного сообщения попадают в ОДНУ группу независимости
    и не увеличивают число независимых подтверждений. Первичный источник группы
    сохраняется, цепочка перепубликаций фиксируется связью DERIVED_FROM.
    """
    docs = [db.dec(r, "identifiers", "organizations", "authors") for r in
            db.query("SELECT * FROM research_documents WHERE research_id=?", (research_id,))]
    primaries = [d for d in docs if ORIGIN_BY_CLASS.get(d["evidence_class"], "DERIVATIVE") == "PRIMARY"]
    ref_index: dict[str, dict] = {}
    for p in primaries:
        if p.get("url"):
            ref_index[norm.normalize_url(p["url"])] = p
            ref_index[p["url"].lower().strip()] = p
        if p.get("doi"):
            ref_index[str(p["doi"]).lower().strip()] = p
    groups: dict[str, dict] = {}
    reprints = 0
    for d in docs:
        ids = d.get("identifiers") or {}
        origin = ORIGIN_BY_CLASS.get(d["evidence_class"], "DERIVATIVE")
        root = None
        explicit = ids.get("derived_from") or ids.get("reprint_of") or ids.get("primary_source")
        if explicit:
            ref = str(explicit).lower().strip()
            root = ref_index.get(norm.normalize_url(str(explicit))) or ref_index.get(ref)
            key = (root.get("independence_group") or ("doc:" + root["id"])) if root else "src:" + ref
            origin = "REPRINT" if d["evidence_class"] == "media" else "DERIVATIVE"
        else:
            key = d.get("independence_group") or ("doc:" + d["id"])
            if origin in DERIVED_ORIGINS:
                # ищем первичный материал того же сообщения
                for p in primaries:
                    if p["id"] == d["id"]:
                        continue
                    same_title = norm.simhash(p["title"] or "")
                    if norm.hamming(same_title, d.get("simhash") or "") <= 8:
                        root = p
                        break
                if root is not None:
                    key = root.get("independence_group") or ("doc:" + root["id"])
                    reprints += 1
        g = groups.get(key)
        if g is None:
            g = {"group_key": key, "primary_document_id": (root or d)["id"],
                 "primary_source_ref": (root or d).get("url"), "members": 0,
                 "origin_class": "PRIMARY" if (root or d)["id"] == d["id"] else origin,
                 "first_published_at": (root or d).get("published_at"),
                 "basis": "явная ссылка на первоисточник" if explicit else
                          ("совпадение отпечатка с первичным материалом" if root else "организация/домен")}
            groups[key] = g
        g["members"] += 1
        if (root or d)["id"] == d["id"] and origin == "PRIMARY":
            g["primary_document_id"] = d["id"]
            g["origin_class"] = "PRIMARY"
        db.update("content_documents", "id", d["id"], {"origin_class": origin})
        d["_origin"] = origin
        d["_group_key"] = key

    out = {}
    for key, g in groups.items():
        row = db.one("SELECT id FROM evidence_independence_groups WHERE research_id=? AND group_key=?",
                     (research_id, key))
        gid = row["id"] if row else new_id("ind-")
        db.upsert("evidence_independence_groups", {
            "id": gid, "research_id": research_id, "group_key": key,
            "primary_source_ref": g["primary_source_ref"], "primary_document_id": g["primary_document_id"],
            "origin_class": g["origin_class"], "members": g["members"],
            "first_published_at": g["first_published_at"], "basis": g["basis"],
            "created_at": iso_now()}, key=("research_id", "group_key"))
        out[key] = gid
    # проставляем ссылки в документах и доказательствах
    for d in docs:
        gid = out[d["_group_key"]]
        db.execute("UPDATE evidence_items SET independence_group_id=?, origin_class=? WHERE document_id=? AND research_id=?",
                   (gid, d["_origin"], d["id"], research_id))
    return {"groups": len(out), "documents": len(docs), "reprints": reprints,
            "independent_confirmations": sum(1 for g in groups.values() if g["origin_class"] == "PRIMARY")}


def group_index(research_id: str) -> dict[str, str]:
    return {r["group_key"]: r["id"] for r in
            db.query("SELECT id, group_key FROM evidence_independence_groups WHERE research_id=?", (research_id,))}


def independence_groups(research_id: str) -> list[dict]:
    rows = db.query("SELECT * FROM evidence_independence_groups WHERE research_id=? ORDER BY members DESC", (research_id,))
    for r in rows:
        r["documents"] = db.query("""SELECT d.id, d.title, d.evidence_class, d.origin_class, d.published_at
                                     FROM research_documents d WHERE d.research_id=? AND d.independence_group=?""",
                                  (research_id, r["group_key"]))
    return rows


def quality_of(evidence_class: str, marker: str, *, has_quote: bool,
               has_locator: bool, has_date: bool, independent: bool) -> float:
    m = methodology()
    base = m["evidence_class_quality"].get(evidence_class, 0.15)
    factor = {"П": 1.0, "Р": 0.9, "Д": 0.75}.get(marker, 0.75)
    completeness = 0.6 + 0.15 * has_quote + 0.15 * has_locator + 0.1 * has_date
    ind = 1.0 if independent else 0.85
    return round(min(1.0, base * factor * completeness * ind), 4)


def _quote_for(doc: dict, claim_text: str) -> tuple[str, str]:
    """Короткий подтверждающий фрагмент + локатор (раздел/абзац)."""
    abstract = doc.get("abstract") or ""
    words = [w for w in re.findall(r"[а-яa-zё]{4,}", claim_text.lower())][:12]
    sentences = re.split(r"(?<=[.!?])\s+", abstract)
    best, best_score = "", 0
    for i, s in enumerate(sentences):
        score = sum(1 for w in words if w in s.lower())
        if score > best_score:
            best, best_score = s, score
    if not best and sentences:
        best = sentences[0]
    locator = f"abstract, предложение {sentences.index(best)+1}" if best in sentences else "title"
    return (best or doc.get("title") or "")[:600], locator


def build_evidence(research_id: str, *, progress_cb=None) -> dict:
    """Связывание утверждений с документами и формирование Evidence."""
    claims = db.query("SELECT * FROM knowledge_claims WHERE research_id=?", (research_id,))
    docs = {}
    for r in db.query("SELECT * FROM research_documents WHERE research_id=?", (research_id,)):
        docs[r["id"]] = db.dec(r, "authors", "organizations", "identifiers")
    links = db.query("SELECT * FROM knowledge_links WHERE research_id=? AND link_type='cited'", (research_id,))
    by_agent: dict[str, list[str]] = {}
    for l in links:
        by_agent.setdefault(l["from_id"], []).append(l["to_id"])

    # если ИИ недоступен — утверждения строятся напрямую из документов
    if not claims:
        _claims_from_documents(research_id, docs)
        claims = db.query("SELECT * FROM knowledge_claims WHERE research_id=?", (research_id,))

    indep = assign_independence(research_id)
    gindex = group_index(research_id)
    groups = Counter(d.get("independence_group") for d in docs.values())
    created = 0
    statuses: Counter = Counter()
    for i, c in enumerate(claims, 1):
        doc_ids = _doc_ids_for_claim(c, docs, by_agent)
        if not doc_ids:
            db.update("knowledge_claims", "id", c["id"], {"status": "UNVERIFIED"})
            statuses["UNVERIFIED"] += 1
            continue
        best_status, qualities, indep_groups = "UNVERIFIED", [], set()
        for did in doc_ids[:6]:
            d = docs.get(did)
            if not d:
                continue
            eclass, note = CLASS_RULES.get(d["evidence_class"], ("unknown", "Класс источника не определён"))
            quote, locator = _quote_for(d, c["claim_text"])
            origin = d.get("origin_class") or ORIGIN_BY_CLASS.get(d["evidence_class"], "DERIVATIVE")
            # ИД-11: перепечатка не является независимым подтверждением
            independent = origin in ("PRIMARY", "INDEPENDENT_CONFIRMATION")
            q = quality_of(eclass, d["marker"], has_quote=bool(quote), has_locator=bool(locator),
                           has_date=bool(d["published_at"]), independent=independent)
            simulated = bool((d.get("identifiers") or {}).get("simulated"))
            if simulated:
                status = "UNVERIFIED"
                note += "; ИМИТАЦИОННЫЕ ДАННЫЕ DEV-профиля — не доказательство"
            elif c["claim_type"] == "FACT" and eclass in ("primary_peer_reviewed", "primary_report", "dataset", "official_register", "standard"):
                status = "SUPPORTED"
            elif eclass in ("patent", "preprint", "press_release", "media", "forum"):
                status = "PARTIAL"
            else:
                status = "PARTIAL"
            db.insert("evidence_items", {
                "id": new_id("evd-"), "claim_id": c["id"], "document_id": did,
                "research_id": research_id, "source_code": d["source_code"], "url": d["url"],
                "locator": locator, "quote": quote, "published_at": d["published_at"],
                "accessed_at": d["accessed_at"], "evidence_class": eclass,
                "independence_group": d["independence_group"],
                "independence_group_id": gindex.get(d.get("independence_group")),
                "origin_class": origin, "primary_source_ref": d.get("url"),
                "first_published_at": d.get("published_at"),
                "verification_status": status, "quality": q, "status": status,
                "marker": d["marker"], "archive_url": None, "created_at": iso_now()})
            created += 1
            qualities.append(q)
            if independent:
                indep_groups.add(d["independence_group"])
            if status == "SUPPORTED":
                best_status = "SUPPORTED"
            elif best_status != "SUPPORTED" and status == "PARTIAL":
                best_status = "PARTIAL"
        final = best_status
        if c["claim_type"] in ("HYPOTHESIS", "FORECAST"):
            final = "UNVERIFIED"      # гипотеза/прогноз не «подтверждается» источником
        db.update("knowledge_claims", "id", c["id"], {
            "status": final,
            "confidence": round(sum(qualities) / len(qualities), 4) if qualities else None})
        statuses[final] += 1
        if progress_cb and i % 20 == 0:
            progress_cb(i, len(claims), f"Обработано утверждений: {i}/{len(claims)}")

    _detect_contradictions(research_id)
    events.emit("evidence.added", research_id=research_id,
                payload={"evidence_items": created, "claims": len(claims), "statuses": dict(statuses)})
    return {"claims": len(claims), "evidence_items": created, "statuses": dict(statuses),
            "independence_groups": indep["groups"], "reprints_detected": indep["reprints"],
            "note": "Повторные публикации одного сообщения учтены как одна группа независимости (ИД-11)"}


def _doc_ids_for_claim(claim: dict, docs: dict, by_agent: dict) -> list[str]:
    explicit = db.query("""SELECT to_id FROM knowledge_links
                           WHERE research_id=? AND from_kind='claim' AND from_id=?""",
                        (claim["research_id"], claim["id"]))
    if explicit:
        return [r["to_id"] for r in explicit]
    agent = claim.get("section")
    words = [w for w in re.findall(r"[а-яa-zё]{5,}", claim["claim_text"].lower())][:10]
    scored = []
    for did, d in docs.items():
        if d.get("relevance_class") not in ("DIRECT", "ADJACENT"):
            continue
        blob = ((d["title"] or "") + " " + (d["abstract"] or "")).lower()
        score = sum(1 for w in words if w in blob)
        if agent and agent in ("A03",) and d["doc_type"] != "patent":
            score -= 3
        if agent in ("A02",) and d["evidence_class"] not in ("primary_peer_reviewed", "preprint", "primary_report", "dataset"):
            score -= 2
        if score > 0:
            scored.append((score, did))
    scored.sort(reverse=True)
    return [d for _, d in scored[:4]]


def _claims_from_documents(research_id: str, docs: dict) -> None:
    """Базовый слой утверждений без ИИ: только то, что есть в источниках."""
    for did, d in docs.items():
        if d.get("relevance_class") not in ("DIRECT", "ADJACENT"):
            continue
        if d["doc_type"] == "patent":
            text = f'Раскрытие по патентной публикации: {d["title"]}'
            ctype = "FACT"
        elif d["evidence_class"] in ("press_release", "media", "forum"):
            text = f'Заявление/сообщение: {d["title"]}'
            ctype = "ANALYSIS"
        else:
            text = f'{d["title"]}'
            ctype = "FACT" if d["evidence_class"] in ("primary_peer_reviewed", "primary_report", "dataset", "official_register") else "ANALYSIS"
        cid = new_id("clm-")
        db.insert("knowledge_claims", {"id": cid, "research_id": research_id, "technology_id": None,
                                       "claim_text": text[:2000], "claim_type": ctype,
                                       "section": "DOC", "status": "UNVERIFIED", "confidence": None,
                                       "produced_by": "document_layer", "created_at": iso_now()})
        db.insert("knowledge_links", {"id": new_id("lnk-"), "research_id": research_id,
                                      "from_kind": "claim", "from_id": cid, "to_kind": "document",
                                      "to_id": did, "link_type": "cited", "confirmed": 1,
                                      "created_at": iso_now()})


def _detect_contradictions(research_id: str) -> None:
    """Противоречия сохраняются: противоположные утверждения об одном объекте."""
    rows = db.query("""SELECT c.id, c.claim_text, c.status, e.document_id, e.evidence_class
                       FROM knowledge_claims c JOIN evidence_items e ON e.claim_id=c.id
                       WHERE c.research_id=?""", (research_id,))
    neg = re.compile(r"\b(не подтвержд|не достигнут|отрицательн|failed|неудач|опроверг|not reproducible|не воспроизвод)\w*", re.I)
    positives = [r for r in rows if not neg.search(r["claim_text"])]
    negatives = [r for r in rows if neg.search(r["claim_text"])]
    for n in negatives:
        for p in positives[:50]:
            kw = set(re.findall(r"[а-яa-zё]{6,}", n["claim_text"].lower())) & \
                 set(re.findall(r"[а-яa-zё]{6,}", p["claim_text"].lower()))
            if len(kw) >= 3:
                db.update("knowledge_claims", "id", n["id"], {"status": "CONTRADICTED"})
                db.execute("UPDATE evidence_items SET contradiction_of=? WHERE claim_id=?", (p["id"], n["id"]))
                break


def evidence_for(research_id: str, claim_id: str | None = None) -> list[dict]:
    if claim_id:
        return db.query("SELECT * FROM evidence_items WHERE claim_id=? ORDER BY quality DESC", (claim_id,))
    return db.query("SELECT * FROM evidence_items WHERE research_id=? ORDER BY quality DESC LIMIT 500", (research_id,))


def summary(research_id: str) -> dict:
    rows = db.query("SELECT status, evidence_class, COUNT(*) AS n FROM evidence_items WHERE research_id=? GROUP BY status, evidence_class",
                    (research_id,))
    by_status, by_class = Counter(), Counter()
    for r in rows:
        by_status[r["status"]] += r["n"]
        by_class[r["evidence_class"]] += r["n"]
    indep = db.query("""SELECT COUNT(DISTINCT ifnull(independence_group_id, independence_group)) AS n
                        FROM evidence_items WHERE research_id=?""", (research_id,))
    origins = db.query("SELECT origin_class, COUNT(*) AS n FROM evidence_items WHERE research_id=? GROUP BY origin_class",
                       (research_id,))
    return {"by_status": dict(by_status), "by_class": dict(by_class),
            "by_origin": {r["origin_class"]: r["n"] for r in origins},
            "independence_groups": indep[0]["n"] if indep else 0,
            "total": sum(by_status.values())}
