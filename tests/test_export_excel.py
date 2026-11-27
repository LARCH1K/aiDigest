import openpyxl

from aidigest.export_excel import export_xlsx, metric_line
from aidigest.models import Level, PlanLink


def test_export_sheets_order_and_headers(tmp_path, make_case, make_metric):
    a = make_case(title="без цифр", metrics=[])
    b = make_case(title="подтверждён", metrics=[make_metric(confirmed_by=["https://x.ru"])])
    b.recompute_status()
    p = tmp_path / "out.xlsx"
    export_xlsx([a, b], {"Кредитов потрачено": 3}, p)
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["Кейсы", "Показатели", "Нацплан", "Карта М-1", "Отчёт запуска"]
    ws = wb["Кейсы"]
    hdr = [c.value for c in ws[1]]
    assert hdr[0] == "Уровень" and "Флаги" in hdr and len(hdr) == 17
    assert ws.cell(2, hdr.index("Название") + 1).value == "подтверждён"
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref
    assert wb["Показатели"].max_row == 2
    assert wb["Показатели"]["O2"].value == 2.6
    assert {row[0]: row[3] for row in wb["Нацплан"].iter_rows(min_row=2, values_only=True)} == {
        "1.1": 70, "1.2": 50, "2.3": 60, "3.1": 70, "3.2": 100, "3.3": 50,
    }
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
    assert openpyxl.load_workbook(p).sheetnames == ["Кейсы", "Показатели", "Нацплан", "Карта М-1"]


def test_plan_sheet_keeps_the_target_and_case_evidence_in_separate_columns(tmp_path, make_case):
    link = PlanLink(indicator_id="1.2", explanation="ИИ готовит проекты ответов.",
                    source_url="https://example.org/replies", quote="Помощник составляет проекты ответов на обращения.")
    case = make_case(plan_links=[link])
    workbook = openpyxl.load_workbook(export_xlsx([case], None, tmp_path / "out.xlsx"))
    rows = list(workbook["Нацплан"].iter_rows(min_row=2, values_only=True))
    assert rows[1][0] == "1.2" and rows[1][2:4] == (2030, 50)
    assert rows[1][5:] == (case.id, case.title, link.explanation, link.quote, link.source_url)
    assert all(row[5] is None for row in [rows[0], *rows[2:]])


def test_metric_line_skips_empty_parts(make_metric):
    assert metric_line(make_metric()) == "время в пробках: 13 мин → 5 мин [скорость, факт]"
    assert metric_line(make_metric(before=None, after=None, change="-23%")) == "время в пробках: (-23%) [скорость, факт]"


def test_locked_file_falls_back_to_new_name(tmp_path, make_case, monkeypatch):
    from openpyxl import Workbook
    real_save = Workbook.save
    target = tmp_path / "cases.xlsx"

    def save(self, filename):
        if str(filename) == str(target):
            raise PermissionError("файл открыт в Excel")
        return real_save(self, filename)
    monkeypatch.setattr(Workbook, "save", save)
    written = export_xlsx([make_case()], None, target)
    assert written != target and written.exists() and written.parent == tmp_path
