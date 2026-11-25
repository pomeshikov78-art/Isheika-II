"""Контролируемое расширение запроса (ТЗ-01 §5, ТЗ-04 UI-03).

Расширения не должны терять исходную тему: каждая ветвь содержит обязательное
ядро (техническую сущность) и необязательные уточнения. Ветви и исключения
показываются пользователю до запуска поиска.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from .query_parser import ParsedQuery

# Стартовый тезаурус: синонимы, аббревиатуры, переводы. Пополняется реестром
# терминов и агентом A01 (предложения ИИ проходят проверку ядра).
THESAURUS: dict[str, dict[str, list[str]]] = {
    "tropospheric_scatter": {
        "ru": ["тропосферная связь", "тропосферное рассеяние", "тропосферная радиосвязь", "загоризонтная связь"],
        "en": ["tropospheric scatter", "troposcatter", "tropospheric radio propagation", "beyond line of sight"],
        "abbr": ["TROS", "BLOS"],
    },
    "mobile_generation": {
        "ru": ["6G", "связь шестого поколения", "мобильная связь нового поколения", "IMT-2030"],
        "en": ["6G", "sixth generation mobile", "IMT-2030", "next generation wireless"],
        "abbr": ["6G", "IMT-2030"],
    },
    "terahertz": {
        "ru": ["терагерцовый диапазон", "субтерагерцовая связь", "терагерцовая связь"],
        "en": ["terahertz communication", "sub-THz", "THz band"], "abbr": ["THz"],
    },
    "ris": {
        "ru": ["перенастраиваемая интеллектуальная поверхность", "метаповерхность"],
        "en": ["reconfigurable intelligent surface", "intelligent reflecting surface", "metasurface"],
        "abbr": ["RIS", "IRS"],
    },
    "isac": {
        "ru": ["совмещённая связь и зондирование", "интегрированное зондирование и связь"],
        "en": ["integrated sensing and communication", "joint communication and sensing"],
        "abbr": ["ISAC", "JCAS"],
    },
    "radio_relay": {"ru": ["радиорелейная линия", "РРЛ", "радиорелейная связь"],
                    "en": ["radio relay link", "microwave backhaul", "point-to-point microwave"], "abbr": ["RRL", "PTP"]},
    "antenna": {"ru": ["антенная решётка", "фазированная антенная решётка", "АФАР", "апертура"],
                "en": ["antenna array", "phased array", "aperture", "beamforming"], "abbr": ["AESA", "PAA"]},
    "battery": {"ru": ["литий-ионный аккумулятор", "твердотельный аккумулятор", "накопитель энергии", "удельная энергоёмкость"],
                "en": ["lithium-ion battery", "solid-state battery", "energy density", "specific energy"],
                "abbr": ["LIB", "SSB", "Wh/kg"]},
    "semiconductor": {"ru": ["полупровниковая технология", "нитрид галлия", "карбид кремния", "технологическая норма"],
                      "en": ["semiconductor process", "gallium nitride", "silicon carbide", "process node"],
                      "abbr": ["GaN", "SiC", "nm"]},
    "hydrogen": {"ru": ["водородная энергетика", "электролизёр", "топливный элемент"],
                 "en": ["hydrogen energy", "electrolyzer", "fuel cell", "PEM"], "abbr": ["PEMFC", "SOEC"]},
    "uav": {"ru": ["беспилотный летательный аппарат", "БПЛА", "дрон"],
            "en": ["unmanned aerial vehicle", "drone", "UAS"], "abbr": ["UAV", "BVLOS"]},
    "satellite": {"ru": ["спутниковая связь", "низкоорбитальная группировка", "малый космический аппарат"],
                  "en": ["satellite communication", "LEO constellation", "small satellite"], "abbr": ["LEO", "GEO"]},
    "cryogenic": {"ru": ["криогенная техника", "сверхпроводимость", "охлаждение"],
                  "en": ["cryogenics", "superconductivity", "cryocooler"], "abbr": ["HTS", "LTS"]},
    "material": {"ru": ["композиционный материал", "новые материалы", "покрытие"],
                 "en": ["composite material", "advanced materials", "coating"], "abbr": ["CFRP", "CMC"]},
    "radar": {"ru": ["радиолокационная станция", "РЛС", "радар"],
              "en": ["radar", "synthetic aperture radar"], "abbr": ["SAR", "AESA"]},
    "optical_comm": {"ru": ["оптическая связь", "лазерная линия связи", "атмосферная оптическая линия"],
                     "en": ["free-space optical communication", "laser communication"], "abbr": ["FSO"]},
    "ai_accelerator": {"ru": ["ускоритель нейросетей", "нейропроцессор", "вычислитель ИИ"],
                       "en": ["AI accelerator", "neural processing unit", "inference accelerator"], "abbr": ["NPU", "TPU"]},
    "digital_twin": {"ru": ["цифровой двойник", "цифровые двойники", "цифровая модель объекта",
                            "виртуальный прототип"],
                     "en": ["digital twin", "digital twins", "digital shadow", "virtual prototype"],
                     "abbr": ["DT"]},
}

CONTEXT_TERMS = {
    "arctic": {"ru": ["арктика", "низкие температуры", "крайний север"], "en": ["arctic", "low temperature", "cold climate"]},
    "beyond_horizon": {"ru": ["загоризонтный", "дальняя связь"], "en": ["beyond horizon", "long range link"]},
    "marine": {"ru": ["морской", "судовой"], "en": ["maritime", "shipborne"]},
    "space": {"ru": ["космический", "орбитальный"], "en": ["space", "orbital"]},
    "industrial": {"ru": ["промышленный"], "en": ["industrial"]},
    "urban": {"ru": ["городской"], "en": ["urban"]},
}

PURPOSE_TERMS = {
    "communication": {"ru": ["связь", "передача данных"], "en": ["communication", "data link"]},
    "energy_storage": {"ru": ["накопление энергии"], "en": ["energy storage"]},
    "computing": {"ru": ["вычисления"], "en": ["computing"]},
    "sensing": {"ru": ["обнаружение", "измерение"], "en": ["sensing", "detection"]},
    "propulsion": {"ru": ["движение", "тяга"], "en": ["propulsion"]},
    "manufacturing": {"ru": ["производство"], "en": ["manufacturing"]},
    "protection": {"ru": ["помехоустойчивость", "защита"], "en": ["interference immunity", "security"]},
}


@dataclass
class Branch:
    name: str
    expression: str
    kind: str = "core"          # core | adjacent | contextual
    terms: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Expansion:
    core_terms: list[str] = field(default_factory=list)
    synonyms: list[str] = field(default_factory=list)
    abbreviations: list[str] = field(default_factory=list)
    translations: list[str] = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    version: str = "EX-1.1.0"
    source: str = "deterministic_thesaurus"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["branches"] = [b.to_dict() for b in self.branches]
        return d


def _quote(term: str) -> str:
    return f'"{term}"' if " " in term else term


# ---------------------------------------------------------------- обратный глоссарий
def _stem_ru(word: str) -> str:
    """Грубая основа русского слова: «цифровых»/«цифровой» → «цифров».

    Морфологического анализатора в ядре нет (только стандартная библиотека),
    поэтому сопоставление идёт по усечённому префиксу — этого достаточно,
    чтобы найти термин глоссария в словоформе запроса.
    """
    w = word.lower().replace("ё", "е")
    return w[:6] if len(w) > 6 else w[:4]


_REVERSE: dict | None = None


def _reverse_glossary() -> dict:
    """Обратный словарь RU→EN из глоссария технического перевода (G-1.7.0).

    ИД-29: если тема не распознана словарём сущностей, англоязычная ветвь
    раньше не строилась вовсе — зарубежные источники получали кириллическую
    фразу и не давали материалов. Глоссарий уже содержит пары EN→RU, поэтому
    перевод терма берётся из него детерминированно, без обращения к ИИ.
    """
    global _REVERSE
    if _REVERSE is not None:
        return _REVERSE
    from ..translation import glossary
    g = glossary()
    phrases: dict[str, str] = {}
    words: dict[str, str] = {}
    stems: dict[str, str] = {}
    for en, ru in sorted(g.get("phrases", {}).items()):
        key = " ".join(str(ru).lower().split())
        phrases.setdefault(key, en)
    for en, ru in sorted(g.get("words", {}).items()):
        key = str(ru).lower().strip()
        if not key or " " in key:
            continue
        words.setdefault(key, en)
        stems.setdefault(_stem_ru(key), en)
    _REVERSE = {"phrases": phrases, "words": words, "stems": stems,
                "version": g.get("version", "G-0.0.0")}
    return _REVERSE


def _en_from_glossary(text: str, tokens: list[str]) -> tuple[list[str], list[str]]:
    """Возвращает (фразы EN, отдельные слова EN) для русского запроса."""
    rev = _reverse_glossary()
    low = " ".join((text or "").lower().split()).replace("ё", "е")
    phrases: list[str] = []
    for ru, en in sorted(rev["phrases"].items(), key=lambda kv: -len(kv[0])):
        stem_phrase = " ".join(_stem_ru(w) for w in ru.split())
        hay = " ".join(_stem_ru(w) for w in low.split())
        if ru in low or (len(ru.split()) > 1 and stem_phrase in hay):
            if en not in phrases:
                phrases.append(en)
    words: list[str] = []
    for t in tokens:
        en = rev["words"].get(t.lower()) or rev["stems"].get(_stem_ru(t))
        if en and en not in words and not any(en in p for p in phrases):
            words.append(en)
    return phrases[:4], words[:4]


def _bigrams(tokens: list[str]) -> list[str]:
    """Соседние пары значимых слов: «цифровых двойников», «системах связи».

    Одна склеенная фраза из четырёх слов («технологии цифровых двойников
    системах») не встречается в текстах дословно и давала почти нулевую
    полноту (ИД-29: 13 документов, 1 прямой против 81/39 у короткого запроса).
    """
    return [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]


def build(q: ParsedQuery, *, languages: list[str] | None = None,
          ai_suggestions: list[str] | None = None) -> Expansion:
    langs = languages or ["ru", "en"]
    ex = Expansion(exclusions=list(q.exclusions))
    core_ru: list[str] = []
    core_en: list[str] = []
    abbr: list[str] = []
    en_join = " OR "
    en_rationale = "Перевод технической сущности; тема сохраняется"

    for ent in q.entities:
        entry = THESAURUS.get(ent, {})
        core_ru += entry.get("ru", [])
        core_en += entry.get("en", [])
        abbr += entry.get("abbr", [])

    if not core_ru and not core_en:
        # Тема не распознана словарём сущностей (ИД-29). Раньше здесь склеивались
        # четыре слова в одну точную фразу на языке запроса: «технологии цифровых
        # двойников системах» — без англоязычной ветви и без синонимов. Теперь:
        # пары соседних слов + перевод по глоссарию для второй языковой ветви.
        tokens = q.object_terms[:5]
        pairs = _bigrams(tokens)[:3]
        base = pairs or [" ".join(tokens[:4]) or q.raw]
        if len(tokens) <= 2:
            # короткая тема: пары совпадают с самой фразой — добавляем и слова
            base = list(dict.fromkeys(base + tokens))
        if q.language == "ru":
            core_ru = list(dict.fromkeys(base))
            en_phrases, en_words = _en_from_glossary(q.raw, tokens)
            core_en = en_phrases
            if not core_en and en_words:
                # отдельных слов достаточно только совместно: все понятия сразу
                core_en = en_words
                en_join = " AND "
                en_rationale = ("Перевод отдельных слов по глоссарию %s; понятия соединены по И, "
                                "чтобы не терять тему" % _reverse_glossary()["version"])
                ex.warnings.append(
                    "Тема не распознана словарём сущностей: англоязычная ветвь построена "
                    "по глоссарию %s из отдельных слов (соединены по И). Уточните формулировку "
                    "или добавьте термин в тезаурус." % _reverse_glossary()["version"])
            elif core_en:
                en_rationale = "Перевод темы по глоссарию %s (сущность не распознана)" % _reverse_glossary()["version"]
                ex.warnings.append(
                    "Тема не распознана словарём сущностей: ветви построены по исходным словам "
                    "и глоссарию %s. Проверьте предпросмотр перед запуском." % _reverse_glossary()["version"])
            else:
                ex.warnings.append(
                    "Тема не распознана словарём сущностей, перевода в глоссарии нет: "
                    "англоязычная ветвь не построена — зарубежные источники материалов не дадут.")
        else:
            core_en = list(dict.fromkeys(base))
            ex.warnings.append(
                "Тема не распознана словарём сущностей: поиск идёт по исходным словам. "
                "Проверьте предпросмотр выражений перед запуском.")
        if len(tokens) == 1 and len(tokens[0]) <= 6 and not core_en:
            ex.warnings.append(
                "Сокращение «%s» не раскрыто: синонимов и перевода нет. Раскройте его словами — "
                "иначе поиск найдёт только дословные упоминания." % tokens[0])

    ex.core_terms = list(dict.fromkeys(core_ru + core_en))
    ex.abbreviations = list(dict.fromkeys(abbr))
    ex.synonyms = list(dict.fromkeys(core_ru))
    ex.translations = list(dict.fromkeys(core_en))

    if ai_suggestions:
        # предложения ИИ принимаются только как смежная ветвь и маркируются
        extra = [t.strip() for t in ai_suggestions if t.strip()][:12]
        if extra:
            ex.branches.append(Branch(
                name="Предложения ИИ (требуют проверки)", kind="adjacent", terms=extra,
                expression=" OR ".join(_quote(t) for t in extra),
                rationale="Источник — модель ИИ; не влияет на основную выдачу без подтверждения"))

    # --- ветвь 1: ядро на русском
    if core_ru and ("ru" in langs or not langs):
        terms = core_ru[:4]
        ex.branches.append(Branch(
            name="Ядро (RU)", kind="core", terms=terms,
            expression=" OR ".join(_quote(t) for t in terms),
            rationale="Исходная техническая сущность на русском языке"))
    # --- ветвь 2: ядро на английском
    if core_en and "en" in langs:
        terms = core_en[:4]
        ex.branches.append(Branch(
            name="Core (EN)", kind="core", terms=terms,
            expression=en_join.join(_quote(t) for t in terms),
            rationale=en_rationale))
    # --- ветвь 3: аббревиатуры (только вместе с ядром)
    if abbr:
        ex.branches.append(Branch(
            name="Аббревиатуры + ядро", kind="adjacent", terms=abbr[:5],
            expression="(" + " OR ".join(abbr[:5]) + ") AND (" + " OR ".join(_quote(t) for t in (core_en[:2] or core_ru[:2])) + ")",
            rationale="Аббревиатуры без ядра дают ложные совпадения"))
    # --- ветвь 4: контекст
    for ctx in q.context:
        ct = CONTEXT_TERMS.get(ctx, {})
        terms = (ct.get("ru", []) if q.language == "ru" else ct.get("en", []))[:2]
        if terms:
            ex.branches.append(Branch(
                name=f"Контекст: {ctx}", kind="contextual", terms=terms,
                expression="(" + " OR ".join(_quote(t) for t in (core_en[:2] or core_ru[:2])) + ") AND (" + " OR ".join(_quote(t) for t in terms) + ")",
                rationale="Контекстное уточнение; в основную выдачу не подмешивается"))
    # --- ветвь 5: назначение/проблема
    for pp in q.purpose[:2]:
        pt = PURPOSE_TERMS.get(pp, {})
        terms = pt.get("en", [])[:2]
        if terms and core_en:
            ex.branches.append(Branch(
                name=f"Назначение: {pp}", kind="adjacent", terms=terms,
                expression="(" + " OR ".join(_quote(t) for t in core_en[:2]) + ") AND (" + " OR ".join(_quote(t) for t in terms) + ")",
                rationale="Функциональное уточнение"))
    return ex


def primary_expression(ex: Expansion, q: ParsedQuery) -> str:
    core = [b for b in ex.branches if b.kind == "core"]
    if core:
        return " OR ".join(f"({b.expression})" for b in core)
    return q.raw
