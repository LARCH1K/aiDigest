"""Разбор лога `aidigest run`: строки отчёта и причина неудачи."""
from aidigest.services.runs import STATE_LABEL, last_reason, parse_report


def test_parse_report_reads_cli_lines():
    log = ("Отсеян кандидат (https://x.ru): опрос\nКредитов Tavily потрачено: 7.0\nКейсов новых: 3\n"
           "Флаг: один_источник: 66\nExcel: report.xlsx\n")
    assert parse_report(log) == {"Кредитов Tavily потрачено": "7.0", "Кейсов новых": "3", "Флаг: один_источник": "66"}
    assert parse_report("Причина: Tavily недоступен\n") == {}


def test_last_reason_takes_last_line_without_prefix():
    out = "Причина: старая\nКейсов новых: 0\nПричина: Tavily недоступен — проверьте ключ.\n"
    assert last_reason(out) == "Tavily недоступен — проверьте ключ."


def test_last_reason_none_without_reason_line():
    assert last_reason("ok\n") is None
    assert last_reason("Причина: \n") is None
    assert last_reason("") is None


def test_state_labels_have_no_busy():
    assert "busy" not in STATE_LABEL and STATE_LABEL["ok"] == "успешно"
