"""Подтверждение показателей кейса вторым независимым источником."""
from __future__ import annotations

import json
from datetime import date, timedelta

from aidigest.llm import LLMClient
from aidigest.models import Case, ConfirmationStatus
from aidigest.quotes import quote_in_text
from aidigest.registry import SourceRegistry
from aidigest.search import SearchClient
from aidigest.urls import normalize_url

ARTICLE_CHARS = 4000

CONFIRM_SYSTEM_PROMPT = """Ты проверяешь показатели кейса внедрения ИИ по другим источникам.
Тебе дают кейс с пронумерованными показателями (metric_index) и несколько статей с их URL.
Для каждого показателя найди, упоминается ли ТОТ ЖЕ показатель ТОГО ЖЕ кейса в какой-либо статье.
- Если число в статье совпадает по смыслу (то же значение или эквивалентная запись) — agrees: true.
- Если статья называет ДРУГОЕ значение того же показателя — agrees: false, value — значение из статьи.
- Если статья про другой проект или показатель не упоминается — ничего не пиши.
quote — ДОСЛОВНАЯ цитата из статьи с этим числом, символ в символ.
Ответ — только JSON:
{"matches": [{"metric_index": 0, "url": "", "value": "", "agrees": true, "quote": ""}]}
Если совпадений нет — {"matches": []}."""


def _due_for_recheck(c: Case, today: date, recheck_after_days: int, max_rechecks: int) -> bool:
    return (c.confirmation_status == ConfirmationStatus.SINGLE
            and 1 <= c.confirmation_attempts <= max_rechecks
            and c.last_confirmation_attempt is not None
            and today - c.last_confirmation_attempt >= timedelta(days=recheck_after_days))


def plan_confirmation_queue(cases: list[Case], new_ids: set[str], today: date,
                            recheck_after_days: int, max_rechecks: int) -> list[Case]:
    pending = [c for c in cases if c.metrics and c.confirmation_status == ConfirmationStatus.SINGLE]
    new = [c for c in pending if c.id in new_ids and c.confirmation_attempts == 0]
    deferred = [c for c in pending if c.id not in new_ids and c.confirmation_attempts == 0]
    recheck = [c for c in pending if _due_for_recheck(c, today, recheck_after_days, max_rechecks)]
    return new + deferred + recheck


def confirmation_query(case: Case) -> str:
    parts = [case.region or case.country, case.organization, case.ai_technology, case.title]
    return " ".join(p for p in parts if p)


def _case_for_prompt(case: Case) -> str:
    metrics = [{"metric_index": i, "name": m.name, "before": m.before, "after": m.after,
                "change": m.change, "unit": m.unit} for i, m in enumerate(case.metrics)]
    head = {"title": case.title, "region": case.region or case.country, "organization": case.organization,
            "ai_technology": case.ai_technology, "summary": case.summary}
    return json.dumps({"case": head, "metrics": metrics}, ensure_ascii=False, indent=1)


def confirm_case(case: Case, search: SearchClient, llm: LLMClient, registry: SourceRegistry,
                 today: date, max_results: int) -> None:
    exclude = sorted({s.domain for s in case.sources})
    # BudgetExceeded пробрасывается до любых изменений кейса.
    articles = search.search(confirmation_query(case), pool="confirm", exclude_domains=exclude,
                             max_results=max_results)
    case.confirmation_attempts += 1
    case.last_confirmation_attempt = today
    if not articles:
        case.recompute_status()
        return

    by_url = {normalize_url(a.url): a for a in articles}
    user = _case_for_prompt(case) + "\n\nСтатьи:\n" + "\n\n".join(
        f"URL: {u}\n{a.text[:ARTICLE_CHARS]}" for u, a in by_url.items())
    reply = llm.complete_json(CONFIRM_SYSTEM_PROMPT, user)
    matches = reply.get("matches", []) if isinstance(reply, dict) else []

    known = {normalize_url(s.url) for s in case.sources}
    for m in matches:
        if not isinstance(m, dict):
            continue
        url = normalize_url(str(m.get("url") or ""))
        idx = m.get("metric_index")
        article = by_url.get(url)
        if article is None or not isinstance(idx, int) or not 0 <= idx < len(case.metrics):
            continue
        if not quote_in_text(str(m.get("quote") or ""), article.text):
            continue  # совпадение без настоящей цитаты не принимаем
        metric = case.metrics[idx]
        if m.get("agrees") is True:
            if url not in metric.confirmed_by:
                metric.confirmed_by.append(url)
        else:
            metric.conflicting_values.append(f"{m.get('value')} ({url})")
        if url not in known:
            case.sources.append(registry.to_source(article))
            known.add(url)
    case.recompute_status()
