"""Тестовые данные фронта (отдельный модуль: имя conftest занято корневыми тестами)."""
from datetime import date

from aidigest.models import (
    Case, ConfirmationStatus, Level, Methodology, Metric, MetricKind, Reliability, Sector, Source, SourceType, Stage,
)


def _metric(**kw):
    base = dict(name="время в пробках", criterion="скорость", before="13 мин", after="5 мин", change=None, unit="мин",
                kind=MetricKind.FACT, quote="время в пробках сократилось с 13 до 5 минут",
                source_url="https://gubernia74.ru/news/1", quote_verified=True)
    base.update(kw)
    return Metric(**base)


def _case(**kw):
    base = dict(id="c1", first_seen=date(2026, 11, 1), updated=date(2026, 11, 1), level=Level.RF_REGIONS,
                country="Россия", region="Челябинская область", municipality=None, organization="Минтранс",
                sector=Sector.GOV, industry="транспорт", ai_technology="компьютерное зрение",
                title="Умные светофоры", summary="ИИ анализирует дорожную обстановку.", stage=Stage.DEPLOYED,
                methodology=Methodology.R1, metrics=[_metric()],
                sources=[Source(url="https://gubernia74.ru/news/1", domain="gubernia74.ru",
                                reliability=Reliability.MEDIUM, source_type=SourceType.MEDIA)])
    base.update(kw)
    return Case(**base)


def sample_cases() -> list[Case]:
    confirmed = _case(id="chel", metrics=[_metric(confirmed_by=["https://chel.kp.ru/1"])])
    confirmed.recompute_status()
    sverd = _case(id="ekb", level=Level.SVERDLOVSK, region="Свердловская область", title="ИИ-помощник «Катюша» в ЗАГС",
                  organization="ЗАГС Екатеринбурга", industry="госуслуги",
                  metrics=[_metric(name="доля обращений", before=None, after="42%", quote="до 42% обращений",
                                   quote_verified=False)])
    world = _case(id="bcg", level=Level.WORLD, country="США", region=None, organization="BCG", sector=Sector.BUSINESS,
                  title="Консультанты BCG и GPT-4", methodology=Methodology.BUSINESS, metrics=[], stage=Stage.PILOT)
    return [world, sverd, confirmed]
