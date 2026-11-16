"""Даты публикаций и обновления сведений в карточке кейса."""
from __future__ import annotations

import re
from contextlib import contextmanager
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

from aidigest.urls import normalize_url

if TYPE_CHECKING:
    from aidigest.models import Case, Source

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
_TECHNICAL_FIELDS = {"first_seen", "updated", "confirmation_attempts", "last_confirmation_attempt",
                     "strategy_input", "flags"}


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


def publication_date(value: str | None, text: str = "") -> str | None:
    parsed = _parse_date(value.strip()) if value else None
    if parsed:
        return parsed.isoformat()
    dates = {_parse_date(match.group(1)) for match in _LABELED_DATE.finditer(text)} - {None}
    return dates.pop().isoformat() if len(dates) == 1 else None


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
