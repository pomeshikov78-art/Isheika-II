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
    version: str = "EX-1.0.0"
    source: str = "deterministic_thesaurus"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["branches"] = [b.to_dict() for b in self.branches]
        return d


def _quote(term: str) -> str:
    return f'"{term}"' if " " in term else term


def build(q: ParsedQuery, *, languages: list[str] | None = None,
          ai_suggestions: list[str] | None = None) -> Expansion:
    langs = languages or ["ru", "en"]
    ex = Expansion(exclusions=list(q.exclusions))
    core_ru: list[str] = []
    core_en: list[str] = []
    abbr: list[str] = []

    for ent in q.entities:
        entry = THESAURUS.get(ent, {})
        core_ru += entry.get("ru", [])
        core_en += entry.get("en", [])
        abbr += entry.get("abbr", [])

    if not core_ru and not core_en:
        # нет распознанной сущности — работаем с исходными терминами
        base = " ".join(q.object_terms[:4]) or q.raw
        if q.language == "ru":
            core_ru = [base]
        else:
            core_en = [base]

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
            expression=" OR ".join(_quote(t) for t in terms),
            rationale="Перевод технической сущности; тема сохраняется"))
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
