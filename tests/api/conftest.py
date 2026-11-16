"""Фикстуры HTTP API: настоящая БД (pg), фейковый popen вместо подпроцесса сбора."""
import threading
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aidigest.config import Settings
from aidigest.services.runs import RunService, RunStore
from aidigest.store import PgCaseStore, StoreData
from aidigest_api import create_app
from services.casedata import sample_cases

USER, PASSWORD = "u", "p"


class FakeProc:
    def __init__(self, gate):
        self.gate = gate

    def wait(self, timeout=None):
        if self.gate is not None:
            self.gate.wait(timeout if timeout is not None else 10)
        return 0

    def terminate(self):
        if self.gate is not None:
            self.gate.set()

    def poll(self):
        return None if self.gate is not None and not self.gate.is_set() else 0


@pytest.fixture
def popen_calls():
    return []


@pytest.fixture
def gate():
    ev = threading.Event()
    yield ev
    ev.set()


@pytest.fixture
def make_client(pg, tmp_path, popen_calls, gate):
    """Фабрика клиентов; клиенты входят в контекст (lifespan) и закрываются после теста."""
    stack: list = []
    services: list[RunService] = []

    def _make(*, password=PASSWORD, secure=False, block=False, base_url="http://testserver", trust_real_ip=False):
        def popen(argv, **kw):
            popen_calls.append(argv)
            return FakeProc(gate if block else None)
        svc = RunService(RunStore(pg), tmp_path / "data", Path("/proj"), Settings(), None, popen=popen,
                         now=datetime.now)
        services.append(svc)
        app = create_app(pg, username=USER if password else None, password=password,
                         secret_key="k" * 32, secure_cookie=secure, run_service=svc, trust_real_ip=trust_real_ip)
        client = TestClient(app, base_url=base_url)
        client.__enter__()
        stack.append(client)
        return client

    yield _make
    gate.set()
    for c in stack:
        c.__exit__(None, None, None)
    for s in services:
        s.join_watchers()


def _login(c):
    assert c.post("/api/login", json={"username": USER, "password": PASSWORD}).status_code == 204
    return c


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def secure_client(make_client):
    return make_client(secure=True)


@pytest.fixture
def open_client(make_client):
    return make_client(password=None, base_url="http://localhost")


@pytest.fixture
def authed(make_client):
    return _login(make_client())


@pytest.fixture
def authed_blocking_child(make_client):
    return _login(make_client(block=True))


@pytest.fixture
def authed_with_cases(pg, authed):
    cases = sample_cases()
    urls = {source.url for case in cases for source in case.sources}
    PgCaseStore(pg).save(StoreData(cases=cases, processed_urls=urls))
    return authed
