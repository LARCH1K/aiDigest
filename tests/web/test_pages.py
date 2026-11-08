import io

import openpyxl

from aidigest.store import CaseStore, StoreData
from aidigest_web import create_app


def html(r):
    return r.get_data(as_text=True)


def test_list_shows_counts_and_rows(client):
    body = html(client.get("/"))
    assert "Найдено 2 из 3" in body
    assert "Умные светофоры" in body and "Катюша" in body and "Консультанты BCG" not in body
    assert 'href="/case/chel"' in body


def test_list_filters_via_query(client):
    body = html(client.get("/?q=екатеринбург&metrics=0"))
    assert "Найдено 1 из 3" in body and "Катюша" in body and "Умные светофоры" not in body
    body = html(client.get("/?metrics=0&level=мир"))
    assert "Консультанты BCG" in body and "Найдено 1 из 3" in body


def test_empty_base_shows_placeholder(tmp_path):
    app = create_app(tmp_path, password=None, secret_key="t")
    body = html(app.test_client().get("/"))
    assert "Кейсов пока нет" in body


def test_html_is_escaped(tmp_path, make_case):
    CaseStore(tmp_path / "cases.json").save(StoreData([make_case(id="x", title="<script>alert(1)</script>")], set()))
    body = html(create_app(tmp_path, password=None, secret_key="t").test_client().get("/"))
    assert "<script>alert(1)" not in body and "&lt;script&gt;" in body


def test_case_card_shows_quote_source_and_flags(client):
    body = html(client.get("/case/ekb"))
    assert "Катюша" in body and "до 42% обращений" in body
    assert "цифра_не_найдена_в_тексте" in body or "Цифра не найдена" in body
    assert "Проверьте цифру по ссылке вручную" in body
    card = html(client.get("/case/chel"))
    assert "https://chel.kp.ru/1" in card and "gubernia74.ru" in card


def test_unknown_case_is_404(client):
    r = client.get("/case/нет-такого")
    assert r.status_code == 404 and "не найден" in html(r)


def test_help_lists_all_flags(client):
    from aidigest.models import Flag
    body = html(client.get("/help"))
    for f in Flag:
        assert f.value in body


def test_export_returns_xlsx(client):
    r = client.get("/export.xlsx")
    assert r.status_code == 200 and "aidigest_cases_" in r.headers["Content-Disposition"]
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert wb.sheetnames[0] == "Кейсы" and wb["Кейсы"].max_row == 4


def test_list_shows_first_seen_and_reliability(client):
    body = html(client.get("/"))
    assert "В базе с" in body and "Достоверность" in body
    assert "01.11.2026" in body and 'data-sort-value="2026-11-01"' in body
    assert "средняя" in body


def test_list_filters_by_reliability(client):
    assert "Найдено 0 из 3" in html(client.get("/?reliability=высокая"))
    assert "Найдено 2 из 3" in html(client.get("/?reliability=средняя"))
