"""Клиент LLM через LiteLLM Proxy (OpenAI-совместимый API) с дисковым кешем."""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Protocol

from aidigest.cache import DiskCache

RETRY_HINT = "Ответ должен быть только корректным JSON без пояснений."
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class LLMFormatError(Exception):
    pass


class OfflineCacheMiss(Exception):
    pass


class LLMClient(Protocol):
    calls: int

    def complete_json(self, system: str, user: str,
                      validate: Callable[[Any], Any] | None = None) -> Any: ...


def parse_json_reply(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for block in _FENCE_RE.findall(text):
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            continue
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                value, _ = decoder.raw_decode(text, i)
                return value
            except json.JSONDecodeError:
                continue
    raise ValueError("в ответе нет корректного JSON")


class LiteLLMClient:
    def __init__(self, api_key: str | None, base_url: str | None, model: str, cache: DiskCache,
                 offline: bool = False, client: Any = None):
        self.model = model
        self.cache = cache
        self.offline = offline
        self.calls = 0
        if client is None and not offline:
            import openai
            client = openai.OpenAI(api_key=api_key, base_url=base_url)
        self._client = client

    def _ask(self, messages: list[dict]) -> str:
        self.calls += 1
        resp = self._client.chat.completions.create(model=self.model, messages=messages, temperature=0)
        return resp.choices[0].message.content or ""

    def complete_json(self, system: str, user: str,
                      validate: Callable[[Any], Any] | None = None) -> Any:
        """validate(value) возвращает нормализованное значение или бросает ValueError.

        Невалидный ответ (не JSON или не та структура) переспрашивается один раз и никогда не кешируется.
        """
        check = validate or (lambda v: v)
        key = {"model": self.model, "system": system, "user": user}
        cached = self.cache.get("llm", key)
        if cached is not None:
            try:
                return check(cached)
            except ValueError:
                pass  # старый ответ из кеша не проходит проверку — спросим заново
        if self.offline:
            raise OfflineCacheMiss("нет ответа в кеше, а запуск офлайн")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        reply = self._ask(messages)
        try:
            raw = parse_json_reply(reply)
            value = check(raw)
        except ValueError:
            messages += [{"role": "assistant", "content": reply}, {"role": "user", "content": RETRY_HINT}]
            try:
                raw = parse_json_reply(self._ask(messages))
                value = check(raw)
            except ValueError as e:
                raise LLMFormatError(str(e)) from e
        self.cache.put("llm", key, raw)
        return value
