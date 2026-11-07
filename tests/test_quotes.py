from aidigest.quotes import extract_numbers, normalize_text, numbers_in_quote, quote_in_text, verify_metric

TEXT = ("По данным ведомства, среднее время в пробках сократилось с 13 до 5 минут, "
        "а экономия бюджета — более 9 млн руб.")


def test_normalize_text():
    assert normalize_text("Ёлка «ИИ» —  тест") == 'елка "ии" - тест'


def test_extract_numbers_russian_formats():
    assert extract_numbers("в 2,5 раза") == [2.5]
    assert extract_numbers("9 000 000 руб") == [9_000_000]
    assert extract_numbers("более 9 млн руб.") == [9_000_000]
    assert extract_numbers("со 161 до 122") == [161, 122]
    assert extract_numbers("свыше 90%") == [90]
    assert extract_numbers("снижено на −23%") == [23]
    assert extract_numbers("1,2 млрд") == [1_200_000_000]


def test_quote_found_despite_nbsp_and_dash():
    assert quote_in_text("сократилось с 13 до 5 минут", TEXT)
    assert quote_in_text("экономия бюджета - более 9 млн руб", TEXT)


def test_verify_metric_rejects_invented_number(make_metric):
    ok = make_metric(before="13 мин", after="5 мин", quote="сократилось с 13 до 5 минут")
    bad = make_metric(before="13 мин", after="4 мин", quote="сократилось с 13 до 5 минут")
    assert verify_metric(ok, TEXT) and not verify_metric(bad, TEXT)


def test_verify_metric_rejects_quote_absent_from_text(make_metric):
    m = make_metric(before=None, after=None, change="-24%", quote="число ДТП снизилось на 24%")
    assert not verify_metric(m, TEXT)


def test_million_equivalence(make_metric):
    m = make_metric(before=None, after=None, change="9 000 000 руб", quote="более 9 млн руб")
    assert numbers_in_quote(m)


def test_signed_change_matches_unsigned_quote(make_metric):
    m = make_metric(before=None, after=None, change="-23%", quote="снижена на 23%")
    assert numbers_in_quote(m)
