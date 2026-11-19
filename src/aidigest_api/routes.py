"""Адаптеры HTTP над сервисами кейсов, каталога и запусков."""
import re
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import PlainTextResponse

from aidigest.models import Case, ConfirmationStatus, Level
from aidigest.services.cases import (
    EFFECT_CRITERIA, FLAG_HELP, NO_RATED, RELIABILITY_CLASS, RELIABILITY_LABEL, RELIABILITY_ORDER, STATUS_CLASS,
    STATUS_LABEL, CaseFilter, CaseService, best_reliability, headline,
)
from aidigest.services.catalog import ANY_RF_LABEL, ANY_RF_LEVEL, CatalogService
from aidigest.services.runs import AlreadyRunning, MonthExhausted, RunParams, RunService, RunServiceStopping
from aidigest.strategy import STRATEGY_KPIS
from aidigest_api.schemas import (
    ActiveRun, CaseDetail, CaseList, CaseQuery, CaseRow, Credits, IdleRun, Meta, Option, Queries,
    QueryGroup, RunQuery, RunRequest, RunRow, RunStarted, SourceQuery, Sources, StatusOption, StrategyKpiOption,
)

BUSY = "Сбор уже идёт — дождитесь, пока он закончится."
LIMIT_EXHAUSTED = "Лимит поисковых запросов исчерпан."
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PROVIDER_NAMES = re.compile(
    r"https://(?:api\.tavily\.com|searchapi\.api\.cloud\.yandex\.net)[^\s\"']*"
    r"|\b(?:Yandex Search API|YandexSearch|TavilySearch|yandex_search|Tavily)(?:\.env)?\b",
    re.IGNORECASE,
)


def _run_text(text: str) -> str:
    """Убирает имена провайдеров из текста текущих и архивных запусков."""
    text = text.replace("Кредитов Tavily потрачено", "Новых поисковых запросов")
    return _PROVIDER_NAMES.sub("поисковый сервис", text)


async def _run_params(request: Request, body: RunRequest | None = None) -> RunParams:
    # FastAPI передаёт None и для отсутствующего тела, и для явного JSON null.
    if body is None and await request.body():
        raise RequestValidationError([{"type": "dict_type", "loc": ("body",), "msg": "Ожидается объект JSON"}])
    params = RunParams(**(body or {}))
    max_days = (date.today() - date.min).days
    if params.days is not None and params.days > max_days:
        raise RequestValidationError([{"type": "less_than_equal", "loc": ("body", "days"),
                                       "msg": f"Окно поиска не может превышать {max_days} дней"}])
    return params


def _case_row(case: Case) -> CaseRow:
    status = case.confirmation_status
    reliability = best_reliability(case)
    headline_text, headline_unverified = headline(case)
    return CaseRow(
        id=case.id, title=case.title, level=case.level, country=case.country, region=case.region,
        organization=case.organization, industry=case.industry, stage=case.stage, first_seen=case.first_seen,
        updated=case.updated, metrics=case.metrics, strategy_links=case.strategy_links,
        status=status, status_label=STATUS_LABEL[status], status_class=STATUS_CLASS[status],
        headline=headline_text, headline_unverified=headline_unverified, flags=case.flags,
        reliability=reliability, reliability_label=RELIABILITY_LABEL[reliability],
        reliability_class=RELIABILITY_CLASS[reliability],
    )


def api_routes(case_service: CaseService, catalog: CatalogService, runs: RunService) -> APIRouter:
    router = APIRouter(prefix="/api")
    level_options = [Option(value=level.value, label=level.value) for level in Level]
    reliability_options = [Option(value=rating.value, label=RELIABILITY_LABEL[rating])
                           for rating in RELIABILITY_ORDER]

    @router.get("/meta")
    def meta() -> Meta:
        return Meta(
            levels=list(Level),
            statuses=[StatusOption(value=status.value, label=STATUS_LABEL[status], css_class=STATUS_CLASS[status])
                      for status in ConfirmationStatus],
            reliability=[*reliability_options, Option(value=NO_RATED, label=RELIABILITY_LABEL[None])],
            criteria=[Option(value=criterion, label=criterion[0].upper() + criterion[1:])
                      for criterion in EFFECT_CRITERIA],
            strategy_kpis=[StrategyKpiOption(value=kpi_id, label=kpi.label, clause=kpi.clause, url=kpi.url)
                           for kpi_id, kpi in STRATEGY_KPIS.items()],
            flag_help=FLAG_HELP,
        )

    @router.get("/cases")
    def cases(query: Annotated[CaseQuery, Query()]) -> CaseList:
        items, total = case_service.list(CaseFilter(
            q=query.q, level=query.level, status=query.status, reliability=query.reliability,
            criterion=query.criterion, kpi=query.kpi, hide_doubtful=query.doubtful == "1",
            with_metrics=None if query.metrics is None else query.metrics == "1",
        ))
        return CaseList(total=total, updated=case_service.updated_at(), cases=[_case_row(case) for case in items])

    @router.get("/cases/{case_id}")
    def case_detail(case_id: str) -> CaseDetail:
        case = case_service.get(case_id)
        if case is None:
            raise HTTPException(404, "Кейс не найден")
        return CaseDetail(
            **case.model_dump(exclude={"flags"}),
            status_label=STATUS_LABEL[case.confirmation_status], status_class=STATUS_CLASS[case.confirmation_status],
            reliability_label=RELIABILITY_LABEL[best_reliability(case)],
        )

    @router.get("/export.xlsx", response_class=Response)
    def export() -> Response:
        filename = f"aidigest_cases_{date.today().isoformat()}.xlsx"
        return Response(case_service.export_xlsx(), media_type=XLSX_TYPE,
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @router.get("/credits")
    def credits() -> Credits:
        return Credits.model_validate(runs.credits())

    @router.get("/runs/current")
    def current_run() -> IdleRun | ActiveRun:
        current = runs.current()
        if current is None:
            return IdleRun()
        run, tail = current
        return ActiveRun(run_id=run.run_id, started=run.started, minutes=run.minutes,
                         tail=[_run_text(line) for line in tail])

    @router.post("/runs", status_code=202)
    def start_run(params: Annotated[RunParams, Depends(_run_params)]) -> RunStarted:
        try:
            return RunStarted(run_id=runs.start(params))
        except AlreadyRunning as exc:
            raise HTTPException(409, BUSY) from exc
        except MonthExhausted as exc:
            raise HTTPException(409, LIMIT_EXHAUSTED) from exc
        except RunServiceStopping as exc:
            raise HTTPException(503, "Сервис завершает работу") from exc

    @router.get("/runs")
    def run_history(query: Annotated[RunQuery, Query()]) -> list[RunRow]:
        history = [RunRow.model_validate(run) for run in runs.history(query.limit)]
        for row in history:
            if row.reason:
                row.reason = _run_text(row.reason)
            row.report = {_run_text(key): _run_text(value) for key, value in row.report.items()}
        return history

    @router.get("/runs/{run_id}/log", response_class=PlainTextResponse)
    def run_log(run_id: str) -> str:
        result = runs.log(run_id)
        if result is None:
            raise HTTPException(404, "Лог запуска не найден")
        return _run_text(result)

    @router.get("/queries")
    def queries() -> Queries:
        groups, total, freshness_days, error = catalog.queries()
        return Queries(groups=[QueryGroup(level=level, queries=items) for level, items in groups],
                       total=total, freshness_days=freshness_days, error=error)

    @router.get("/sources")
    def sources(query: Annotated[SourceQuery, Query()]) -> Sources:
        items, total, error = catalog.sources(level=query.level, reliability=query.reliability)
        return Sources(sources=items, total=total, error=error, reliability_options=reliability_options,
                       level_options=[*level_options, Option(value=ANY_RF_LEVEL, label=ANY_RF_LABEL)])

    return router
