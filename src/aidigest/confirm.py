"""Подтверждение показателей кейса вторым независимым источником."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from aidigest.llm import LLMClient, LLMFormatError
from aidigest.models import Case, ConfirmationStatus
from aidigest.models import Article
from aidigest.quotes import extract_numbers, normalize_text, quote_in_text
from aidigest.registry import SourceRegistry
from aidigest.search import SearchClient
from aidigest.urls import domain_of, normalize_url

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


def _metric_numbers(metric) -> list[float]:
    return [n for part in (metric.before, metric.after, metric.change) for n in extract_numbers(part)]


def _all_in(wanted: list[float], have: list[float]) -> bool:
    """Непустой набор чисел, каждое из которых есть в have."""
    return bool(wanted) and all(any(abs(w - h) <= 1e-6 for h in have) for w in wanted)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")
# Общие слова в названиях мест и ведомств — по ним «место кейса» не узнать.
_GENERIC_PLACE = {"облас", "респу", "город", "район", "прави", "минис", "админ", "федер", "управ", "госуд",
                  "росси", "нацио", "центр", "компа", "групп", "служб", "депар", "комит", "уровн"}


def _stems(text: str | None, min_len: int = 5) -> set[str]:
    return {w[:5] for w in re.findall(r"[^\W\d_]+", normalize_text(text or "")) if len(w) >= min_len}


def _place_stems(case: Case) -> set[str]:
    """Место кейса: регион и город, а из названия организации — только имена собственные
    (с заглавной буквы, латиница, аббревиатуры). Обычные слова («информационный центр») — не место."""
    stems = _stems(case.region) | _stems(case.municipality)
    for token in re.findall(r"[^\W\d_][\w-]*", case.organization or ""):
        proper = token[0].isupper() or token[0].isascii()
        if proper and (len(token) >= 4 or (token.isupper() and len(token) >= 3)):
            stems.add(normalize_text(token)[:5])
    return stems - _GENERIC_PLACE


def _unit_kind(text: str) -> str:
    s = normalize_text(text)
    return "%" if ("%" in s or "процент" in s or "п.п" in s) else "abs"


def _distinctive(numbers: list[float]) -> bool:
    """Хотя бы одно число не из мелких (0–10): «5 минут» встречается где угодно."""
    return any(not (n.is_integer() and n <= 10) for n in numbers)


def find_number_confirmations(case: Case, articles: list[Article]) -> list[tuple[int, str, str]]:
    """Подтверждения без LLM: в статье другого издания есть предложение со всеми числами проверенного
    показателя (хотя бы одно не мелкое) и словом из его названия, а сама статья упоминает место кейса.

    Возвращает (индекс показателя, URL, предложение)."""
    place = _place_stems(case)
    if not place:
        return []
    out = []
    for article in articles:
        if not (place & _stems(article.text, min_len=3)):
            continue
        sentences = _SENTENCE_SPLIT.split(article.text)
        for i, metric in enumerate(case.metrics):
            wanted = _metric_numbers(metric)
            name = _stems(metric.name)
            if not metric.quote_verified or not wanted or not _distinctive(wanted) or not name:
                continue
            for sentence in sentences:
                have = extract_numbers(sentence)
                if _all_in(wanted, have) and name & _stems(sentence):
                    out.append((i, normalize_url(article.url), sentence.strip()))
                    break
    return out


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
    own = {domain_of(s.url) for s in case.sources} | {domain_of(m.source_url) for m in case.metrics}
    # Повторная попытка ищет только материалы, вышедшие после прошлой (и не берёт старый ответ из кеша).
    since = case.last_confirmation_attempt if case.confirmation_attempts > 0 else None
    # BudgetExceeded пробрасывается до любых изменений кейса.
    found = search.search(confirmation_query(case), pool="confirm", exclude_domains=sorted(own),
                          start_date=since, max_results=max_results)
    case.confirmation_attempts += 1
    case.last_confirmation_attempt = today
    # Независимость источника проверяем сами, не полагаясь на exclude_domains поисковика.
    articles = [a for a in found if domain_of(a.url) not in own]
    if not articles:
        case.recompute_status()
        return

    by_url = {normalize_url(a.url): a for a in articles}
    user = _case_for_prompt(case) + "\n\nСтатьи:\n" + "\n\n".join(
        f"URL: {u}\n{a.text[:ARTICLE_CHARS]}" for u, a in by_url.items())
    try:
        reply = llm.complete_json(CONFIRM_SYSTEM_PROMPT, user)
    except LLMFormatError:
        reply = {"matches": []}  # проверка по числам ниже всё равно отработает
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
        quote = str(m.get("quote") or "")
        if not quote_in_text(quote, article.text):
            continue  # совпадение без настоящей цитаты не принимаем
        metric = case.metrics[idx]
        if not metric.quote_verified:
            continue  # непроверенную цифру нельзя «подтвердить»
        if m.get("agrees") is True:
            # В цитате второго источника должны стоять те же числа, что у показателя.
            if not _all_in(_metric_numbers(metric), extract_numbers(quote)):
                continue
            if url not in metric.confirmed_by:
                metric.confirmed_by.append(url)
        else:
            value = str(m.get("value") or "")
            if not _all_in(extract_numbers(value), extract_numbers(quote)):
                continue
            mine = " ".join(filter(None, (metric.before, metric.after, metric.change)))
            if _unit_kind(value) != _unit_kind(mine):
                continue  # «74 региона» против «70%» — разные показатели, а не противоречие
            metric.conflicting_values.append(f"{value} ({url})")
        if url not in known:
            case.sources.append(registry.to_source(article))
            known.add(url)
    # Детерминированные совпадения по числам — дополнение к осторожному LLM.
    for i, url, _sentence in find_number_confirmations(case, articles):
        metric = case.metrics[i]
        if url not in metric.confirmed_by:
            metric.confirmed_by.append(url)
        if url not in known:
            case.sources.append(registry.to_source(by_url[url]))
            known.add(url)
    case.recompute_status()
