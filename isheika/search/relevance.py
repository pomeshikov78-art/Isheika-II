"""Движок релевантности (ТЗ-03 §2).

R(d,q) = 0.30·S + 0.25·T + 0.15·C + 0.15·E + 0.10·K + 0.05·F

S — семантическое соответствие. В базовой конфигурации без векторной модели
используется лексико-семантическая аппроксимация (взвешенное покрытие терминов
ядра + IDF-взвешенное пересечение). Факт аппроксимации фиксируется в components
и в отчёте: подмена метода не допускается. При подключении pgvector/эмбеддингов
компонента S заменяется без изменения весов и порогов.

Жёсткое правило ТЗ-01 §5: материал, содержащий лишь отдельное совпавшее слово,
не попадает в основную выдачу — вводится gate по ядру запроса.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from ..analytics import methodologies as M
from ..contracts import Document, iso_now
from .expansion import Expansion
from .query_parser import ParsedQuery, ENTITY_LEXICON, PURPOSE_LEXICON, CONTEXT_LEXICON, tokenize

_WORD = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]{3,}")


@dataclass
class RelevanceResult:
    score: float
    cls: str                       # DIRECT | ADJACENT | BELOW_THRESHOLD (ИД-07)
    components: dict
    reason: str
    weights: dict
    gate: dict
    methodology_version: str
    assessed_at: str
    methodology_id: str = ""
    methodology_code: str = "RELEVANCE_V1"
    reason_codes: list = None
    decision: str = "INCLUDE"

    def to_dict(self) -> dict:
        return {
            "relevance_score": round(self.score, 4), "relevance_class": self.cls,
            "score": round(self.score, 4), "class": self.cls,
            "components": {k: round(v, 4) if isinstance(v, float) else v for k, v in self.components.items()},
            "reason": self.reason, "reason_codes": self.reason_codes or [],
            "decision": self.decision, "weights": self.weights, "gate": self.gate,
            "methodology_id": self.methodology_id, "methodology_code": self.methodology_code,
            "methodology_version": self.methodology_version, "assessed_at": self.assessed_at,
        }


def classify(score: float, thresholds: dict | None = None) -> str:
    """ИД-07: единственный источник правил отнесения к классу релевантности.

    DIRECT ≥ 0,80; ADJACENT 0,60…0,79; BELOW_THRESHOLD < 0,60.
    Пороги берутся из активной методики RELEVANCE_V1 (реестр ИД-09),
    а не из кода; буквы A/B/C допустимы только как псевдонимы в UI.
    """
    if thresholds is None:
        meth = M.active("RELEVANCE")
        thresholds = {"DIRECT": meth["thresholds"]["DIRECT"], "ADJACENT": meth["thresholds"]["ADJACENT"]}
    direct = float(thresholds.get("DIRECT", 0.80))
    adjacent = float(thresholds.get("ADJACENT", 0.60))
    s = round(float(score), 6)
    if s >= direct:
        return "DIRECT"
    if s >= adjacent:
        return "ADJACENT"
    return "BELOW_THRESHOLD"


CLASS_ALIASES = {"A": "DIRECT", "B": "ADJACENT", "C": "BELOW_THRESHOLD"}


def _terms_of(text: str) -> set[str]:
    return set(w.lower() for w in _WORD.findall(text or ""))


def _phrase_hit(phrase: str, blob: str) -> bool:
    """Сопоставление фразы с учётом словоизменения (RU/EN).

    Точное вхождение проверяется первым; при его отсутствии используется
    усечённая основа каждого слова (морфологическая аппроксимация без
    внешних NLP-библиотек). Ложные срабатывания ограничены длиной основы.
    """
    phrase = phrase.lower().strip()
    if not phrase:
        return False
    if re.search(re.sub(r"\s+", r"\\s+", re.escape(phrase)), blob):
        return True
    parts = [w for w in re.split(r"\s+", phrase) if w]
    stems = []
    for w in parts:
        base = w[:6] if len(w) > 6 else w[:max(3, len(w) - 2)]
        stems.append(re.escape(base) + r"[a-zа-яё0-9]*")
    return re.search(r"\s+".join(stems), blob) is not None


def _stem_overlap(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    aa = {t[:6] for t in a}
    bb = {t[:6] for t in b}
    inter = aa & bb
    return len(inter) / max(3.0, min(len(aa), 12.0))


def assess(doc: Document, q: ParsedQuery, ex: Expansion, *,
           required_types: list[str] | None = None,
           corpus_df: dict[str, int] | None = None, corpus_n: int = 0) -> RelevanceResult:
    meth = M.active("RELEVANCE")            # ИД-09: активная версия из реестра методик
    w = meth["parameters"]["weights"]
    th = {"direct": meth["thresholds"]["DIRECT"], "adjacent": meth["thresholds"]["ADJACENT"]}
    source_quality = M.active("SOURCE_QUALITY")["parameters"]["class_quality"]
    blob = (doc.title + " \n " + doc.abstract + " \n " + doc.text_excerpt).lower()
    dterms = _terms_of(blob)

    core_terms = [t.lower() for t in ex.core_terms] or q.object_terms
    core_phrases = [t for t in core_terms if " " in t]
    core_words = [t for t in core_terms if " " not in t]

    phrase_hits = [p for p in core_phrases if _phrase_hit(p, blob)]
    word_hits = [t for t in core_words if t[:6] in {x[:6] for x in dterms}]
    title_blob = (doc.title or "").lower()

    # Термы расширения — СИНОНИМЫ, а не независимые требования:
    # совпадение любого из них означает полное терминологическое покрытие.
    # Покрытие считается внутри языковой группы (RU/EN) и берётся максимум.
    def _is_ru(t: str) -> bool:
        return bool(re.search(r"[а-яё]", t))

    groups = {"ru": [t for t in core_terms if _is_ru(t)], "en": [t for t in core_terms if not _is_ru(t)]}
    any_exact = bool(phrase_hits or word_hits)
    best_group_ratio = 0.0
    for g in groups.values():
        if not g:
            continue
        hits = sum(1 for t in g if (t in phrase_hits if " " in t else t in word_hits))
        if hits:
            best_group_ratio = max(best_group_ratio, min(1.0, 0.85 + 0.15 * (hits - 1)))

    qterms = set(q.tokens) | {t for p in core_phrases for t in tokenize(p)}
    idf = 0.0
    if corpus_df and corpus_n:
        inter = qterms & dterms
        if inter:
            idf = sum(math.log(1 + corpus_n / (1 + corpus_df.get(t, 0))) for t in inter) / \
                  max(1.0, sum(math.log(1 + corpus_n / (1 + corpus_df.get(t, 0))) for t in qterms))
    overlap = _stem_overlap(qterms, dterms)
    title_exact = any(_phrase_hit(p, title_blob) for p in core_phrases) or \
                  any(t[:6] in {x[:6] for x in _terms_of(title_blob)} for t in core_words)
    S = max(0.92 if title_exact else 0.0,
            0.80 if any_exact else 0.0,
            min(1.0, 0.45 * overlap + 0.25 * (idf or overlap)))

    # --- T: техническая сущность и назначение
    ent_hits = 0
    ent_total = max(1, len(q.entities))
    for ent in q.entities:
        keys = ENTITY_LEXICON.get(ent, [])
        if any(k in blob for k in keys):
            ent_hits += 1
    purpose_hits = 0
    for pp in q.purpose:
        keys = PURPOSE_LEXICON.get(pp, [])
        if any(k in blob for k in keys):
            purpose_hits += 1
    if q.entities:
        T = 0.75 * (ent_hits / ent_total) + 0.25 * (purpose_hits / max(1, len(q.purpose)) if q.purpose else ent_hits / ent_total)
    else:
        T = min(1.0, best_group_ratio)
    T = min(1.0, T)

    # --- C: контекст
    if q.context:
        chits = 0.0
        for ctx in q.context:
            keys = CONTEXT_LEXICON.get(ctx, [])
            if any(k in blob for k in keys):
                chits += 1.0
            elif any(any(k in p for k in keys) for p in phrase_hits):
                # контекст входит в само ядро темы (напр. «загоризонтная связь»):
                # частичное подтверждение 0.5, а не полное
                chits += 0.5
        C = chits / len(q.context)
    else:
        C = 0.5      # контекст не задан — нейтральное значение, не 0 и не 1
    # --- E: соответствие типу требуемого доказательства
    req = required_types or q.doc_types
    if req:
        E = 1.0 if doc.doc_type in req else (0.5 if doc.evidence_class in ("primary_peer_reviewed", "primary_report", "dataset") else 0.2)
    else:
        quality = source_quality.get(doc.evidence_class, 0.15)
        E = quality
    # --- K: терминологическое/классификационное соответствие
    abbr_hits = sum(1 for a in ex.abbreviations if re.search(r"\b" + re.escape(a.lower()) + r"\b", blob))
    K = min(1.0, 0.75 * best_group_ratio + 0.25 * min(1.0, abbr_hits / 2))
    if not any_exact:
        K = min(K, 0.3 * overlap)

    # --- F: актуальность
    year = None
    if doc.published_at:
        mm = re.search(r"(19|20)\d{2}", doc.published_at)
        year = int(mm.group(0)) if mm else None
    if year:
        import datetime
        age = max(0, datetime.date.today().year - year)
        half = meth["parameters"]["freshness_half_life_years"]
        F = 0.5 ** (age / half)
    else:
        F = 0.3      # дата неизвестна — не ноль, но и не высокая актуальность

    raw = w["S"] * S + w["T"] * T + w["C"] * C + w["E"] * E + w["K"] * K + w["F"] * F

    # --- gate: защита от «одного совпавшего слова»
    gate = {"core_phrase_hits": len(phrase_hits), "core_word_hits": len(word_hits), "title_exact": title_exact,
            "entity_hits": ent_hits, "passed": True, "rule": ""}
    if not phrase_hits and ent_hits == 0 and len(word_hits) <= 1:
        gate["passed"] = False
        gate["rule"] = "Совпало не более одного отдельного слова, ядро темы не подтверждено"
        raw = min(raw, th["adjacent"] - 0.01)
    if doc.identifiers.get("simulated"):
        gate["simulated"] = True

    score = max(0.0, min(1.0, raw))
    cls = classify(score, {"DIRECT": th["direct"], "ADJACENT": th["adjacent"]})

    reasons, codes = [], []
    if phrase_hits:
        reasons.append("точное совпадение ядра: " + ", ".join(phrase_hits[:2]))
        codes.append("CORE_PHRASE_MATCH")
    if ent_hits:
        reasons.append(f"техническая сущность подтверждена ({ent_hits}/{ent_total})")
        codes.append("TECH_ENTITY_MATCH")
    if req:
        reasons.append("тип документа: " + doc.doc_type + (" (соответствует запросу)" if doc.doc_type in req else " (не запрошенный тип)"))
        codes.append("EVIDENCE_TYPE_MATCH" if doc.doc_type in req else "EVIDENCE_TYPE_MISMATCH")
    if not gate["passed"]:
        reasons.append(gate["rule"])
        codes.append("CORE_GATE_FAILED")
    if year is None:
        reasons.append("дата публикации неизвестна — актуальность оценена консервативно")
        codes.append("DATE_UNKNOWN")
    if cls == "BELOW_THRESHOLD":
        codes.append("BELOW_THRESHOLD")

    return RelevanceResult(score, cls, {"S": S, "T": T, "C": C, "E": E, "K": K, "F": F,
                                       "S_method": "lexical_semantic_approximation (embeddings not configured)"},
                           "; ".join(reasons) or "Слабое соответствие запросу",
                           w, gate, meth["code"] + " " + meth["version"], iso_now(),
                           methodology_id=meth["id"], methodology_code=meth["code"],
                           reason_codes=codes,
                           decision="EXCLUDE" if cls == "BELOW_THRESHOLD" else "INCLUDE")


def build_df(docs: list[Document]) -> tuple[dict[str, int], int]:
    df: dict[str, int] = {}
    for d in docs:
        for t in set(_terms_of(d.title + " " + d.abstract)):
            df[t] = df.get(t, 0) + 1
    return df, len(docs)


# ------------------------------------------------------------------ метрики качества

def _relevant(label: int) -> int:
    """Разметка градуированная (0 — нет, 1 — смежное, 2 — прямое).
    Для Precision/Recall релевантным считается любой уровень ≥ 1."""
    return 1 if label and label >= 1 else 0


def precision_at_k(labels: list[int], k: int) -> float | None:
    if not labels:
        return None
    top = labels[:k]
    return sum(_relevant(x) for x in top) / len(top)


def ndcg_at_k(labels: list[int], k: int) -> float | None:
    if not labels:
        return None
    top = labels[:k]
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(top))
    ideal = sorted(labels, reverse=True)[:k]
    idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal))
    return dcg / idcg if idcg else None


def recall_at_k(labels: list[int], k: int, total_relevant: int) -> float | None:
    if not total_relevant:
        return None
    return sum(_relevant(x) for x in labels[:k]) / total_relevant
