"""Скачивание текста статьи обычным HTTP-запросом (только для эталона, без Tavily)."""
from __future__ import annotations

import sys
from pathlib import Path

from aidigest.cache import DiskCache

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def fetch_text(url: str, cache: DiskCache, manual_dir: Path, ref_id: str, index: int,
               allow_network: bool = True) -> str:
    manual = Path(manual_dir) / f"{ref_id}-{index}.txt"
    if manual.exists():
        return manual.read_text(encoding="utf-8")
    cached = cache.get("fetch", url)
    if cached is not None:
        return cached
    if not allow_network:
        return ""
    try:
        import requests
        import trafilatura
        resp = requests.get(url, timeout=20, headers={"User-Agent": _UA})
        resp.raise_for_status()
        text = trafilatura.extract(resp.text, include_comments=False, include_tables=True) or ""
    except Exception as e:
        print(f"Не удалось скачать {url}: {e}", file=sys.stderr)
        return ""
    if text:
        cache.put("fetch", url, text)
    return text
