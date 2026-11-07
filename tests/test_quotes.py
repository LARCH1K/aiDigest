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


def test_extract_numbers_spelled_multipliers():
    assert extract_numbers("превысила 9 миллионов рублей") == [9_000_000]
    assert extract_numbers("1,5 миллиарда") == [1_500_000_000]
    assert extract_numbers("12 тысяч человек") == [12_000]


# --- пакет «к показу»: направление изменения и длина цитаты ---
from aidigest.quotes import direction_consistent

TEXT2 = "Число аварий снизилось на 23%. Выручка выросла на 15%. Точность 95%."


def test_sign_contradicting_quote_is_rejected(make_metric):
    up = make_metric(before=None, after=None, change="+23%", quote="Число аварий снизилось на 23%")
    down = make_metric(before=None, after=None, change="-23%", quote="Число аварий снизилось на 23%")
    assert not verify_metric(up, TEXT2) and verify_metric(down, TEXT2)
    assert not direction_consistent(make_metric(before=None, after=None, change="-15%", quote="Выручка выросла на 15%"))


def test_unsigned_change_and_mixed_words_are_not_judged(make_metric):
    assert direction_consistent(make_metric(before=None, after=None, change="23%", quote="Число аварий снизилось на 23%"))
    assert direction_consistent(make_metric(before=None, after=None, change="-5%",
                                            quote="расходы снизились на 5%, а выручка выросла"))


def test_too_short_quote_is_rejected(make_metric):
    assert not quote_in_text("95%", TEXT2)
    assert not quote_in_text("Точность 95%", TEXT2)
    assert quote_in_text("Выручка выросла на 15%", TEXT2)


ELLIPSIS_TEXT = "Как показала практика, ИИ способен прогнозировать аварии, а также плановые отключения с точностью свыше 90%."


def test_quote_with_ellipsis_matches_fragments_in_order():
    assert quote_in_text("ИИ способен прогнозировать аварии... с точностью свыше 90%", ELLIPSIS_TEXT)
    assert quote_in_text("ИИ способен прогнозировать аварии … с точностью свыше 90%", ELLIPSIS_TEXT)


def test_ellipsis_fragments_out_of_order_or_absent_are_rejected():
    assert not quote_in_text("с точностью свыше 90%... ИИ способен прогнозировать", ELLIPSIS_TEXT)
    assert not quote_in_text("ИИ способен прогнозировать аварии... с точностью свыше 99%", ELLIPSIS_TEXT)
    assert not quote_in_text("ИИ... 90%", ELLIPSIS_TEXT)


# --- ревью quality-pass ---

def test_truncated_numbers_do_not_match(make_metric):
    text = "Время обработки заявок сократилось на 45%. Обработка стала в 15 раз быстрее."
    m = make_metric(before=None, after=None, change="-4%", quote="заявок сократилось на 4")
    assert not verify_metric(m, text)
    assert not quote_in_text("стала в 5 раз быстрее", text.replace("в 15", "в 15"))
    assert not quote_in_text("Время обработки ... сократилось на 4", text)


def test_ellipsis_gap_is_limited_and_rejects_negation():
    far = "Время обработки заявок сократилось. " + "Прочий текст. " * 20 + "Число сотрудников выросло на 40% за год."
    assert not quote_in_text("Время обработки заявок сократилось ... выросло на 40% за год", far)
    neg = "Затраты компании в этом году не снизились на 30% вопреки ожиданиям."
    assert not quote_in_text("Затраты компании ... снизились на 30%", neg)


def test_number_fragment_in_ellipsis_needs_three_words():
    t = "Время обработки заявок сократилось. Итог на 40% лучше."
    assert not quote_in_text("Время обработки заявок ... на 40%", t)


def test_bare_numbers_are_not_a_quote():
    t = "Бюджет проекта 12 000 000 рублей, экономия 1,5 млн руб. в год."
    assert not quote_in_text("12 000 000", t)
    assert not quote_in_text("1,5 млн руб.", t)
    assert quote_in_text("экономия 1,5 млн руб. в год", t)


def test_direction_words_match_word_starts_only(make_metric):
    ok = make_metric(before=None, after=None, change="-30%", quote="Количество простоев — минус 30% за квартал")
    assert direction_consistent(ok)
    assert direction_consistent(make_metric(before=None, after=None, change="+20%",
                                            quote="эффективность на нижегородском заводе +20%"))


def test_em_dash_and_word_signs_are_judged(make_metric):
    assert not direction_consistent(make_metric(before=None, after=None, change="—23%", quote="выручка выросла на 23%"))
    assert not direction_consistent(make_metric(before=None, after=None, change="минус 23%",
                                                quote="выручка выросла на 23%"))
