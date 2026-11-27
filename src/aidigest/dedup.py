"""Поиск дубля кейса в базе и слияние записей.

Сравнение спрятано в find_duplicate — позже его можно заменить эмбеддингами FRIDA.
"""
from __future__ import annotations

import json
import re
from datetime import date

from aidigest.llm import LLMClient
from aidigest.models import Case, Level
from aidigest.publication import case_update, merge_source
from aidigest.quotes import extract_numbers, normalize_text
from aidigest.urls import domain_of, normalize_url

DEDUP_SYSTEM_PROMPT = """Ты сравниваешь кейсы внедрения ИИ. Дан новый кейс (id "new") и кандидаты из базы.
Определи, описывает ли какой-то кандидат ТОТ ЖЕ проект (та же организация/регион и та же система),
а не просто похожий проект. Ответ — только JSON: {"duplicate_id": "<id кандидата>"} или {"duplicate_id": null}."""

_REGION_STOP = {"область", "обл", "край", "республика", "респ", "город", "г", "автономный", "округ", "ао"}


def _region_key(case: Case) -> str:
    if case.level == Level.SVERDLOVSK:
        return "sverdlovsk"
    raw = case.region or case.country
    tokens = [t for t in re.findall(r"\w+", normalize_text(raw)) if t not in _REGION_STOP]
    return tokens[0][:6] if tokens else normalize_text(raw)


def _words(case: Case) -> set[str]:
    text = " ".join(p for p in (case.organization, case.ai_technology, case.title) if p)
    return {w[:6] for w in re.findall(r"\w+", normalize_text(text)) if len(w) >= 4}


def _brief(case: Case, cid: str) -> dict:
    return {"id": cid, "region": case.region or case.country, "organization": case.organization,
            "ai_technology": case.ai_technology, "title": case.title, "summary": case.summary}


def find_duplicate(case: Case, existing: list[Case], llm: LLMClient, max_candidates: int = 5) -> Case | None:
    key = _region_key(case)
    pool = [c for c in existing if c.level == case.level and _region_key(c) == key]
    if not pool:
        return None
    words = _words(case)
    pool.sort(key=lambda c: len(words & _words(c)), reverse=True)
    candidates = pool[:max_candidates]
    user = json.dumps({"new": _brief(case, "new"), "candidates": [_brief(c, c.id) for c in candidates]},
                      ensure_ascii=False, indent=1)
    reply = llm.complete_json(DEDUP_SYSTEM_PROMPT, user)
    dup_id = reply.get("duplicate_id") if isinstance(reply, dict) else None
    return next((c for c in candidates if c.id == dup_id), None)


def _numbers(m) -> tuple[float, ...]:
    return tuple(sorted(round(n, 6) for part in (m.before, m.after, m.change) for n in extract_numbers(part)))


def merge_into(target: Case, new: Case, today: date) -> None:
    with case_update(target, today):
        for source in new.sources:
            merge_source(target, source)

        for evidence in new.qualitative_evidence:
            if evidence not in target.qualitative_evidence:
                target.qualitative_evidence.append(evidence)

        for nm in new.metrics:
            same = next((tm for tm in target.metrics
                         if tm.criterion == nm.criterion and _numbers(tm) == _numbers(nm) and _numbers(nm)), None)
            if same is None:
                target.metrics.append(nm)
                continue
            seen_domains = {domain_of(same.source_url)} | {domain_of(u) for u in same.confirmed_by}
            if domain_of(nm.source_url) not in seen_domains and nm.quote_verified:
                same.confirmed_by.append(nm.source_url)

        stages = list(type(target.stage))
        if stages.index(new.stage) > stages.index(target.stage):
            target.stage = new.stage
        target.recompute_status()
