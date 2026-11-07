from datetime import date
from pathlib import Path

import pytest

from aidigest.models import (
    Case, ConfirmationStatus, Level, Methodology, Metric, MetricKind, Reliability, Sector, Source, SourceType, Stage,
)
from aidigest.store import CaseStore, StoreData
from aidigest_web import create_app
from webdata import _case, _metric, sample_cases


@pytest.fixture
def data_dir(tmp_path) -> Path:
    CaseStore(tmp_path / "cases.json").save(StoreData(sample_cases(), set()))
    return tmp_path


@pytest.fixture
def app(data_dir):
    app = create_app(data_dir, password=None, secret_key="test")
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def protected_client(data_dir):
    app = create_app(data_dir, password="секрет", secret_key="test")
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def make_case():
    return _case


@pytest.fixture
def make_metric():
    return _metric
