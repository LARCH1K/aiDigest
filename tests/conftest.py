from datetime import date

import pytest

from aidigest.models import (
    Case, Level, Methodology, Metric, MetricKind, Reliability, Sector, Source, SourceType, Stage,
)


@pytest.fixture
def make_metric():
    def _make(**kw):
        base = dict(
            name="время в пробках", criterion="скорость", before="13 мин", after="5 мин",
            change=None, unit="мин", kind=MetricKind.FACT,
            quote="сократилось с 13 до 5 минут", source_url="https://gubernia74.ru/news/1",
            quote_verified=True,
        )
        base.update(kw)
        return Metric(**base)
    return _make


@pytest.fixture
def make_source():
    def _make(url="https://gubernia74.ru/news/1", **kw):
        from urllib.parse import urlsplit
        host = urlsplit(url).hostname or ""
        base = dict(url=url, domain=host.removeprefix("www."), title="", reliability=Reliability.MEDIUM,
                    source_type=SourceType.MEDIA)
        base.update(kw)
        return Source(**base)
    return _make


@pytest.fixture(scope="session")
def registry():
    from pathlib import Path
    from aidigest.registry import SourceRegistry
    return SourceRegistry.load(Path(__file__).resolve().parent.parent / "config" / "sources.yaml")


@pytest.fixture
def case_reply():
    """Ответ LLM формата extract.SYSTEM_PROMPT; region/stage/country — в кейс, остальное — в метрику."""
    def _make(**kw):
        case = {"country": "Россия", "region": "Челябинская область", "municipality": None,
                "organization": None, "sector": "госсектор", "industry": "транспорт",
                "ai_technology": "компьютерное зрение", "title": "т", "summary": "с", "stage": "внедрён"}
        for k in ("region", "stage", "country", "sector", "organization", "title"):
            if k in kw:
                case[k] = kw.pop(k)
        metric = {"name": "время в пробках", "criterion": "скорость", "before": "13 мин", "after": "5 мин",
                  "change": None, "unit": "мин", "kind": "факт", "quote": "сократилось с 13 до 5 минут"}
        metric.update(kw)
        case["metrics"] = [metric]
        return {"cases": [case]}
    return _make


@pytest.fixture
def make_case(make_metric, make_source):
    def _make(**kw):
        base = dict(
            id="c1", first_seen=date(2026, 11, 1), updated=date(2026, 11, 1),
            level=Level.RF_REGIONS, country="Россия", region="Челябинская область",
            municipality=None, organization="Минтранс области", sector=Sector.GOV,
            industry="транспорт", ai_technology="компьютерное зрение", title="Умные светофоры",
            summary="ИИ анализирует дорожную обстановку.", stage=Stage.DEPLOYED,
            methodology=Methodology.R1,
        )
        base.update(kw)
        if "metrics" not in base:
            base["metrics"] = [make_metric()]
        if "sources" not in base:
            base["sources"] = [make_source()]
        return Case(**base)
    return _make
