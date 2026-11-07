"""Дисковый кеш ответов внешних сервисов (Tavily, LLM, HTTP)."""
import hashlib
import json
import os
from pathlib import Path
from typing import Any


class DiskCache:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, namespace: str, key: Any) -> Path:
        raw = json.dumps(key, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return self.root / namespace / f"{digest}.json"

    def get(self, namespace: str, key: Any) -> Any | None:
        p = self._path(namespace, key)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    def put(self, namespace: str, key: Any, value: Any) -> None:
        p = self._path(namespace, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)
