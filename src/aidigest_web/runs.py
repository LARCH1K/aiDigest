"""Запуски сбора (реализация — задача 4)."""
from __future__ import annotations

from pathlib import Path


class RunManager:
    def __init__(self, data_dir: Path, project_root: Path, **kw):
        self.data_dir = Path(data_dir)
        self.project_root = Path(project_root)
