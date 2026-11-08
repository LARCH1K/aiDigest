"""Регулярный цикл: сбор → извлечение → дедупликация → подтверждение → сохранение."""
from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from aidigest.budget import BudgetExceeded, CreditBudget
from aidigest.config import QuerySpec, Settings
from aidigest.confirm import confirm_case, plan_confirmation_queue
from aidigest.dedup import find_duplicate, merge_into
from aidigest.extract import extract_cases
from aidigest.llm import LLMClient, LLMFormatError, OfflineCacheMiss
from aidigest.models import Level
from aidigest.registry import SourceRegistry
from aidigest.search import SearchClient
from aidigest.store import CaseStore
from aidigest.urls import normalize_url


@dataclass
class RunReport:
    credits_spent: float = 0
    llm_calls: int = 0
    articles_processed: int = 0
    articles_rejected: int = 0
    articles_failed: int = 0
    candidates_rejected: int = 0
    cases_new: int = 0
    cases_updated: int = 0
    confirmations_done: int = 0
    confirmations_deferred: int = 0
    budget_exhausted: bool = False
    flags: dict[str, int] = field(default_factory=dict)
    # Для failure_reason — в отчёт (as_rows) не выводятся.
    searches_ok: int = 0
    searches_failed: int = 0
    last_search_error: BaseException | None = None
    last_llm_error: BaseException | None = None

    def as_rows(self) -> dict[str, Any]:
        rows = {
            "Кредитов Tavily потрачено": self.credits_spent,
            "Вызовов LLM": self.llm_calls,
            "Статей обработано": self.articles_processed,
            "Статей отсеяно (не кейс)": self.articles_rejected,
            "Статей с ошибкой LLM (повтор в след. раз)": self.articles_failed,
            "Кандидатов отсеяно (не конкретное внедрение)": self.candidates_rejected,
            "Кейсов новых": self.cases_new,
            "Кейсов обновлено": self.cases_updated,
            "Подтверждений проведено": self.confirmations_done,
            "Подтверждений отложено": self.confirmations_deferred,
            "Бюджет исчерпан": "да" if self.budget_exhausted else "нет",
        }
        rows.update({f"Флаг: {k}": v for k, v in sorted(self.flags.items())})
        return rows


@dataclass
class Deps:
    search: SearchClient
    llm: LLMClient
    registry: SourceRegistry
    store: CaseStore
    queries: list[QuerySpec]
    settings: Settings
    budget: CreditBudget


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def run_cycle(deps: Deps, levels: set[Level], today: date) -> RunReport:
    s, report = deps.settings, RunReport()
    data = deps.store.load()
    new_ids: set[str] = set()
    seen_now: set[str] = set()
    start = today - timedelta(days=s.freshness_days)

    queries = [q for q in deps.queries if q.level in levels]
    for qi, q in enumerate(queries, 1):
        domains = deps.registry.domains_for(q.level) if q.use_registry_domains else None
        try:
            articles = deps.search.search(q.text, pool="collect", include_domains=domains,
                                          start_date=start, max_results=s.max_results)
        except BudgetExceeded:
            report.budget_exhausted = True
            _log("Бюджет сбора исчерпан — дальше обрабатываю уже найденное.")
            break
        except Exception as e:  # сеть, API — переходим к следующему запросу
            report.searches_failed += 1
            report.last_search_error = e
            _log(f"Ошибка поиска «{q.text}»: {e}")
            continue
        report.searches_ok += 1

        fresh = [a for a in articles
                 if normalize_url(a.url) not in data.processed_urls and normalize_url(a.url) not in seen_now]
        _log(f"Поиск {qi}/{len(queries)} [{q.level.value}]: «{q.text}» — статей: {len(articles)}, новых: {len(fresh)}")
        for ai, article in enumerate(fresh, 1):
            url = normalize_url(article.url)
            if url in seen_now:
                continue
            seen_now.add(url)
            _log(f"  Статья {ai}/{len(fresh)}: {article.title[:90] or url}")
            rejected: list[str] = []
            try:
                cases = extract_cases(article, deps.llm, deps.registry, today, s.article_max_chars,
                                      rejected=rejected)
            except Exception as e:  # битый ответ, нет в кеше, сеть/API LLM — статья повторится в след. раз
                report.articles_failed += 1
                if not isinstance(e, OfflineCacheMiss):  # офлайн-промах кеша — не сбой LiteLLM
                    report.last_llm_error = e
                _log(f"Статья пропущена ({url}): {type(e).__name__}: {e}")
                continue
            report.articles_processed += 1
            report.candidates_rejected += len(rejected)
            for reason in rejected:
                _log(f"Отсеян кандидат ({url}): {reason}")
            if not cases:
                report.articles_rejected += 1
            for case in cases:
                try:
                    dup = find_duplicate(case, data.cases, deps.llm)
                except Exception as e:
                    _log(f"Дедупликация не удалась ({url}): {type(e).__name__}: {e}")
                    dup = None
                if dup is not None:
                    merge_into(dup, case, today)
                    report.cases_updated += 1
                else:
                    data.cases.append(case)
                    new_ids.add(case.id)
                    report.cases_new += 1
            data.processed_urls.add(url)
            deps.store.save(data)

    deps.budget.close_collection()
    queue = plan_confirmation_queue(data.cases, new_ids, today, s.recheck_after_days, s.max_rechecks)
    _log(f"Подтверждение: кейсов в очереди {len(queue)}")
    for i, case in enumerate(queue):
        _log(f"  Подтверждение {i + 1}/{len(queue)}: {case.title[:90]}")
        try:
            confirm_case(case, deps.search, deps.llm, deps.registry, today, s.confirm_max_results)
            report.confirmations_done += 1
        except BudgetExceeded:
            report.budget_exhausted = True
            report.confirmations_deferred = len(queue) - i
            break
        except (LLMFormatError, OfflineCacheMiss) as e:
            _log(f"Подтверждение не удалось ({case.title}): {e}")
        except Exception as e:
            _log(f"Ошибка поиска подтверждения ({case.title}): {e}")

    deps.store.save(data)
    report.credits_spent = deps.budget.spent
    report.llm_calls = getattr(deps.llm, "calls", 0)
    report.flags = dict(Counter(str(f) for c in data.cases for f in c.flags))
    return report
