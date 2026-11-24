"""TRL Engine (ТЗ-03 §4, ИД-08 ведомости v1.1).

Итоговый TRL — МАКСИМАЛЬНЫЙ уровень, для которого выполнены все обязательные
критерии и имеются достаточные доказательства. Усреднение уровней запрещено.
Отсутствие подтверждения = «не подтверждено», а не 0 и не отрицательный факт.

Критерии имеют стабильные идентификаторы TRL<n>-C<nn> и связаны с доказательствами
через analytics_trl_criterion_evidence. Расчёт воспроизводим: сохраняются версия
методики, входной снимок, контрольные суммы и пробелы.
"""
from __future__ import annotations

from collections import defaultdict

from ..contracts import CoreError, iso_now, new_id
from ..storage import db
from ..workflow import events
from . import methodologies as M
from . import snapshot as SNAP

STRONG_CLASSES = {"primary_peer_reviewed", "primary_report", "dataset", "official_register", "standard"}
WEAK_CLASSES = {"patent", "preprint", "press_release", "media", "forum", "unknown"}


def legacy_to_canonical() -> dict[str, str]:
    rows = db.query("SELECT criterion_code, legacy_code FROM analytics_trl_criteria WHERE legacy_code IS NOT NULL")
    if not rows:
        M.bootstrap()
        rows = db.query("SELECT criterion_code, legacy_code FROM analytics_trl_criteria WHERE legacy_code IS NOT NULL")
    return {r["legacy_code"]: r["criterion_code"] for r in rows}


def validate_no_averaging(payload: dict) -> None:
    """TRL-02: попытка присвоить уровень усреднением отклоняется валидатором."""
    method = str(payload.get("method") or payload.get("aggregation") or "").lower()
    if any(k in method for k in ("mean", "average", "avg", "средн", "усредн")):
        raise CoreError("E_VALIDATION", "Усреднение уровней TRL запрещено (ТЗ-03 §4, ИД-08)",
                        stage="trl_validation", method=method)
    if payload.get("averaged_levels") or payload.get("level_votes"):
        raise CoreError("E_VALIDATION", "Голосование моделей не определяет уровень TRL (ИД-08)",
                        stage="trl_validation")
    if payload.get("trl") is not None and not payload.get("criteria"):
        raise CoreError("E_VALIDATION", "Уровень TRL без проверки обязательных критериев не принимается",
                        stage="trl_validation")


def _document_index(research_id: str) -> dict[str, dict]:
    out = {}
    for r in db.query("SELECT * FROM research_documents WHERE research_id=?", (research_id,)):
        out[r["id"]] = db.dec(r, "identifiers", "organizations")
    return out


def collect_signals(research_id: str, docs: dict) -> dict[str, dict]:
    """Признаки по критериям: из агента A07 либо из детерминированного экстрактора."""
    from ..ai import agents as A
    from ..ai.simulation import TRL_MARKERS, _blob, _hits
    mapping = legacy_to_canonical()
    sig = A.signals(research_id, "A07")
    result: dict[str, dict] = {}
    if sig and sig.get("signals"):
        if sig.get("suggested_level") is not None and not sig.get("criteria_checked"):
            # предварительная оценка агента не заменяет проверку критериев
            pass
        for s in sig["signals"]:
            ids = [d for d in (s.get("document_ids") or []) if d in docs]
            code = mapping.get(s["criterion_id"], s["criterion_id"])
            result[code] = {"observed": bool(s.get("observed")), "document_ids": ids,
                            "producer": "agent:A07", "note": s.get("note", "")}
        return result
    for crit, markers in TRL_MARKERS.items():
        code = mapping.get(crit, crit)
        matched = [d for did, d in docs.items()
                   if d.get("relevance_class") in ("DIRECT", "ADJACENT") and _hits(_blob(d), markers)]
        strong = [d for d in matched if d["evidence_class"] in STRONG_CLASSES]
        use = strong if code.startswith(("TRL5", "TRL6", "TRL7", "TRL8", "TRL9")) else matched
        result[code] = {"observed": bool(use), "document_ids": [d["id"] for d in use[:5]],
                        "producer": "deterministic_extractor",
                        "note": "" if use else "Подтверждающих документов не найдено"}
    return result


def compute(research_id: str, technology_id: str | None = None, *,
            signals: dict | None = None, methodology_id: str | None = None,
            store: bool = True, assessed_by: str = "calculation_core") -> dict:
    m = M.by_id(methodology_id) if methodology_id else M.active("TRL_CRITERIA")
    trl_cfg = m["parameters"]
    docs = _document_index(research_id)
    signals = signals if signals is not None else collect_signals(research_id, docs)
    mapping = legacy_to_canonical()
    signals = {mapping.get(k, k): v for k, v in (signals or {}).items()}

    criteria_out, gaps, criterion_evidence = [], [], []
    achieved = 0
    chain_ok = True            # ИД-08: уровень достижим только при непрерывной цепочке
    blocked_from = None
    for level in trl_cfg["levels"]:
        lvl = level["level"]
        level_ok = True
        level_groups: set[str] = set()
        level_evidence = 0
        for crit in level["criteria"]:
            code = crit.get("criterion_code") or crit["id"]
            s = signals.get(code, {"observed": False, "document_ids": [], "note": "нет данных"})
            allowed = set(crit.get("evidence_classes") or [])
            valid_docs, weak_docs = [], []
            for did in s.get("document_ids", []):
                d = docs.get(did)
                if not d:
                    continue
                if (d.get("identifiers") or {}).get("simulated"):
                    weak_docs.append(did)
                    continue
                if allowed and d["evidence_class"] not in allowed:
                    weak_docs.append(did)
                    continue
                valid_docs.append(did)
                level_groups.add(d["independence_group"] or "unknown")
            confirmed = bool(s.get("observed")) and len(valid_docs) >= trl_cfg["min_evidence_per_level"]
            mandatory = bool(crit.get("is_mandatory", crit.get("required", True)))
            if mandatory and not confirmed:
                level_ok = False
                gaps.append({"level": lvl, "criterion_code": code, "criterion_id": code,
                             "text": crit["text"],
                             "reason": "не подтверждено достаточными доказательствами",
                             "weak_documents": weak_docs[:5]})
            _groups = len({docs[d]["independence_group"] for d in valid_docs if d in docs})
            conf = round(min(0.95, 0.35 + 0.12 * min(len(valid_docs), 3) + 0.10 * min(_groups, 2)), 4) if confirmed else None
            criteria_out.append({
                "level": lvl, "criterion_code": code, "criterion_id": code, "text": crit["text"],
                "is_mandatory": mandatory, "required": mandatory, "confirmed": confirmed,
                "document_ids": valid_docs[:6], "rejected_document_ids": weak_docs[:6],
                "evidence_classes": sorted({docs[d]["evidence_class"] for d in valid_docs if d in docs}),
                "gap": "" if confirmed else "не подтверждено",
                "confidence": conf, "producer": s.get("producer"),
            })
            for did in valid_docs[:6]:
                criterion_evidence.append({"criterion_code": code, "document_id": did, "confirmed": 1,
                                           "independence_group_id": docs[did].get("independence_group"),
                                           "note": ""})
            if not confirmed:
                criterion_evidence.append({"criterion_code": code, "document_id": None, "confirmed": 0,
                                           "independence_group_id": None,
                                           "note": s.get("note") or "не подтверждено"})
            level_evidence += len(valid_docs)
        need_groups = trl_cfg["min_independent_groups"].get(str(lvl), 1)
        if level_ok and level_evidence >= trl_cfg["min_evidence_per_level"] and len(level_groups) >= need_groups:
            if chain_ok:
                achieved = lvl
        elif level_ok and len(level_groups) < need_groups:
            gaps.append({"level": lvl, "criterion_code": "INDEP", "criterion_id": "INDEP",
                         "text": f"Требуется независимых групп: {need_groups}",
                         "reason": f"Найдено групп независимости: {len(level_groups)}", "weak_documents": []})
            level_ok = False
        if not level_ok:
            # Пробел на уровне блокирует все последующие уровни: TRL — не максимум
            # отдельных подтверждений, а непрерывная цепочка обязательных критериев.
            if chain_ok:
                chain_ok = False
                blocked_from = lvl
            continue
        if not chain_ok:
            for c in criteria_out:
                if c["level"] == lvl:
                    c["blocked_by_level"] = blocked_from
                    c["gap"] = (c["gap"] + "; " if c["gap"] else "") + \
                        f"уровень не достигнут: пробел обязательных критериев на TRL{blocked_from}"

    confidence = None
    if achieved:
        confs = [c["confidence"] for c in criteria_out if c["level"] <= achieved and c["confirmed"] and c["confidence"]]
        confidence = round(sum(confs) / len(confs), 4) if confs else None
    inputs = {"research_id": research_id, "signals": signals}
    params = {"min_evidence_per_level": trl_cfg["min_evidence_per_level"],
              "min_independent_groups": trl_cfg["min_independent_groups"],
              "aggregation": "max_level_with_mandatory_criteria"}
    snap = SNAP.capture(research_id, m, inputs, params, assessed_by=assessed_by)
    result = {"trl": achieved or 1, "criteria": criteria_out, "gaps": gaps, "confidence": confidence,
              "methodology_id": m["id"], "methodology_code": m["code"],
              "methodology_version": snap["methodology_version"], "input_hash": snap["input_hash"],
              "chain_blocked_from": blocked_from,
              "note": "TRL = максимальный уровень с выполненными обязательными критериями; усреднение не применялось"}
    result["output_hash"] = SNAP.output_hash({"trl": result["trl"], "confidence": confidence})
    rec_id = new_id("trl-")
    if store:
        db.insert("analytics_trl", {
            "id": rec_id, "research_id": research_id, "technology_id": technology_id,
            "trl": achieved or 1, "criteria": criteria_out, "gaps": gaps, "confidence": confidence,
            "output_hash": result["output_hash"],
            **{k: snap[k] for k in ("methodology_id", "methodology_version", "input_hash",
                                    "document_set_version", "model_id", "model_version",
                                    "prompt_version", "input_snapshot", "parameters",
                                    "config_checksum", "assessed_by")},
            "created_at": iso_now()})
        for ce in criterion_evidence:
            db.insert("analytics_trl_criterion_evidence", {
                "id": new_id("tce-"), "assessment_id": rec_id, **ce, "created_at": iso_now()})
        if technology_id:
            db.update("knowledge_technologies", "id", technology_id, {"trl": achieved or 1, "updated_at": iso_now()})
        events.emit("analytics.trl", research_id=research_id,
                    payload={"trl": achieved or 1, "gaps": len(gaps), "confidence": confidence,
                             "averaging_used": False})
    return {"id": rec_id if store else None, **result}


def latest(research_id: str) -> dict | None:
    row = db.one("SELECT * FROM analytics_trl WHERE research_id=? ORDER BY created_at DESC LIMIT 1", (research_id,))
    return db.dec(row, "criteria", "gaps", "input_snapshot", "parameters")


def history(research_id: str) -> list[dict]:
    return db.query("""SELECT id, trl, confidence, methodology_version, input_hash, output_hash, created_at
                       FROM analytics_trl WHERE research_id=? ORDER BY created_at""", (research_id,))


def criteria_catalog() -> list[dict]:
    return [db.dec(r, "evidence_classes") for r in
            db.query("SELECT * FROM analytics_trl_criteria ORDER BY trl_level, criterion_code")]


def criterion_evidence(assessment_id: str) -> list[dict]:
    return db.query("""SELECT * FROM analytics_trl_criterion_evidence
                       WHERE assessment_id=? ORDER BY criterion_code""", (assessment_id,))


def validation_metrics(pairs: list[tuple[int, int]]) -> dict:
    """MAE по уровням, доля точных совпадений, weighted kappa (ТЗ-03 §8)."""
    if not pairs:
        return {"mae": None, "exact_share": None, "weighted_kappa": None, "n": 0,
                "calibrated": False, "status": "калибровка не завершена"}
    n = len(pairs)
    mae = sum(abs(a - b) for a, b in pairs) / n
    exact = sum(1 for a, b in pairs if a == b) / n
    k = 9
    obs = [[0] * k for _ in range(k)]
    for a, b in pairs:
        obs[a - 1][b - 1] += 1
    ra = [sum(r) for r in obs]
    ca = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = abs(i - j) / (k - 1)
            exp = ra[i] * ca[j] / n
            num += w * obs[i][j]
            den += w * exp
    kappa = 1 - num / den if den else None
    return {"mae": round(mae, 3), "exact_share": round(exact, 3),
            "weighted_kappa": round(kappa, 3) if kappa is not None else None, "n": n,
            "calibrated": n >= 30, "status": "калибровка не завершена" if n < 30 else "выборка достаточна"}
