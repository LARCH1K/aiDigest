"""Выгрузка базы кейсов в Excel для команды «Аналитика»."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from aidigest.methodology import m1_profile, r1_ratio
from aidigest.models import Case, ConfirmationStatus, Level, Methodology, Metric
from aidigest.national_plan import PLAN_INDICATORS, PLAN_SOURCE, PLAN_TARGET_YEAR

CASE_HEADERS = ["Уровень", "Страна", "Регион", "Организация", "Сектор", "Отрасль", "Технология ИИ", "Название",
                "Суть", "Стадия", "Методика", "Показатели", "Статус подтверждения", "Флаги", "Источники",
                "Впервые найден", "Обновлён"]
METRIC_HEADERS = ["ID кейса", "Название кейса", "Показатель", "Критерий", "Было", "Стало", "Изменение",
                  "Единица", "Вид", "Цитата", "Источник", "Цитата проверена", "Подтверждено источниками",
                  "Расхождения", "Р-1 (Base / Project)"]
PLAN_HEADERS = ["Пункт", "Показатель нацплана", "Год цели", "Цель, %", "Источник цели", "ID кейса", "Название кейса",
                "Связь с кейсом", "Цитата", "Источник"]
M1_HEADERS = ["ID кейса", "Название кейса", "Критерий", "Факт", "Цитата", "Источник"]
_STATUS_ORDER = [ConfirmationStatus.CONFIRMED, ConfirmationStatus.CONFLICT, ConfirmationStatus.SINGLE]
_WIDE = {"Суть": 60, "Показатели": 60, "Источники": 50, "Флаги": 30, "Цитата": 60, "Название": 35,
         "Название кейса": 35, "Показатель нацплана": 60, "Источник цели": 50, "Факт": 45, "Связь с кейсом": 45}


def metric_line(m: Metric) -> str:
    values = " → ".join(v for v in (m.before, m.after) if v)
    change = f"({m.change})" if m.change else ""
    body = " ".join(p for p in (values, change) if p)
    return f"{m.name}: {body} [{m.criterion}, {m.kind}]"


def _sort_key(c: Case):
    return (0 if c.metrics else 1, _STATUS_ORDER.index(c.confirmation_status), list(Level).index(c.level))


def _case_row(c: Case) -> list[Any]:
    return [c.level, c.country, c.region, c.organization, c.sector, c.industry, c.ai_technology, c.title,
            c.summary, c.stage, c.methodology, "\n".join(metric_line(m) for m in c.metrics),
            c.confirmation_status, "\n".join(c.flags),
            "\n".join(f"{s.url} ({s.reliability})" for s in c.sources),
            c.first_seen.isoformat(), c.updated.isoformat()]


def _metric_rows(c: Case):
    for m in c.metrics:
        yield [c.id, c.title, m.name, m.criterion, m.before, m.after, m.change, m.unit, m.kind, m.quote,
               m.source_url, "да" if m.quote_verified else "нет", "\n".join(m.confirmed_by),
               "\n".join(m.conflicting_values), r1_ratio(m) if c.methodology == Methodology.R1 else None]


def _plan_rows(cases: list[Case]):
    links_by_indicator: dict[str, list[list[str]]] = {}
    for case in cases:
        for link in case.plan_links:
            links_by_indicator.setdefault(link.indicator_id, []).append(
                [case.id, case.title, link.explanation, link.quote, link.source_url])
    for indicator_id, indicator in PLAN_INDICATORS.items():
        goal = [indicator_id, indicator.label, PLAN_TARGET_YEAR, indicator.target_percent, PLAN_SOURCE]
        for evidence in links_by_indicator.get(indicator_id, [[]]):
            yield [*goal, *evidence]


def _m1_rows(case: Case):
    for criterion, evidence in m1_profile(case).items():
        if not evidence:
            yield [case.id, case.title, criterion, "Нет сохранённых свидетельств"]
        for item in evidence:
            yield [case.id, case.title, criterion, item.fact, item.quote, item.source_url]


def _sheet(wb: Workbook, title: str, headers: list[str], rows, first: bool = False):
    ws = wb.active if first else wb.create_sheet()
    ws.title = title
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append([str(v) if hasattr(v, "value") else v for v in row])
    for i, h in enumerate(headers, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = _WIDE.get(h, 18)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            if cell.data_type == "f":
                cell.data_type = "s"
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    return ws


def export_xlsx(cases: list[Case], report: Mapping[str, Any] | None, path: Path) -> Path:
    ordered = sorted(cases, key=_sort_key)
    wb = Workbook()
    _sheet(wb, "Кейсы", CASE_HEADERS, (_case_row(c) for c in ordered), first=True)
    _sheet(wb, "Показатели", METRIC_HEADERS, (r for c in ordered for r in _metric_rows(c)))
    _sheet(wb, "Нацплан", PLAN_HEADERS, _plan_rows(ordered))
    _sheet(wb, "Карта М-1", M1_HEADERS, (r for c in ordered for r in _m1_rows(c)))
    if report is not None:
        ws = wb.create_sheet("Отчёт запуска")
        for k, v in report.items():
            ws.append([k, v if isinstance(v, (int, float, str)) or v is None else str(v)])
        ws.column_dimensions["A"].width = 40
        ws.column_dimensions["B"].width = 40
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(path)
        return path
    except PermissionError:  # файл открыт в Excel — пишем рядом под другим именем
        alt = path.with_name(f"{path.stem}_{datetime.now():%H%M%S}{path.suffix}")
        wb.save(alt)
        return alt
