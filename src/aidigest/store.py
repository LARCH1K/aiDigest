"""База кейсов: один JSON-файл, атомарная запись."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from aidigest.models import Case


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
        os.replace(tmp, self.path)
