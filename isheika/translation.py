"""Технический перевод найденной научно-технической информации на русский язык.

Задача пользователя (ред. 1.5.0): найденные материалы должны быть доступны
аналитику по-русски. Иностранные заголовки и аннотации переводятся с сохранением
чисел, единиц, формул, обозначений и идентификаторов; терминология берётся из
словаря `isheika/data/glossary_ru.json`.

Два режима — и они честно различаются в данных, интерфейсе и отчёте:

* `ai_technical` — перевод моделью ИИ через маршрутизацию Free-First (если
  провайдер доступен и разрешён политикой). Машинный перевод, требует вычитки.
* `terminology` — детерминированный терминологический перевод без сети: шаблоны
  научных конструкций + словарь терминов. Это **черновик для понимания сути**,
  а не литературный перевод: непереведённые слова остаются в оригинале, доля
  переведённого считается и показывается (`coverage`).

Русские материалы не переводятся (`original`). Проверка «перевод выдан за
оригинал» исключена: режим и признак вычитки хранятся рядом с текстом.
"""
from __future__ import annotations

import json
import os
import re
import threading

from . import journal
from .config import SETTINGS
from .contracts import iso_now, new_id
from .storage import db

GLOSSARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "glossary_ru.json")
_LOCK = threading.Lock()
_GLOSSARY: dict | None = None

# То, что переводить нельзя: адреса, DOI, числа с единицами, обозначения.
_PROTECT = re.compile("(" + "|".join([
    r"https?://\S+",
    r"doi:\s*\S+",
    r"10\.\d{4,9}/\S+",
    r"[\w.+-]+@[\w.-]+",
    (r"\b\d+(?:[.,]\d+)?(?:\s*[×x]\s*\d+(?:[.,]\d+)?)*\s*"
     r"(?:GHz|MHz|kHz|THz|Hz|dBm|dBi|dB|km|cm|mm|µm|nm|ms|µs|ns|s|mW|kW|W|mV|V|mA|A|K|"
     r"Gbps|Mbps|kbps|bps|GB|MB|%|°)?"),
    r"\b[1-6]G\b",
    r"\b[A-Z][A-Z0-9-]{1,9}\b",
]) + ")")
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-ZА-Я0-9(])")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_CYR = re.compile(r"[А-Яа-яЁё]")


def glossary() -> dict:
    """Словарь технического перевода (кэшируется, версия фиксируется в записи)."""
    global _GLOSSARY
    with _LOCK:
        if _GLOSSARY is None:
            with open(GLOSSARY_PATH, encoding="utf-8") as f:
                g = json.load(f)
            g["_phrases_sorted"] = sorted(g["phrases"].items(), key=lambda kv: -len(kv[0]))
            g["_patterns"] = [(re.compile(p, re.I), t) for p, t in g["patterns"]]
            # русские слова, которые ведут себя как прилагательные: их нужно
            # пропускать при поиске существительного для согласования
            like = set()
            for en in g.get("adjective_words", []):
                ru = g["words"].get(en)
                if ru:
                    like.add(ru.lower())
            for entry in g.get("adjectives", {}).values():
                like.update(v.lower() for v in entry.values())
            for ru in g["phrases"].values():        # «антенная решётка», «базовые станции»
                first = ru.split(" ")[0].lower()
                if len(ru.split()) > 1 and first.endswith(_ADJ_ENDINGS):
                    like.add(first)
            g["_adj_like"] = like
            _GLOSSARY = g
        return _GLOSSARY


def version() -> str:
    return glossary().get("version", "G-0.0.0")


def detect_language(text: str, declared: str | None = None) -> str:
    """Язык материала: заявленный коннектором либо по доле кириллицы."""
    if declared and declared not in ("unknown", "und", ""):
        return declared[:2].lower()
    if not text:
        return "unknown"
    letters = sum(1 for c in text if c.isalpha())
    if not letters:
        return "unknown"
    return "ru" if len(_CYR.findall(text)) / letters > 0.3 else "en"


def _protect(text: str) -> tuple[str, list[str]]:
    kept: list[str] = []

    def sub(m):
        kept.append(m.group(0))
        return f"\x00{len(kept) - 1}\x00"

    return _PROTECT.sub(sub, text), kept


def _restore(text: str, kept: list[str]) -> str:
    """Возврат защищённых фрагментов: числа сохраняются, единицы переводятся."""
    g = glossary()
    for i, raw in enumerate(kept):
        token = raw.strip()
        if token in g["units"]:
            token = g["units"][token]
        elif token in g["abbrev"]:
            token = g["abbrev"][token]
        else:
            m = re.match(r"^([\d.,]+(?:\s*[×x]\s*[\d.,]+)*)\s*([A-Za-zµ%°]+)$", token)
            if m and m.group(2) in g["units"]:
                token = f"{m.group(1)} {g['units'][m.group(2)]}"
        text = text.replace(f"\x00{i}\x00", token)
    return text


def _word_ru(word: str) -> str | None:
    """Словарная форма слова с простой морфологией (множественное число, -ing/-ed)."""
    g = glossary()
    w = word.lower()
    if w in g.get("adjectives", {}):
        return g["adjectives"][w]["m"]
    for table in ("words", "function"):
        if w in g[table]:
            return g[table][w]
    for suffix, repl in (("ies", "y"), ("es", ""), ("s", ""), ("ing", ""), ("ing", "e"),
                         ("ed", ""), ("ed", "e"), ("ly", "")):
        if w.endswith(suffix) and len(w) > len(suffix) + 2:
            base = w[:-len(suffix)] + repl
            if base in g["words"]:
                return g["words"][base]
    return None



_ADJ_ENDINGS = ("ый", "ий", "ой", "ая", "яя", "ое", "ее", "ые")


def _adj_forms(ru: str) -> dict:
    """Формы прилагательного по мужской форме: новый → новая/новое/новые."""
    if ru.endswith(("ый", "ой")):
        stem = ru[:-2]
        return {"m": ru, "f": stem + "ая", "n": stem + "ое", "pl": stem + "ые"}
    if ru.endswith("ий"):
        stem = ru[:-2]
        soft = stem.endswith(("н", "ж", "ш", "ч", "щ"))
        return {"m": ru, "f": stem + ("яя" if soft else "ая"),
                "n": stem + ("ее" if soft else "ое"), "pl": stem + ("ие" if soft else "ие")}
    return {"m": ru, "f": ru, "n": ru, "pl": ru}


def _agree(text: str) -> str:
    """Согласование прилагательных с ближайшим существительным (черновой перевод).

    Полный морфологический анализ вне объёма детерминированного контура: род и
    число определяются по окончанию следующего за прилагательным русского слова.
    """
    g = glossary()
    forms: dict[str, dict] = {}
    for table in ("adjectives", "short_participles"):
        for entry in g.get(table, {}).values():
            for form in entry.values():
                forms[form.lower()] = entry
    for like in g.get("_adj_like", ()):
        forms.setdefault(like, _adj_forms(like))
    words = text.split(" ")
    for i, w in enumerate(words):
        key = w.lower().strip(".,;:()")
        entry = forms.get(key)
        if not entry:
            continue
        gender = "m"
        soft_f = set(g.get("feminine_soft", []))
        for nxt in words[i + 1:i + 4]:
            cand = nxt.lower().strip(".,;:()")
            if not cand or not _CYR.search(cand):
                continue
            if cand in forms or cand in g.get("_adj_like", ()):
                continue                          # следующее слово — прилагательное
            if cand.endswith("ость") or cand in soft_f:
                gender = "f"
            elif cand.endswith(("а", "я")):
                gender = "f"
            elif cand.endswith(("о", "е")):
                gender = "n"
            elif cand.endswith(("и", "ы")):
                gender = "pl"
            break
        replacement = entry[gender]
        if w[:1].isupper():
            replacement = replacement[0].upper() + replacement[1:]
        words[i] = w.replace(w.strip(".,;:()"), replacement)
    return " ".join(words)


def _translate_sentence(sentence: str) -> tuple[str, int, int, list[str]]:
    g = glossary()
    body, kept = _protect(sentence)
    for pattern, template in g["_patterns"]:
        m = pattern.match(body.strip())
        if m:
            parts, ok_n, total_n, unk = {}, 0, 0, []
            for i in range(1, (m.lastindex or 0) + 1):
                tr, ok, total, unknown = _translate_words(m.group(i) or "")
                parts[str(i)] = tr
                ok_n += ok
                total_n += total
                unk += [u for u in unknown if u not in unk]
            filled = re.sub(r"\{(\d+)\}", lambda mm: parts.get(mm.group(1), ""), template)
            return _restore(_agree(filled), kept), ok_n, total_n, unk
    tr, ok, total, unknown = _translate_words(body)
    return _restore(tr, kept), ok, total, unknown


def _translate_words(text: str) -> tuple[str, int, int, list[str]]:
    """Терминологический проход: сначала фразы, затем слова."""
    g = glossary()
    out = text
    for phrase, ru in g["_phrases_sorted"]:
        out = re.sub(r"\b" + re.escape(phrase) + r"(?:e?s)?\b", ru, out, flags=re.I)
    translated = total = 0
    unknown: list[str] = []

    def sub(m):
        nonlocal translated, total
        word = m.group(0)
        if _CYR.search(word) or len(word) == 1:
            return word                     # одиночная буква — обозначение, не слово
        total += 1
        ru = _word_ru(word)
        if ru is None:
            if word.lower() not in unknown:
                unknown.append(word.lower())
            return word
        translated += 1
        if word[0].isupper() and ru and ru[0].isalpha():
            ru = ru[0].upper() + ru[1:]
        return ru

    out = _WORD.sub(sub, out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:)])", r"\1", out)
    out = re.sub(r"([(])\s+", r"\1", out)
    return _agree(out.strip()), translated, total, unknown


def translate_text(text: str, *, lang_from: str | None = None) -> dict:
    """Перевод фрагмента на русский. Числа, единицы и обозначения сохраняются."""
    text = (text or "").strip()
    if not text:
        return {"text": "", "coverage": 1.0, "untranslated": [], "mode": "original", "lang_from": "ru"}
    lang = detect_language(text, lang_from)
    if lang == "ru":
        return {"text": text, "coverage": 1.0, "untranslated": [], "mode": "original", "lang_from": "ru"}
    parts, ok, total, unknown = [], 0, 0, []
    for sentence in _SENT_SPLIT.split(text):
        tr, o, t, unk = _translate_sentence(sentence)
        parts.append(tr)
        ok += o
        total += t
        for u in unk:
            if u not in unknown:
                unknown.append(u)
    parts = [(p[0].upper() + p[1:]) if p and p[0].isalpha() else p for p in parts]
    result = " ".join(p for p in parts if p)
    result = re.sub(r"\s{2,}", " ", result).strip()
    coverage = round(ok / total, 3) if total else 1.0
    return {"text": result, "coverage": coverage, "untranslated": unknown[:40],
            "mode": "terminology", "lang_from": lang}


# ------------------------------------------------------------------ маршрут ИИ

def ai_route() -> dict | None:
    """Доступный маршрут ИИ для перевода. Имитационный провайдер не годится:
    он не переводит, а придумывает текст — подменять перевод им нельзя."""
    if not SETTINGS.network_enabled:
        return None
    try:
        from .ai import orchestrator as O
        route = O.select_route("technical_translation", "public")
    except Exception:
        return None
    entry = route.get("entry") or {}
    provider = entry.get("provider") or {}
    if provider.get("id") == "simulation" or provider.get("family") == "simulation":
        return None
    return route


def _ai_translate(texts: list[str], route: dict) -> list[str] | None:
    """Технический перевод моделью ИИ. Возвращает None при любом отказе."""
    from .ai import adapters as AD
    from .contracts import AIRequest
    entry = route["entry"]
    provider, model = entry["provider"], entry["model"]
    try:
        adapter = AD.build_adapter(provider)
    except Exception:                                         # noqa: BLE001
        return None
    g = glossary()
    hint = "; ".join(f"{k} → {v}" for k, v in list(g["phrases"].items())[:25])
    prompt = ("Выполни технический перевод на русский язык приведённых фрагментов "
              "научно-технических материалов. Сохрани числа, единицы измерения, формулы, "
              "обозначения, имена собственные и идентификаторы без изменений. "
              "Используй принятую русскую терминологию, например: " + hint + ". "
              "Верни только переводы, по одному фрагменту на строку, без пояснений.\n\n"
              + "\n".join(f"[{i + 1}] {t}" for i, t in enumerate(texts)))
    req = AIRequest(request_id=new_id("air-"), task_id=new_id("ait-"), agent_id="TRANSLATION",
                    provider_id=provider["id"], model_id=model["model_id"], prompt=prompt,
                    timeout_s=SETTINGS.http_timeout * 3, privacy_class="public",
                    budget_policy={"allow_paid": SETTINGS.allow_paid_ai, "max_cost_usd": 0.0})
    try:
        resp = adapter.complete(req, model["model_id"])
    except Exception as exc:                                  # noqa: BLE001
        journal.record(level="warn", kind="ai", action="translation.ai_failed",
                       message=f"Перевод моделью ИИ не выполнен: {exc}"[:300],
                       error_code="E_PROVIDER", source="server")
        return None
    lines = [re.sub(r"^\[\d+\]\s*", "", ln).strip()
             for ln in (resp.text or "").splitlines() if ln.strip()]
    return lines if len(lines) == len(texts) else None


# ------------------------------------------------------------------ документы

def _source_hash(title: str, abstract: str) -> str:
    import hashlib
    return hashlib.sha256(((title or "") + "\x1f" + (abstract or "")).encode("utf-8")).hexdigest()[:16]


def for_document(document_id: str) -> dict | None:
    row = db.one("SELECT * FROM document_translations WHERE document_id=? AND lang_to='ru'", (document_id,))
    return db.dec(row, "untranslated") if row else None


def translate_document(doc: dict, *, research_id: str | None = None, force: bool = False,
                       use_ai: bool = True) -> dict | None:
    """Переводит заголовок и аннотацию документа, сохраняет результат."""
    did = doc.get("id") or doc.get("document_id")
    if not did:
        return None
    title, abstract = doc.get("title") or "", doc.get("abstract") or ""
    # Язык определяется по каждому полю отдельно: коннекторы нередко заявляют
    # «ru» для материала с английским заголовком и русской аннотацией (прогон
    # 1.5.0: «Applications of atmospheric optical communication equipment»).
    # Заявленный язык — только подсказка, письменность важнее.
    lang_t = detect_language(title) if title.strip() else (doc.get("language") or "unknown")
    lang_a = detect_language(abstract) if abstract.strip() else lang_t
    lang = "ru" if lang_t == "ru" and lang_a == "ru" else (lang_t if lang_t != "ru" else lang_a)
    existing = for_document(did)
    src_hash = _source_hash(title, abstract)
    if existing and not force and existing["source_hash"] == src_hash:
        return existing
    if lang == "ru":
        row = {"title_ru": title, "abstract_ru": abstract, "mode": "original",
               "coverage": 1.0, "untranslated": [], "lang_from": "ru",
               "provider": None, "model": None, "review_required": 0}
    else:
        route = ai_route() if use_ai else None
        ai_texts = _ai_translate([title, abstract], route) if route else None
        if ai_texts:
            row = {"title_ru": ai_texts[0], "abstract_ru": ai_texts[1], "mode": "ai_technical",
                   "coverage": 1.0, "untranslated": [], "lang_from": lang,
                   "provider": route["entry"]["provider"]["id"],
                   "model": route["entry"]["model"]["model_id"], "review_required": 1}
        else:
            t1 = translate_text(title, lang_from=lang_t)
            t2 = translate_text(abstract, lang_from=lang_a)
            unknown = list(dict.fromkeys(t1["untranslated"] + t2["untranslated"]))[:40]
            total_len = max(1, len(title) + len(abstract))
            coverage = round((t1["coverage"] * len(title) + t2["coverage"] * len(abstract)) / total_len, 3)
            row = {"title_ru": t1["text"], "abstract_ru": t2["text"], "mode": "terminology",
                   "coverage": coverage, "untranslated": unknown, "lang_from": lang,
                   "provider": None, "model": None, "review_required": 1}
    now = iso_now()
    payload = {"document_id": did, "research_id": research_id, "lang_to": "ru",
               "glossary_version": version(), "source_hash": src_hash,
               "updated_at": now, **row}
    if existing:
        db.update("document_translations", "id", existing["id"], payload)
        out = {**existing, **payload}
    else:
        payload = {"id": new_id("trn-"), "created_at": now, **payload}
        db.insert("document_translations", payload)
        out = payload
    out["untranslated"] = row["untranslated"]
    return out


def run(research_id: str, *, force: bool = False, progress_cb=None, limit: int | None = None) -> dict:
    """Перевод материалов исследования. Вызывается этапом 4 и вручную из API."""
    sql = """SELECT DISTINCT d.* FROM content_documents d
             JOIN content_occurrences o ON o.document_id=d.id
             WHERE o.research_id=? ORDER BY d.id"""
    params: list = [research_id]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    docs = [db.dec(r, "authors", "organizations", "identifiers") for r in db.query(sql, params)]
    done = original = terminology = ai = failed = 0
    coverage_sum = 0.0
    for i, d in enumerate(docs, 1):
        try:
            row = translate_document(d, research_id=research_id, force=force)
        except Exception as exc:                              # noqa: BLE001
            failed += 1
            journal.error(exc, "analytics", "translation.document", source="server",
                          research_id=research_id, entity_kind="document", entity_id=d.get("id"))
            continue
        if not row:
            continue
        done += 1
        coverage_sum += row.get("coverage") or 0.0
        mode = row.get("mode")
        original += mode == "original"
        terminology += mode == "terminology"
        ai += mode == "ai_technical"
        if progress_cb and (i % 10 == 0 or i == len(docs)):
            progress_cb(i, len(docs), f"Переведено материалов: {i}/{len(docs)}")
    out = {"documents": len(docs), "translated": done, "already_russian": original,
           "terminology_mode": terminology, "ai_mode": ai, "failed": failed,
           "coverage": round(coverage_sum / done, 3) if done else 1.0,
           "glossary_version": version(),
           "review_required": terminology + ai,
           "note": "Технический перевод: числа, единицы и обозначения сохранены; "
                   "терминологический режим — черновик, требует вычитки специалистом."}
    journal.record(level="info", kind="analytics", action="translation.run",
                   message=f"Перевод материалов: {done} из {len(docs)} (ИИ {ai}, терминология {terminology})",
                   source="server", research_id=research_id, detail=out)
    return out


def summary(research_id: str) -> dict:
    """Сводка перевода по исследованию — для экрана, отчёта и приёмки."""
    rows = db.query("""SELECT t.mode, COUNT(*) AS n, AVG(t.coverage) AS coverage
                       FROM document_translations t
                       JOIN content_occurrences o ON o.document_id=t.document_id
                       WHERE o.research_id=? GROUP BY t.mode""", (research_id,))
    modes = {r["mode"]: {"count": r["n"], "coverage": round(r["coverage"] or 0, 3)} for r in rows}
    total = sum(m["count"] for m in modes.values())
    review = db.one("""SELECT COUNT(*) AS n FROM document_translations t
                       JOIN content_occurrences o ON o.document_id=t.document_id
                       WHERE o.research_id=? AND t.review_required=1""", (research_id,))
    return {"translated": total, "modes": modes, "review_required": (review or {}).get("n") or 0,
            "glossary_version": version()}
