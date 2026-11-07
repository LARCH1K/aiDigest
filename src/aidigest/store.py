"""База кейсов: один JSON-файл, атомарная запись."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from aidigest.models import Case


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


@dataclass
class StoreData:
    cases: list[Case] = field(default_factory=list)
    processed_urls: set[str] = field(default_factory=set)


class CaseStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> StoreData:
        if not self.path.exists():
            return StoreData()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return StoreData([Case.model_validate(c) for c in raw.get("cases", [])],
                         set(raw.get("processed_urls", [])))

    def save(self, data: StoreData) -> None:
        payload = {"cases": [c.model_dump(mode="json") for c in data.cases],
                   "processed_urls": sorted(data.processed_urls)}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        replace_with_retry(tmp, self.path)
