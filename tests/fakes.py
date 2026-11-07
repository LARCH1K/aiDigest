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
