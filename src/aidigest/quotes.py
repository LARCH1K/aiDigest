"""Проверка, что показатель действительно взят из текста статьи (защита от выдуманных цифр)."""
import re

from aidigest.models import Metric

_SPACES = "    "
_QUOTES = "«»“”„\"'‘’"
_DASHES = "—–−‒"

# Префикс слова-множителя → множитель (порядок важен: «миллиард» раньше «миллион»).
_MULTIPLIERS = [("тыс", 1e3), ("млрд", 1e9), ("миллиард", 1e9), ("млн", 1e6), ("миллион", 1e6),
                ("трлн", 1e12), ("триллион", 1e12)]
_NUMBER_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[    ]\d{3})+|\d+)([.,]\d+)?"
    r"(?:\s*(тыс[а-яё]*|млрд|млн|трлн|миллиард[а-яё]*|миллион[а-яё]*|триллион[а-яё]*)(?![а-яё]))?",
    re.IGNORECASE,
)


def normalize_text(s: str) -> str:
    s = s.lower().replace("ё", "е")
    for ch in _SPACES:
        s = s.replace(ch, " ")
    for ch in _QUOTES:
        s = s.replace(ch, '"')
    for ch in _DASHES:
        s = s.replace(ch, "-")
    return re.sub(r"\s+", " ", s).strip()


def extract_numbers(s: str | None) -> list[float]:
    """Числа из текста по-русски; знак не учитывается (всегда модуль)."""
    if not s:
        return []
    out = []
    for whole, frac, mult in _NUMBER_RE.findall(s.lower()):
        value = float(re.sub(r"\D", "", whole) + (("." + frac[1:]) if frac else ""))
        if mult:
            value *= next(k for prefix, k in _MULTIPLIERS if mult.lower().startswith(prefix))
        out.append(value)
    return out


def _strip_punct(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s)).strip()


MIN_QUOTE_WORDS = 3     # короткий обрывок («95%», «5 минут») подтверждает что угодно
MIN_QUOTE_LETTER_WORDS = 2  # и хотя бы два настоящих слова: «12 000 000» — не цитата
MAX_ELLIPSIS_GAP = 150  # символов между частями цитаты с многоточием
_NEGATIONS = re.compile(r"(?<!\w)(не|нет|без|ни)(?!\w)")

# Начала слов, обозначающих направление изменения (сравниваются с началом слова, не с серединой).
_DOWN = ("снизил", "снижен", "сократил", "сокращен", "уменьшил", "уменьшен", "упал", "упад", "падени")
_UP = ("вырос", "выросл", "возрос", "рост", "увеличил", "увеличен", "повысил", "повышен", "прирост")
# Сравнительные слова — только целиком («ниже», но не «нижегородский»).
_DOWN_WORDS = ("меньше", "ниже", "минус")
_UP_WORDS = ("больше", "выше", "плюс")
# Сокращения единиц не считаются словами цитаты: «1,5 млн руб.» — это число, а не цитата.
_UNIT_TOKENS = {"тыс", "млн", "млрд", "трлн", "руб", "коп", "км", "мин", "сек", "чел", "шт", "га", "кг", "тн", "ч"}


def _has_word_start(text: str, prefixes: tuple[str, ...], whole: tuple[str, ...] = ()) -> bool:
    return (any(re.search(r"(?<!\w)" + re.escape(p), text) for p in prefixes)
            or any(re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", text) for w in whole))


def _find(part: str, hay: str, start: int = 0) -> re.Match | None:
    """Поиск части цитаты целыми словами: «на 4» не должно найтись внутри «на 45%»."""
    return re.compile(r"(?<!\w)" + re.escape(part) + r"(?!\w)").search(hay, start)


def quote_in_text(quote: str, text: str) -> bool:
    q, t = normalize_text(quote), normalize_text(text)
    if len(re.findall(r"\w+", q)) < MIN_QUOTE_WORDS:
        return False
    if len([w for w in re.findall(r"[^\W\d_]{2,}", q) if w not in _UNIT_TOKENS]) < MIN_QUOTE_LETTER_WORDS:
        return False
    if "..." in q or "…" in q:
        return _fragments_in_order(q, t)
    if _find(q, t):
        return True
    q2 = _strip_punct(q)
    return bool(q2) and _find(q2, _strip_punct(t)) is not None


def _fragments_in_order(q: str, t: str) -> bool:
    """Цитата с многоточием: части идут по порядку, недалеко друг от друга и без отрицания в пропуске.

    Каждая часть — не короче 2 слов, часть с числом — не короче 3."""
    parts = [_strip_punct(x) for x in re.split(r"\.{3,}|…", q)]
    parts = [x for x in parts if x]
    if not parts:
        return False
    for x in parts:
        need = 3 if re.search(r"\d", x) else 2
        if len(x.split()) < need:
            return False
    hay, pos, prev_end = _strip_punct(t), 0, None
    for part in parts:
        m = _find(part, hay, pos)
        if m is None:
            return False
        if prev_end is not None:
            gap = hay[prev_end:m.start()]
            if len(gap) > MAX_ELLIPSIS_GAP or _NEGATIONS.search(gap):
                return False
        prev_end = pos = m.end()
    return True


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 or abs(a - b) <= 1e-3 * max(abs(a), abs(b))


def numbers_in_quote(metric: Metric) -> bool:
    wanted = [n for part in (metric.before, metric.after, metric.change) for n in extract_numbers(part)]
    have = extract_numbers(metric.quote)
    return all(any(_close(w, h) for h in have) for w in wanted)


def _sign(change: str | None) -> str | None:
    s = normalize_text(change or "")
    if s.startswith(("-", "минус")):
        return "-"
    if s.startswith(("+", "плюс")):
        return "+"
    return None


def direction_consistent(metric: Metric) -> bool:
    """Знак change не противоречит словам цитаты («+23%» при «снизилось на 23%» — ложь).

    Без явного знака или при словах обоих направлений не судим."""
    sign = _sign(metric.change)
    if sign is None:
        return True
    q = normalize_text(metric.quote)
    down, up = _has_word_start(q, _DOWN, _DOWN_WORDS), _has_word_start(q, _UP, _UP_WORDS)
    if down == up:
        return True
    return (sign == "+") == up


def verify_metric(metric: Metric, text: str) -> bool:
    return quote_in_text(metric.quote, text) and numbers_in_quote(metric) and direction_consistent(metric)
