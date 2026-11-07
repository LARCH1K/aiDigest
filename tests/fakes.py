"""Фейки внешних сервисов для тестов (без сети)."""
from types import SimpleNamespace
from typing import Any, Callable


class FakeLLM:
    """complete_json отдаёт заранее заданные ответы или результат функции route(system, user)."""

    def __init__(self, replies: list[Any] | Callable[[str, str], Any]):
        self._replies = replies
        self.calls = 0
        self.log: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> Any:
        self.calls += 1
        self.log.append((system, user))
        if callable(self._replies):
            return self._replies(system, user)
        return self._replies.pop(0)


class FakeOpenAI:
    """Имитирует openai.OpenAI: client.chat.completions.create(...).choices[0].message.content."""

    def __init__(self, texts: list[str]):
        self._texts = list(texts)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        text = self._texts.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class FakeSearch:
    """SearchClient для тестов: results — dict {запрос: статьи} или функция(**kw) -> статьи."""

    def __init__(self, results, cost: float = 1, budget=None):
        self._results = results
        self.cost = cost
        self.budget = budget
        self.calls: list[dict] = []

    def search(self, query, *, pool, include_domains=None, exclude_domains=None, start_date=None, max_results=5):
        kw = dict(query=query, pool=pool, include_domains=include_domains, exclude_domains=exclude_domains,
                  start_date=start_date, max_results=max_results)
        if self.budget is not None:
            self.budget.spend(pool, self.cost)
        self.calls.append(kw)
        if callable(self._results):
            return list(self._results(**kw))
        return list(self._results.get(query, []))
