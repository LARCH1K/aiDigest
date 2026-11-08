"""Страницы «Запросы» и «Источники»: только показывают config/*.yaml."""
from pathlib import Path

from aidigest.config import load_queries
from aidigest.registry import SourceRegistry
from aidigest_web import create_app

CONFIG = Path(__file__).resolve().parents[2] / "config"


def html(r):
    return r.get_data(as_text=True)


def broken_config(tmp_path) -> Path:
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "queries.yaml").write_text("queries: [: не yaml", encoding="utf-8")
    (cfg / "sources.yaml").write_text("sources:\n  - name: без полей\n", encoding="utf-8")
    return cfg


def test_nav_links_to_config_pages(client):
    body = html(client.get("/"))
    assert 'href="/queries"' in body and 'href="/sources"' in body


def test_queries_page_lists_real_queries(client):
    queries = load_queries(CONFIG / "queries.yaml")
    r = client.get("/queries")
    body = html(r)
    assert r.status_code == 200
    assert queries[0].text in body and queries[-1].text in body
    assert f"Всего запросов: {len(queries)}" in body
    assert "Что означают поля" in body and "Только по справочнику" in body


def test_queries_page_survives_broken_yaml(data_dir, tmp_path):
    app = create_app(data_dir, password=None, secret_key="t", config_dir=broken_config(tmp_path))
    r = app.test_client().get("/queries")
    assert r.status_code == 200 and "Не удалось прочитать" in html(r)


def test_sources_page_lists_registry(client):
    sources = SourceRegistry.load(CONFIG / "sources.yaml").sources
    r = client.get("/sources")
    body = html(r)
    assert r.status_code == 200
    assert "TAdviser" in body and "tadviser.ru" in body
    assert f"Найдено {len(sources)} из {len(sources)}" in body
    assert "Что означают поля" in body and "не оценена" in body


def test_sources_filter_by_reliability(client):
    body = html(client.get("/sources?reliability=высокая"))
    assert "TAdviser" not in body and "ИСИЭЗ НИУ ВШЭ" in body


def test_sources_filter_by_level(client):
    sources = SourceRegistry.load(CONFIG / "sources.yaml").sources
    world = [s for s in sources if s.level is not None and s.level.value == "мир"]
    body = html(client.get("/sources?level=мир"))
    assert f"Найдено {len(world)} из {len(sources)}" in body and "TAdviser" not in body


def test_sources_page_survives_broken_yaml(data_dir, tmp_path):
    app = create_app(data_dir, password=None, secret_key="t", config_dir=broken_config(tmp_path))
    r = app.test_client().get("/sources")
    assert r.status_code == 200 and "Не удалось прочитать" in html(r)
