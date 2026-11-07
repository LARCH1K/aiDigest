import openpyxl

from aidigest.export_excel import export_xlsx, metric_line
from aidigest.models import Level


def test_export_sheets_order_and_headers(tmp_path, make_case, make_metric):
    a = make_case(title="без цифр", metrics=[])
    b = make_case(title="подтверждён", metrics=[make_metric(confirmed_by=["https://x.ru"])])
    b.recompute_status()
    p = tmp_path / "out.xlsx"
    export_xlsx([a, b], {"Кредитов потрачено": 3}, p)
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["Кейсы", "Показатели", "Отчёт запуска"]
    ws = wb["Кейсы"]
    hdr = [c.value for c in ws[1]]
    assert hdr[0] == "Уровень" and "Флаги" in hdr and len(hdr) == 17
    assert ws.cell(2, hdr.index("Название") + 1).value == "подтверждён"
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref
    assert wb["Показатели"].max_row == 2
    assert wb["Отчёт запуска"].cell(1, 2).value == 3


def test_sort_by_status_then_level(tmp_path, make_case, make_metric):
    w = make_case(title="мир", level=Level.WORLD, metrics=[make_metric(confirmed_by=["https://x.ru"])])
    s = make_case(title="сверд", level=Level.SVERDLOVSK, metrics=[make_metric(confirmed_by=["https://x.ru"])])
    single = make_case(title="один", level=Level.WORLD)
    for c in (w, s):
        c.recompute_status()
    p = tmp_path / "o.xlsx"
    export_xlsx([single, s, w], None, p)
    ws = openpyxl.load_workbook(p)["Кейсы"]
    col = [c.value for c in ws[1]].index("Название") + 1
    assert [ws.cell(r, col).value for r in (2, 3, 4)] == ["мир", "сверд", "один"]


def test_export_without_report(tmp_path, make_case):
    p = tmp_path / "o.xlsx"
    export_xlsx([make_case()], None, p)
    assert openpyxl.load_workbook(p).sheetnames == ["Кейсы", "Показатели"]


def test_metric_line_skips_empty_parts(make_metric):
    assert metric_line(make_metric()) == "время в пробках: 13 мин → 5 мин [скорость, факт]"
    assert metric_line(make_metric(before=None, after=None, change="-23%")) == "время в пробках: (-23%) [скорость, факт]"
