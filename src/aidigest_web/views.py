"""Логика представления: фильтры списка, «главная цифра», пояснения флагов. Без HTTP."""
from __future__ import annotations

from aidigest.models import Case, ConfirmationStatus, Flag, Level

DOUBTFUL = {Flag.QUOTE_NOT_FOUND, Flag.SOURCES_CONFLICT}

STATUS_CLASS = {
    ConfirmationStatus.CONFIRMED: "ok",
    ConfirmationStatus.SINGLE: "warn",
    ConfirmationStatus.CONFLICT: "bad",
}
STATUS_LABEL = {
    ConfirmationStatus.CONFIRMED: "подтверждено",
    ConfirmationStatus.SINGLE: "один источник",
    ConfirmationStatus.CONFLICT: "противоречие",
}
_STATUS_ORDER = [ConfirmationStatus.CONFIRMED, ConfirmationStatus.CONFLICT, ConfirmationStatus.SINGLE]

FLAG_HELP: dict[Flag, tuple[str, str]] = {
    Flag.QUOTE_NOT_FOUND: ("Цитаты или числа нет в тексте статьи — возможно, LLM ошиблась или досчитала цифру сама.",
                           "Проверьте цифру по ссылке вручную и не используйте её без проверки."),
    Flag.SOURCES_CONFLICT: ("Источники называют разные значения одного показателя.",
                            "Сравните обе версии по ссылкам."),
    Flag.SINGLE_SOURCE: ("Подтверждение во втором издании искали, но не нашли.",
                         "Цифра может быть верной, но не перепроверена."),
    Flag.CONFIRMATION_SKIPPED: ("На поиск подтверждения не хватило кредитов.",
                                "Следующий запуск сбора проверит сам."),
    Flag.NO_METRICS: ("Кейс есть, но измеримых цифр в статье нет.",
                      "Годится как пример внедрения, но не как измеримый кейс."),
    Flag.STAGE_UNCLEAR: ("По статье не понять стадию внедрения.",
                         "Уточните по другим материалам."),
    Flag.SOURCE_UNRATED: ("Сайта нет в справочнике источников, его достоверность не оценена.",
                          "При необходимости попросите добавить сайт в справочник."),
}


def _norm(s: str | None) -> str:
    return (s or "").lower().replace("ё", "е")


def _haystack(c: Case) -> str:
    return _norm(" ".join(filter(None, (c.title, c.summary, c.region, c.organization, c.ai_technology,
                                        c.municipality, c.country, c.industry))))


def sort_key(c: Case):
    return (0 if c.metrics else 1, _STATUS_ORDER.index(c.confirmation_status), list(Level).index(c.level))


def filter_cases(cases: list[Case], q: str = "", level: str = "", status: str = "",
                 with_metrics: bool = True, hide_doubtful: bool = False) -> list[Case]:
    words = _norm(q).split()
    out = []
    for c in cases:
        if with_metrics and not c.metrics:
            continue
        if level and c.level.value != level:
            continue
        if status and c.confirmation_status.value != status:
            continue
        if hide_doubtful and DOUBTFUL & set(c.flags):
            continue
        if words:
            hay = _haystack(c)
            if not all(w in hay for w in words):
                continue
        out.append(c)
    return sorted(out, key=sort_key)


def short_line(m) -> str:
    """«название: было → стало (изменение)» без критерия — для списка."""
    values = " → ".join(v for v in (m.before, m.after) if v)
    if m.change:
        values = f"{values} ({m.change})" if values else m.change
    return f"{m.name}: {values}" if values else m.name


def headline(c: Case) -> tuple[str, bool]:
    """Главная цифра кейса и признак «цифра не проверена цитатой»."""
    for m in c.metrics:
        if m.quote_verified:
            return short_line(m), False
    if c.metrics:
        return short_line(c.metrics[0]), True
    return "—", False
