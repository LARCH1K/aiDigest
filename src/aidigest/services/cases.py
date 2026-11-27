"""Логика представления кейсов: фильтры списка, «главная цифра», пояснения флагов. Без HTTP."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from aidigest.export_excel import export_xlsx
from aidigest.methodology import CRITERIA, OTHER_CRITERION, m1_metric_criterion
from aidigest.models import Case, ConfirmationStatus, Flag, Level, Methodology, Reliability
from aidigest.store import Store

DOUBTFUL = {Flag.QUOTE_NOT_FOUND, Flag.SOURCES_CONFLICT}
EFFECT_CRITERIA = (*dict.fromkeys(item for criteria in CRITERIA.values() for item in criteria), OTHER_CRITERION)

# Оценённые уровни достоверности от лучшего к худшему; «не_оценена» в сравнение не входит.
RELIABILITY_ORDER = [Reliability.HIGH, Reliability.MEDIUM, Reliability.LOW]
RELIABILITY_LABEL: dict[Reliability | None, str] = {r: r.value for r in RELIABILITY_ORDER}
RELIABILITY_LABEL[Reliability.UNRATED] = "не оценена"
RELIABILITY_LABEL[None] = "нет оценённых"
RELIABILITY_CLASS: dict[Reliability | None, str] = {Reliability.HIGH: "ok", Reliability.MEDIUM: "warn",
                                                    Reliability.LOW: "bad", Reliability.UNRATED: "muted",
                                                    None: "muted"}
NO_RATED = "none"  # значение фильтра «нет оценённых»


def best_reliability(c: Case) -> Reliability | None:
    """Лучшая оценка достоверности среди источников кейса; None — оценённых источников нет."""
    rated = [s.reliability for s in c.sources if s.reliability in RELIABILITY_ORDER]
    return min(rated, key=RELIABILITY_ORDER.index) if rated else None


def reliability_rank(r: Reliability | None) -> int:
    """Ранг для сортировки таблиц: 1 — высокая, далее по убыванию; неоценённые в конце."""
    return RELIABILITY_ORDER.index(r) + 1 if r in RELIABILITY_ORDER else len(RELIABILITY_ORDER) + 1

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


def _industry_key(name: str) -> str:
    return _norm(" ".join(name.split()))


def _haystack(c: Case) -> str:
    return _norm(" ".join(filter(None, (c.title, c.summary, c.region, c.organization, c.ai_technology,
                                        c.municipality, c.country, c.industry))))


def sort_key(c: Case):
    return (0 if c.metrics else 1, _STATUS_ORDER.index(c.confirmation_status), list(Level).index(c.level))


def filter_cases(cases: list[Case], q: str = "", level: str = "", status: str = "",
                 with_metrics: bool | None = None, hide_doubtful: bool = False, reliability: str = "",
                 criterion: str = "", plan: str = "", industry: str = "") -> list[Case]:
    words = _norm(q).split()
    industry = _industry_key(industry)
    metrics_required = with_metrics if with_metrics is not None else not plan
    out = []
    for c in cases:
        if metrics_required and not c.metrics:
            continue
        if criterion:
            metric_criteria = (m1_metric_criterion(metric) if c.methodology == Methodology.M1 else metric.criterion
                               for metric in c.metrics)
            if criterion not in metric_criteria and not any(item.criterion == criterion for item in c.qualitative_evidence):
                continue
        if plan and not any(link.indicator_id == plan for link in c.plan_links):
            continue
        if industry and _industry_key(c.industry) != industry:
            continue
        if reliability:
            best = best_reliability(c)
            if (best.value if best else NO_RATED) != reliability:
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


@dataclass
class CaseFilter:
    q: str = ""
    level: str = ""
    status: str = ""
    with_metrics: bool | None = None
    hide_doubtful: bool = False
    reliability: str = ""
    criterion: str = ""
    plan: str = ""
    industry: str = ""


class CaseService:
    def __init__(self, store: Store):
        self.store = store

    def list(self, f: CaseFilter) -> tuple[list[Case], int]:
        """Отфильтрованные кейсы и общее число кейсов в базе."""
        cases = self.store.load().cases
        shown = filter_cases(cases, q=f.q, level=f.level, status=f.status, with_metrics=f.with_metrics,
                             hide_doubtful=f.hide_doubtful, reliability=f.reliability,
                             criterion=f.criterion, plan=f.plan, industry=f.industry)
        return shown, len(cases)

    def get(self, case_id: str) -> Case | None:
        return next((c for c in self.store.load().cases if c.id == case_id), None)

    def industries(self) -> list[tuple[str, str]]:
        labels: dict[str, str] = {}
        names = {" ".join(name.split()) for name in self.store.industry_names()}
        for name in sorted(names - {""}):
            labels.setdefault(_industry_key(name), name)
        return sorted(labels.items())

    def export_xlsx(self) -> bytes:
        """Excel со всеми кейсами; файл пишется во временную папку и удаляется."""
        cases = self.store.load().cases
        with tempfile.TemporaryDirectory() as tmp:
            return export_xlsx(cases, None, Path(tmp) / "cases.xlsx").read_bytes()

    def updated_at(self) -> datetime | None:
        fn = getattr(self.store, "updated_at", None)
        return fn() if fn else None
