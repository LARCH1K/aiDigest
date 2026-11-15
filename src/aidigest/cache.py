"""Дисковый кеш ответов внешних сервисов (Tavily, LLM, HTTP)."""
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

REPLACE_ATTEMPTS = 10


def replace_with_retry(src: Path, dst: Path) -> None:
    """os.replace с повторами: в Windows файл может на мгновение держать IDE, индексатор или антивирус."""
    for attempt in range(1, REPLACE_ATTEMPTS + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == REPLACE_ATTEMPTS:
                raise
            time.sleep(0.2 * attempt)


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
        replace_with_retry(tmp, p)
