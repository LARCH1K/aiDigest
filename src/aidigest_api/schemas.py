"""Модели запросов и ответов HTTP API."""
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from typing_extensions import NotRequired, TypedDict

from aidigest.config import QuerySpec
from aidigest.models import Case, ConfirmationStatus, Flag, Level, Reliability, Stage
from aidigest.registry import SourceInfo
from aidigest.services.cases import NO_RATED
from aidigest.services.catalog import ANY_RF_LEVEL


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(RequestModel):
    username: str
    password: str


class RunRequest(TypedDict):
    __pydantic_config__ = ConfigDict(extra="forbid")

    budget: NotRequired[Annotated[float, Field(strict=True, gt=0, allow_inf_nan=False)]]
    levels: NotRequired[list[Level]]
    days: NotRequired[Annotated[int, Field(strict=True, ge=1)]]
    offline: NotRequired[Annotated[bool, Field(strict=True)]]


class CaseQuery(RequestModel):
    q: str = ""
    level: Level | Literal[""] = ""
    status: ConfirmationStatus | Literal[""] = ""
    metrics: Literal["0", "1"] = "1"
    doubtful: Literal["0", "1"] = "0"
    reliability: Reliability | Literal[NO_RATED, ""] = ""


class SourceQuery(RequestModel):
    level: Level | Literal[ANY_RF_LEVEL, ""] = ""
    reliability: Reliability | Literal[""] = ""


def _integer_query_value(value: str | int) -> str | int:
    if isinstance(value, str) and not (value.isascii() and value.isdecimal()):
        raise ValueError("Ожидается положительное целое число")
    return value


class RunQuery(RequestModel):
    limit: Annotated[int, BeforeValidator(_integer_query_value), Field(ge=1, le=2**63 - 1)] = 10


class SessionState(BaseModel):
    authenticated: bool
    login_required: bool


class Option(BaseModel):
    value: str
    label: str


class StatusOption(Option):
    css_class: str = Field(serialization_alias="class")


class Meta(BaseModel):
    levels: list[Level]
    statuses: list[StatusOption]
    reliability: list[Option]
    flag_help: dict[Flag, tuple[str, str]]


class CaseRow(BaseModel):
    id: str
    title: str
    level: Level
    country: str
    region: str | None
    organization: str | None
    industry: str
    stage: Stage
    first_seen: date
    status: ConfirmationStatus
    status_label: str
    status_class: str
    headline: str
    headline_unverified: bool
    reliability: Reliability | None
    reliability_label: str
    reliability_class: str
    flags: list[Flag]


class CaseList(BaseModel):
    total: int
    updated: datetime | None
    cases: list[CaseRow]


class CaseDetail(Case):
    status_label: str
    status_class: str
    reliability_label: str


class Credits(BaseModel):
    known: bool
    used: float | None
    limit: float | None
    remaining: float | None
    plan: str
    run_budget: float


class RunStarted(BaseModel):
    run_id: str


class IdleRun(BaseModel):
    running: Literal[False] = False


class ActiveRun(RunStarted):
    running: Literal[True] = True
    started: datetime
    minutes: int
    tail: list[str]


class RunRow(RunStarted):
    model_config = ConfigDict(from_attributes=True)

    state: str
    label: str
    started: datetime
    finished: datetime | None
    minutes: int
    exit_code: int | None
    reason: str | None
    report: dict[str, str]
    params: dict


class QueryGroup(BaseModel):
    level: Level
    queries: list[QuerySpec]


class Queries(BaseModel):
    groups: list[QueryGroup]
    total: int
    freshness_days: int
    error: str | None


class Sources(BaseModel):
    sources: list[SourceInfo]
    total: int
    error: str | None
    level_options: list[Option]
    reliability_options: list[Option]
