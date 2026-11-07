"""Модели данных: кейс внедрения ИИ, показатели, источники."""
from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, computed_field


class Level(StrEnum):
    WORLD = "мир"
    RF_REGIONS = "регионы РФ"
    SVERDLOVSK = "Свердловская область"


class Sector(StrEnum):
    GOV = "госсектор"
    BUSINESS = "бизнес"


class Stage(StrEnum):
    # Порядок объявления = порядок зрелости (используется при слиянии кейсов).
    UNKNOWN = "неизвестно"
    DEVELOPMENT = "в разработке"
    PILOT = "пилот"
    DEPLOYED = "внедрён"
    SCALING = "масштабирование"


class MetricKind(StrEnum):
    FACT = "факт"
    PLAN = "план"


class Reliability(StrEnum):
    HIGH = "высокая"
    MEDIUM = "средняя"
    LOW = "низкая"
    UNRATED = "не_оценена"


class SourceType(StrEnum):
    OFFICIAL = "официальная"
    STATISTICS = "статистика"
    CASES = "кейсы"
    MARKET = "аналитика рынка"
    MEDIA = "СМИ"
    UNKNOWN = "неизвестно"


class Methodology(StrEnum):
    M1 = "М-1"
    R1 = "Р-1"
    BUSINESS = "бизнес-метрики"


class ConfirmationStatus(StrEnum):
    CONFIRMED = "подтверждено"
    CONFLICT = "противоречие"
    SINGLE = "один_источник"


class Flag(StrEnum):
    QUOTE_NOT_FOUND = "цифра_не_найдена_в_тексте"
    SOURCES_CONFLICT = "противоречие_источников"
    SINGLE_SOURCE = "один_источник"
    STAGE_UNCLEAR = "стадия_неясна"
    NO_METRICS = "нет_измеримых_показателей"
    SOURCE_UNRATED = "источник_не_оценён"
    CONFIRMATION_SKIPPED = "подтверждение_не_проводилось"


class Metric(BaseModel):
    name: str
    criterion: str
    before: str | None = None
    after: str | None = None
    change: str | None = None
    unit: str | None = None
    kind: MetricKind = MetricKind.FACT
    quote: str
    source_url: str
    quote_verified: bool = False
    confirmed_by: list[str] = []
    conflicting_values: list[str] = []


class Source(BaseModel):
    url: str
    domain: str
    title: str = ""
    published_at: str | None = None
    reliability: Reliability = Reliability.UNRATED
    source_type: SourceType = SourceType.UNKNOWN


class Article(BaseModel):
    url: str
    domain: str
    title: str
    text: str
    published_at: str | None = None


class Case(BaseModel):
    id: str
    first_seen: date
    updated: date
    level: Level
    country: str
    region: str | None = None
    municipality: str | None = None
    organization: str | None = None
    sector: Sector
    industry: str
    ai_technology: str
    title: str
    summary: str
    stage: Stage
    methodology: Methodology
    metrics: list[Metric] = []
    sources: list[Source] = []
    confirmation_status: ConfirmationStatus = ConfirmationStatus.SINGLE
    confirmation_attempts: int = 0
    last_confirmation_attempt: date | None = None

    @computed_field
    @property
    def flags(self) -> list[Flag]:
        """Флаги сомнений — вычисляются из данных кейса, отдельно не хранятся."""
        out: list[Flag] = []
        if any(not m.quote_verified for m in self.metrics):
            out.append(Flag.QUOTE_NOT_FOUND)
        if self.confirmation_status == ConfirmationStatus.CONFLICT:
            out.append(Flag.SOURCES_CONFLICT)
        if self.confirmation_status == ConfirmationStatus.SINGLE and self.confirmation_attempts > 0:
            out.append(Flag.SINGLE_SOURCE)
        if self.stage == Stage.UNKNOWN:
            out.append(Flag.STAGE_UNCLEAR)
        if not self.metrics:
            out.append(Flag.NO_METRICS)
        if any(s.reliability == Reliability.UNRATED for s in self.sources):
            out.append(Flag.SOURCE_UNRATED)
        if self.metrics and self.confirmation_attempts == 0:
            out.append(Flag.CONFIRMATION_SKIPPED)
        return out

    def recompute_status(self) -> None:
        if any(m.conflicting_values for m in self.metrics):
            self.confirmation_status = ConfirmationStatus.CONFLICT
        elif any(m.confirmed_by for m in self.metrics):
            self.confirmation_status = ConfirmationStatus.CONFIRMED
        else:
            self.confirmation_status = ConfirmationStatus.SINGLE
