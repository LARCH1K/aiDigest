"""Межпроцессная блокировка: два `aidigest run` не должны идти одновременно.

Блокировка держится на открытом файле `<data_dir>/run.cli.lock`. ОС снимает её,
когда процесс завершается (в том числе аварийно), поэтому оставшийся файл
ничего не блокирует.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOCK_NAME = "run.cli.lock"


class RunLocked(Exception):
    """Блокировка уже занята другим сбором."""


if os.name == "nt":
    import msvcrt

    def _acquire(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _release(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _acquire(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def run_lock(data_dir: Path) -> Iterator[None]:
    """Эксклюзивная неблокирующая блокировка; занята — бросает RunLocked."""
    data_dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(data_dir / LOCK_NAME, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            _acquire(fd)
        except OSError as e:
            raise RunLocked(str(data_dir / LOCK_NAME)) from e
        try:
            yield
        finally:
            _release(fd)
    finally:
        os.close(fd)
