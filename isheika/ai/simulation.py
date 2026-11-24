"""Детерминированный экстрактор признаков (DEV-профиль / fallback без ключей).

Это НЕ модель ИИ. Это воспроизводимые эвристики извлечения признаков из
документов, которые дают расчётному ядру ТЗ-03 те же входы, что и ИИ-агенты.
Все результаты помечаются simulated=true и producer="deterministic_extractor".

Благодаря этому контуру:
  * расчёты TRL/реализуемости проверяемы без внешних моделей;
  * при подключении реальных моделей структура входов не меняется;
  * сравнение «ИИ против детерминированного ядра» возможно на тех же данных.
"""
from __future__ import annotations

import re
from collections import Counter

# Признаки зрелости: маркеры в тексте -> критерии TRL
TRL_MARKERS = {
    "T1.1": [" principle", "принцип", "theoretical", "теоретическ", "basic study", "fundamental"],
    "T1.2": ["application", "применен", "proposed use", "предложен"],
    "T2.1": ["concept", "концепц", "design study", "предложенн", "scheme", "архитектур"],
    "T2.2": ["feasib", "достижим", "analysis shows", "расчёт показ", "simulation"],
    "T3.1": ["experiment", "эксперимент", "measured", "измерен", "test setup", "испытан", "laboratory experiment"],
    "T3.2": ["db", "дб", "ghz", "ггц", "w/kg", "вт/кг", "%", "mw", "мвт", "km", "км", "measured value"],
    "T4.1": ["laboratory prototype", "лабораторн макет", "breadboard", "макет", "benchtop"],
    "T4.2": ["integrated", "интегрирован", "assembly", "сборк"],
    "T5.1": ["relevant environment", "релевантн сред", "field test", "полев испытан", "outdoor"],
    "T5.2": ["operating range", "границы применим", "conditions", "условия эксплуатации"],
    "T6.1": ["prototype", "прототип", "demonstrator", "демонстратор", "subsystem"],
    "T6.2": ["test protocol", "протокол испытан", "trial results", "результаты испытаний"],
    "T7.1": ["operational environment", "эксплуатац", "field trial", "опытная эксплуатация", "on-site", "в составе"],
    "T7.2": ["performance verified", "подтверждён", "measured in operation", "эксплуатационные характеристики"],
    "T8.1": ["qualification", "квалификацион", "certified", "сертифика", "type approval", "приёмочные испытания"],
    "T8.2": ["production ready", "готовность производства", "serial production", "серийное производство", "поставк"],
    "T9.1": ["deployed", "внедрен", "in service", "штатная эксплуатация", "commissioned", "введён в эксплуатацию"],
    "T9.2": ["fleet", "series production", "серийн", "operational use", "промышленная эксплуатация", "commercial operation"],
}

FACTOR_MARKERS = {
    "k1": ["theory", "теоретическ", "principle", "модель", "analysis", "обоснован"],
    "k2": ["experiment", "эксперимент", "measured", "измерен", "испытан", "test"],
    "k3": ["prototype", "прототип", "demonstrator", "демонстратор", "макет", "образец"],
    "k4": ["trl", "зрелост", "qualification", "квалификац", "deployed", "внедрен"],
    "k5": ["component", "компонент", "material", "материал", "supply", "поставк компонент", "gan", "sic"],
    "k6": ["manufactur", "производств", "fabrication", "изготовлен", "production line", "серийн"],
    "k7": ["power", "мощност", "thermal", "тепло", "energy", "энерг", "limit", "ограничен", "efficiency", "кпд"],
    "k8": ["cost", "стоимост", "price", "цен", "econom", "эконом", "$", "руб"],
    "k9": ["standard", "стандарт", "regulation", "норматив", "certification", "сертификац", "ГОСТ", "ETSI", "ITU"],
}

BARRIER_MARKERS = {
    "физические": ["physical limit", "физическ ограничен", "diffraction", "дифракц", "затухание", "attenuation"],
    "энергетические": ["power consumption", "энергопотреблен", "budget", "энергетическ бюджет", "мощность передатчика"],
    "тепловые": ["thermal", "теплоотвод", "перегрев", "охлажден", "cryocooler"],
    "материальные": ["material", "материал", "деградац", "corrosion", "корроз"],
    "компонентные": ["component shortage", "дефицит компонент", "недоступн компонент", "supply chain", "импортозамещ"],
    "программные": ["software", "программн", "algorithm", "алгоритм", "прошивк"],
    "производственные": ["manufacturing", "производств", "yield", "выход годных", "оснастк"],
    "экономические": ["cost", "стоимост", "окупаем", "capex", "инвестиц"],
    "нормативные": ["regulation", "норматив", "лицензир", "частотн присвоен", "сертификац"],
    "эксплуатационные": ["maintenance", "обслуживан", "надёжност", "reliability", "эксплуатац"],
    "кадровые": ["staff", "кадр", "специалист", "компетенц"],
}

NUM_UNIT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(дБ|db|dbm|дбм|ГГц|ghz|МГц|mhz|км|km|м|m|Вт|w|мВт|mw|кВт|kw|"
    r"Вт/кг|w/kg|Wh/kg|Вт·ч/кг|%|°C|°c|К|kg|кг|г|g|Мбит/с|mbps|Gbit/s|гбит/с|нм|nm|мкм|µm)", re.I)


def _docs(payload: dict) -> list[dict]:
    return payload.get("documents") or []


def _blob(d: dict) -> str:
    return ((d.get("title") or "") + " " + (d.get("abstract") or "")).lower()


def _hits(text: str, markers: list[str]) -> list[str]:
    return [m for m in markers if m in text]


def parameters(docs: list[dict]) -> list[dict]:
    out = []
    for d in docs:
        for m in NUM_UNIT.finditer((d.get("title") or "") + " " + (d.get("abstract") or "")):
            out.append({"value": m.group(1).replace(",", "."), "unit": m.group(2),
                        "document_id": d["id"], "context": (d.get("abstract") or "")[:120]})
    return out[:40]


def run_agent(agent: str, payload: dict) -> dict:
    docs = _docs(payload)
    fn = globals().get("_agent_" + agent.lower())
    if fn is None:
        return {"note": f"Агент {agent} не имеет детерминированной реализации", "documents": len(docs)}
    res = fn(payload, docs)
    res["_producer"] = "deterministic_extractor"
    res["_simulated"] = True
    return res


# ------------------------------------------------------------------ агенты
def _agent_a01(payload, docs):
    words = Counter()
    for d in docs:
        for w in re.findall(r"[a-zA-Zа-яА-ЯёЁ]{5,}", (d.get("title") or "").lower()):
            words[w] += 1
    terms = [w for w, c in words.most_common(15) if c >= 2]
    return {"terms": terms,
            "branches": [{"name": "Частотные термины корпуса", "expression": " OR ".join(terms[:5])}] if terms else [],
            "exclusions": []}


def _agent_a02(payload, docs):
    findings = []
    for d in docs:
        if d.get("evidence_class") not in ("primary_peer_reviewed", "preprint", "primary_report", "dataset"):
            continue
        b = _blob(d)
        measured = bool(NUM_UNIT.search(b))
        text = f'{d.get("title")}'
        findings.append({
            "claim": text + (" — приведены измеренные значения параметров" if measured else " — описаны результаты исследования"),
            "claim_type": "FACT" if d.get("evidence_class") in ("primary_peer_reviewed", "primary_report", "dataset") else "ANALYSIS",
            "document_ids": [d["id"]],
            "measured_parameters": [p for p in parameters([d])][:5],
        })
    return {"findings": findings[:25]}


def _agent_a03(payload, docs):
    findings = []
    for d in docs:
        if d.get("doc_type") != "patent":
            continue
        findings.append({
            "claim": f'Патентная публикация: {d.get("title")}. Подтверждает раскрытие/заявку; работоспособность изделия патентом не подтверждается.',
            "claim_type": "FACT", "document_ids": [d["id"]],
            "legal_status": "не проверено (требуется INPADOC/национальный реестр)",
        })
    return {"findings": findings[:25]}


def _agent_a04(payload, docs):
    findings = []
    orgs = Counter()
    for d in docs:
        for o in d.get("organizations") or []:
            orgs[o] += 1
        if d.get("evidence_class") in ("press_release", "media"):
            findings.append({
                "claim": f'Заявление организации о разработке: {d.get("title")}',
                "claim_type": "ANALYSIS", "document_ids": [d["id"]],
                "organizations": d.get("organizations") or [],
            })
        if any(k in _blob(d) for k in ("prototype", "прототип", "deployed", "внедрен", "серийн", "production")):
            findings.append({
                "claim": f'Признак промышленной реализации: {d.get("title")}',
                "claim_type": "FACT" if d.get("evidence_class") in ("primary_report", "official_register") else "ANALYSIS",
                "document_ids": [d["id"]], "organizations": d.get("organizations") or [],
            })
    return {"findings": findings[:25], "top_organizations": orgs.most_common(10)}


def _agent_a05(payload, docs):
    by_country: dict[str, list[str]] = {}
    for d in docs:
        c = d.get("country_code")
        if c:
            by_country.setdefault(c, []).append(d["id"])
    return {"countries": [{"iso2": c, "activity": f"{len(ids)} документов в выборке",
                           "document_ids": ids[:8], "programs": []}
                          for c, ids in sorted(by_country.items(), key=lambda kv: -len(kv[1]))]}


def _agent_a06(payload, docs):
    top = docs[:8]
    principle = " ".join((d.get("abstract") or "")[:220] for d in top[:3])
    comps = Counter()
    for d in docs:
        for w in re.findall(r"\b(?:антенн\w*|приёмник\w*|передатчик\w*|усилител\w*|модулятор\w*|фильтр\w*|"
                            r"antenna\w*|receiver\w*|transmitter\w*|amplifier\w*|modulator\w*|filter\w*|"
                            r"electrode\w*|electrolyte\w*|электрод\w*|электролит\w*)\b", _blob(d)):
            comps[w] += 1
    return {"principle": principle[:1200] or "Недостаточно данных для описания принципа действия",
            "components": [c for c, _ in comps.most_common(12)],
            "parameters": parameters(docs)[:20],
            "document_ids": [d["id"] for d in top],
            "open_questions": ["Не подтверждены условия испытаний", "Не найдены независимые протоколы"] if len(docs) < 5 else []}


def _agent_a07(payload, docs):
    signals = []
    for crit, markers in TRL_MARKERS.items():
        matched = [d for d in docs if _hits(_blob(d), markers)]
        # патенты и пресс-релизы не подтверждают уровни 7-9
        strong = [d for d in matched if d.get("evidence_class") in
                  ("primary_peer_reviewed", "primary_report", "dataset", "official_register", "standard")]
        use = strong if crit[1] in "56789" else matched
        signals.append({"criterion_id": crit, "observed": bool(use),
                        "document_ids": [d["id"] for d in use[:5]],
                        "note": ("" if use else "Подтверждающих документов не найдено") +
                                (f"; отброшено слабых свидетельств: {len(matched)-len(use)}" if len(matched) > len(use) else "")})
    return {"signals": signals, "suggested_level": None}


def _agent_a08(payload, docs):
    factors = []
    for code, markers in FACTOR_MARKERS.items():
        matched = [d for d in docs if _hits(_blob(d), markers)]
        strong = [d for d in matched if d.get("evidence_class") in
                  ("primary_peer_reviewed", "primary_report", "dataset", "official_register", "standard", "patent")]
        if not matched:
            assessment, value = "unknown", None
        elif len(strong) >= 3:
            assessment, value = "confirmed", 0.8
        elif strong:
            assessment, value = "partial", 0.55
        else:
            assessment, value = "partial", 0.35
        factors.append({"code": code, "assessment": assessment, "value": value,
                        "document_ids": [d["id"] for d in matched[:6]],
                        "rationale": f"Найдено {len(matched)} документов, из них с приемлемым классом доказательства: {len(strong)}"})
    return {"factors": factors}


def _agent_a09(payload, docs):
    alts = []
    keys = ["alternative", "альтернатив", "вместо", "замен", "comparison", "сравнен", "versus", "по сравнению"]
    for d in docs:
        if _hits(_blob(d), keys):
            alts.append({"name": (d.get("title") or "")[:120], "principle": (d.get("abstract") or "")[:200],
                         "criteria": {"TRL": None, "стоимость": None}, "document_ids": [d["id"]]})
    return {"alternatives": alts[:12]}


def _agent_a10(payload, docs):
    years = sorted(int(d["published_at"][:4]) for d in docs if (d.get("published_at") or "")[:4].isdigit())
    trend = "рост" if len(years) > 4 and years[-1] - years[0] > 0 and len([y for y in years if y >= years[-1] - 3]) > len(years) / 2 else "неопределённо"
    assumptions = [
        {"text": f"Динамика публикаций: {trend}. Экстраполяция ограничена доступной выборкой.", "horizon": "H1",
         "target": "scientific_result", "document_ids": [d["id"] for d in docs[:3]]},
        {"text": "Появление работоспособного прототипа зависит от подтверждения критической функции в релевантной среде.",
         "horizon": "H2", "target": "working_prototype", "document_ids": []},
        {"text": "Промышленное производство требует компонентной базы и нормативной готовности.",
         "horizon": "H3", "target": "industrial_production", "document_ids": []},
        {"text": "На горизонте 20–50 лет допустимы только качественные сценарии и широкие интервалы.",
         "horizon": "H5", "target": "wide_adoption", "document_ids": []},
    ]
    return {"assumptions": assumptions}


def _agent_a11(payload, docs):
    issues = []
    classes = Counter(d.get("evidence_class") for d in docs)
    if not classes.get("primary_peer_reviewed") and not classes.get("primary_report"):
        issues.append({"kind": "gap", "text": "Отсутствуют первичные научные/технические источники", "severity": "high", "document_ids": []})
    if not classes.get("patent"):
        issues.append({"kind": "gap", "text": "Патентная база не подтверждена — правовой ландшафт неизвестен", "severity": "medium", "document_ids": []})
    weak = [d for d in docs if d.get("evidence_class") in ("press_release", "media", "forum")]
    if weak:
        issues.append({"kind": "weak_evidence", "text": f"{len(weak)} документов — пресс-релизы/СМИ/форумы: подтверждают заявления, не характеристики",
                       "severity": "medium", "document_ids": [d["id"] for d in weak[:5]]})
    groups = Counter(d.get("independence_group") for d in docs if d.get("independence_group"))
    dominant = groups.most_common(1)
    if dominant and dominant[0][1] > max(3, len(docs) * 0.5):
        issues.append({"kind": "independence", "text": f"Более половины выборки из одной группы независимости ({dominant[0][0]}) — повторные публикации не считаются независимыми подтверждениями",
                       "severity": "high", "document_ids": []})
    if not any(NUM_UNIT.search(_blob(d)) for d in docs):
        issues.append({"kind": "gap", "text": "Не найдены измеренные численные параметры — оценка параметров невозможна", "severity": "high", "document_ids": []})
    return {"issues": issues, "verdicts": []}


def _agent_a12(payload, docs):
    claims = payload.get("claims") or []
    facts = [c for c in claims if c.get("claim_type") == "FACT"]
    return {"summary": f"Проанализировано документов: {len(docs)}. Подтверждённых фактов: {len(facts)}. "
                       f"Оценки и гипотезы маркированы отдельно.",
            "sections": [{"title": "Доказательная база", "text": f"Фактов: {len(facts)}; всего утверждений: {len(claims)}",
                          "claim_ids": [c.get("id") for c in claims[:10] if c.get("id")]}],
            "limitations": ["Выборка ограничена доступными открытыми источниками и квотами",
                            "Калибровка методик не завершена"]}
