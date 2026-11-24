"""Разбор естественно-языкового запроса (ТЗ-01 §5).

Запрос разбирается на: объект, назначение, техническую сущность, контекст,
географию, временной период и ограничения. Результат — детерминированный,
воспроизводимый и версионируемый; ИИ может лишь ПРЕДЛОЖИТЬ расширения.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

from ..contracts import iso_now

# Словари предметных сущностей (стартовые; расширяются реестром и агентом A01)
ENTITY_LEXICON = {
    "tropospheric_scatter": ["тропосферн", "tropospher", "troposcatter", "тропосферная связь"],
    "radio_relay": ["радиорелейн", "radio relay", "microwave link", "ррл"],
    "antenna": ["антенн", "antenna", "phased array", "фар"],
    "battery": ["аккумулятор", "battery", "накопител", "лиий", "li-ion", "твердотельн"],
    "semiconductor": ["полупроводник", "semiconductor", "gan", "sic", "cmos", "литограф"],
    "ai_accelerator": ["нейропроцессор", "npu", "ai accelerator", "тензорн"],
    "hydrogen": ["водород", "hydrogen", "электролиз", "fuel cell"],
    "uav": ["бпла", "uav", "дрон", "drone", "беспилотн"],
    "satellite": ["спутник", "satellite", "leo", "кубсат", "cubesat"],
    "cryogenic": ["криоген", "cryogenic", "сверхпровод", "superconduct"],
    "material": ["материал", "material", "композит", "composite", "графен", "graphene"],
    "radar": ["радар", "радиолокац", "radar", "рлс"],
    "optical_comm": ["оптическ связь", "free space optic", "fso", "лазерн связь"],
    "mobile_generation": ["6g", "5g", "4g", "imt-2030", "imt-2020", "поколен связи", "мобильн связь"],
    "terahertz": ["терагерц", "terahertz", "thz", "субтерагерц", "sub-thz"],
    "ris": ["ris", "интеллектуальн поверхн", "reconfigurable intelligent", "metasurface", "метаповерхн"],
    "isac": ["isac", "совмещённ связь", "joint communication and sensing", "интегрированн зондирован"],
}

PURPOSE_LEXICON = {
    "communication": ["связь", "communication", "передач данн", "канал", "link", "6g", "5g", "imt-2030"],
    "energy_storage": ["накоплен энерги", "хранен энерги", "energy storage", "ёмкость", "емкость"],
    "propulsion": ["движен", "тяга", "propulsion", "двигател"],
    "sensing": ["обнаружен", "измерен", "мониторинг", "sensing", "датчик"],
    "computing": ["вычислен", "обработк", "computing", "инференс"],
    "manufacturing": ["производств", "изготовлен", "manufacturing", "техпроцесс"],
    "protection": ["защит", "помехоустойч", "security", "шифрован"],
}

CONTEXT_LEXICON = {
    "arctic": ["арктик", "arctic", "крайний север", "низк температур"],
    "marine": ["морск", "marine", "судов", "ship"],
    "space": ["космос", "space", "орбит"],
    "urban": ["городск", "urban", "плотн застройк"],
    "industrial": ["промышлен", "industrial", "цех"],
    "military_open": ["военн", "dual-use", "специальн"],
    "beyond_horizon": ["загоризонт", "beyond horizon", "blos", "дальн связь"],
}

COUNTRY_HINTS = {
    "US": ["сша", "usa", "америк", "us "], "CN": ["китай", "china", "кнр"],
    "RU": ["росси", "russia", "рф"], "JP": ["япони", "japan"], "KR": ["коре", "korea"],
    "DE": ["герман", "germany"], "FR": ["франц", "france"], "GB": ["великобритан", "uk", "britain"],
    "IN": ["инди", "india"], "BR": ["бразил", "brazil"], "AU": ["австрал", "australia"],
    "TR": ["турц", "turkey"], "AE": ["оаэ", "uae"], "SE": ["швец", "sweden"],
    "NO": ["норвег", "norway"], "FI": ["финлянд", "finland"], "PL": ["польш", "poland"],
}

DOC_TYPE_HINTS = {
    "patent": ["патент", "patent", "изобретен", "полезн модел"],
    "standard": ["стандарт", "гост", "standard", "iso", "iec", "itu", "etsi"],
    "report": ["отчёт", "отчет", "report", "ниокр", "technical report"],
    "dataset": ["датасет", "dataset", "данн эксперимент"],
    "product": ["изделие", "серийн", "product", "поставк", "производител"],
    "thesis": ["диссерта", "thesis"],
    "article": ["стать", "публикац", "article", "paper"],
}

STOPWORDS = set("""и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам сказал ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее кажется сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между the a an of for and to in on with by from as at is are was were be been this that these those it its""".split())


@dataclass
class ParsedQuery:
    raw: str
    normalized: str = ""
    tokens: list[str] = field(default_factory=list)
    object_terms: list[str] = field(default_factory=list)
    purpose: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    period_from: int | None = None
    period_to: int | None = None
    doc_types: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    language: str = "ru"
    parse_version: str = "QP-1.0.0"
    parsed_at: str = field(default_factory=iso_now)

    def to_dict(self) -> dict:
        return asdict(self)


def detect_language(text: str) -> str:
    cyr = len(re.findall(r"[а-яА-ЯёЁ]", text))
    lat = len(re.findall(r"[a-zA-Z]", text))
    if cyr and cyr >= lat:
        return "ru"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u0600-\u06ff]", text):
        return "ar"
    return "en"


# Короткие технические обозначения: отбрасывать их нельзя — запрос «6G»
# разбирался в пустой список терминов, и ни один документ не проходил порог
# релевантности (прогон 1.5.0 на реальных источниках).
SHORT_TECH = set("""6g 5g 4g 3g 2g ai ml dl rf thz uhf shf ehf vhf hf lf mf if dc ac
 mimo ofdm iot urllc embb mmtc ris isac oam qkd leo geo meo uav gnss imu lidar adc dac
 fpga asic cmos gan sic inp qam psk ldpc snr sinr ber evm csi ran oran ntn d2d v2x xr ar
 vr mr api sdk cpu gpu npu tpu soc sip pcb mems nems los nlos bw fft dft awgn rms qpsk
""".split())


# Короткие обозначения-ОМОНИМЫ: «6G» — и поколение связи, и краситель Rhodamine 6G;
# «5g» — и стандарт, и масса в граммах; «LEO» — и орбита, и имя. Такое обозначение
# само по себе не подтверждает предметную область (ИД-19): требуется второй,
# независимый сигнал области (иная сущность, назначение или иное слово ядра).
AMBIGUOUS_SHORT = set("""6g 5g 4g 3g 2g ris leo geo meo sic gan inp ar vr mr if dc ac hf lf mf oam soc sip
""".split())


def tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9][a-zA-Zа-яА-ЯёЁ0-9\-]{1,}", text.lower())
    out = []
    for w in words:
        if w in STOPWORDS:
            continue
        if len(w) > 2 or w in SHORT_TECH or re.fullmatch(r"\d+[a-z]{1,3}", w):
            out.append(w)
    return out


def parse(text: str) -> ParsedQuery:
    raw = (text or "").strip()
    q = ParsedQuery(raw=raw)
    q.normalized = re.sub(r"\s+", " ", raw.lower()).strip()
    q.language = detect_language(raw)
    q.tokens = tokenize(raw)
    low = q.normalized

    for code, keys in ENTITY_LEXICON.items():
        if any(k in low for k in keys):
            q.entities.append(code)
    for code, keys in PURPOSE_LEXICON.items():
        if any(k in low for k in keys):
            q.purpose.append(code)
    for code, keys in CONTEXT_LEXICON.items():
        if any(k in low for k in keys):
            q.context.append(code)
    for iso, keys in COUNTRY_HINTS.items():
        if any(k in low for k in keys):
            q.countries.append(iso)
    for dt, keys in DOC_TYPE_HINTS.items():
        if any(k in low for k in keys):
            q.doc_types.append(dt)

    # временной период
    years = [int(y) for y in re.findall(r"\b(19\d{2}|20\d{2})\b", low)]
    m = re.search(r"(?:с|from)\s*(19\d{2}|20\d{2})\s*(?:по|to|-|–)\s*(19\d{2}|20\d{2})", low)
    if m:
        q.period_from, q.period_to = int(m.group(1)), int(m.group(2))
    elif re.search(r"последн\w*\s*(\d+)\s*(?:лет|год)", low):
        n = int(re.search(r"последн\w*\s*(\d+)\s*(?:лет|год)", low).group(1))
        import datetime
        q.period_to = datetime.date.today().year
        q.period_from = q.period_to - n
    elif years:
        q.period_from, q.period_to = min(years), max(years)

    # ограничения и исключения
    for m in re.finditer(r"(?:без|кроме|исключая|exclude|not)\s+([а-яa-z0-9\- ]{3,40})", low):
        q.exclusions.extend(tokenize(m.group(1))[:3])
    for m in re.finditer(r"(?:не хуже|не менее|at least|минимум|до)\s*([\d.,]+\s*[а-яa-z/°%]{0,12})", low):
        q.constraints.append(m.group(0).strip())

    # объект исследования — первые значимые термины вне служебных слов
    q.object_terms = q.tokens[:6]
    return q
