"""Даты публикаций и обновления сведений в карточке кейса."""
from __future__ import annotations

import json
import re
from calendar import monthrange
from contextlib import contextmanager
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from aidigest.urls import normalize_url

if TYPE_CHECKING:
    from lxml.html import HtmlElement

    from aidigest.models import Article, Case, Source

_MONTHS = {name: number for number, name in enumerate(
    "января февраля марта апреля мая июня июля августа сентября октября ноября декабря".split(), 1
)}
_LOCAL_DATE = re.compile(r"(\d{1,2})[./](\d{1,2})[./](\d{4})")
_RUSSIAN_DATE = re.compile(rf"(\d{{1,2}})\s+({'|'.join(_MONTHS)})\s+(\d{{4}})", re.IGNORECASE)
_LABELED_DATE = re.compile(
    r"^\s*(?:дата публикации|опубликовано|publication date|published(?: on)?)\s*[:\-–—]?\s*"
    rf"(\d{{4}}-\d{{2}}-\d{{2}}|{_LOCAL_DATE.pattern}|{_RUSSIAN_DATE.pattern})(?!\d)",
    re.IGNORECASE | re.MULTILINE,
)
_URL_ISO_DATE = re.compile(r"[/-]([12][0-9]{3})-([0-9]{2})-([0-9]{2})(?=$|[/-])")
# Последний числовой сегмент URL может быть идентификатором статьи.
_URL_CALENDAR_PATH = re.compile(r"/([12][0-9]{3})/([0-9]{2})(?=$|/)(?:/([0-9]{2})(?=/[^/]|-[^/]))?")
_PUBLICATION_META = {"article:published_time", "og:published_time", "datepublished", "pubdate", "publishdate",
                     "publication_date", "publication-date", "parsely-pub-date", "dc.date.issued",
                     "dcterms.issued"}
_TECHNICAL_FIELDS = {"first_seen", "updated", "confirmation_attempts", "last_confirmation_attempt",
                     "plan_input", "flags"}


def _parse_date(value: str) -> date | None:
    try:
        if match := _LOCAL_DATE.fullmatch(value):
            day, month, year = map(int, match.groups())
            return date(year, month, day)
        if match := _RUSSIAN_DATE.fullmatch(value):
            day, month_name, year = match.groups()
            return date(int(year), _MONTHS[month_name.lower()], int(day))
        if re.match(r"\d{4}-\d{2}-\d{2}(?:$|[T ])", value):
            return datetime.fromisoformat(value).date()
        return parsedate_to_datetime(value).date()
    except (ValueError, OverflowError):
        return None


def _explicit_date(value: object) -> date | None:
    return _parse_date(value.strip()) if isinstance(value, str) else None


def publication_date(value: object, text: str = "", *, url: str = "") -> str | None:
    parsed = _explicit_date(value)
    if parsed:
        return parsed.isoformat()
    dates = {_parse_date(match.group(1)) for match in _LABELED_DATE.finditer(text)} - {None}
    if len(dates) == 1:
        return dates.pop().isoformat()
    span = _url_publication_range(url) if url else None
    return span[0].isoformat() if span and span[0] == span[1] else None


def _json_publication_dates(node: object) -> set[date]:
    dates = set()
    nodes = [node]
    while nodes:
        current = nodes.pop()
        if isinstance(current, list):
            nodes.extend(current)
        elif isinstance(current, dict):
            if published := _explicit_date(current.get("datePublished")):
                dates.add(published)
            nodes.extend([current.get("@graph"), current.get("mainEntity")])
    return dates


def html_publication_date(tree: HtmlElement) -> str | None:
    """Читает явно обозначенную дату публикации из HTML и JSON-LD."""
    dates = set()
    for meta in tree.iter("meta"):
        if any(meta.get(attr, "").strip().lower() in _PUBLICATION_META for attr in ("property", "name", "itemprop")):
            if published := _explicit_date(meta.get("content")):
                dates.add(published)
    if dates:
        return dates.pop().isoformat() if len(dates) == 1 else None

    for script in tree.iter("script"):
        if script.get("type", "").strip().lower() != "application/ld+json" or not script.text:
            continue
        try:
            dates.update(_json_publication_dates(json.loads(script.text)))
        except (ValueError, RecursionError):
            continue
    if dates:
        return dates.pop().isoformat() if len(dates) == 1 else None

    for time in tree.iter("time"):
        if "datepublished" in time.get("itemprop", "").lower().split() or "pubdate" in time.attrib:
            if published := _explicit_date(time.get("datetime") or time.text_content()):
                dates.add(published)
    return dates.pop().isoformat() if len(dates) == 1 else None


def _url_publication_range(url: str) -> tuple[date, date] | None:
    try:
        path = urlsplit(url).path
    except ValueError:
        return None

    ranges = set()
    for pattern in (_URL_ISO_DATE, _URL_CALENDAR_PATH):
        for match in pattern.finditer(path):
            raw_year, raw_month, raw_day = match.groups()
            year, month = int(raw_year), int(raw_month)
            try:
                if raw_day is not None:
                    day = date(year, month, int(raw_day))
                    ranges.add((day, day))
                else:
                    # Если в адресе виден только месяц, для проверки давности берём его последний день.
                    start = date(year, month, 1)
                    ranges.add((start, date(year, month, monthrange(year, month)[1])))
            except ValueError:
                continue
    return ranges.pop() if len(ranges) == 1 else None


def article_publication_date(article: Article) -> str | None:
    return publication_date(article.published_at, article.text, url=article.url)


def is_stale_publication(article: Article, since: date) -> bool:
    if published := publication_date(article.published_at, article.text):
        return date.fromisoformat(published) < since
    span = _url_publication_range(article.url)
    return span is not None and span[1] < since


def merge_source(case: Case, source: Source) -> None:
    url = normalize_url(source.url)
    existing = next((item for item in case.sources if normalize_url(item.url) == url), None)
    if existing is None:
        case.sources.append(source)
    elif not existing.published_at and source.published_at:
        existing.published_at = source.published_at


@contextmanager
def case_update(case: Case, today: date):
    before = case.model_dump(exclude=_TECHNICAL_FIELDS)
    try:
        yield
    finally:
        if case.model_dump(exclude=_TECHNICAL_FIELDS) != before:
            case.updated = today
