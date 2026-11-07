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


MIN_QUOTE_WORDS = 3  # короткий обрывок («95%», «5 минут») подтверждает что угодно

_DOWN = ("снизил", "снижен", "сократил", "сокращен", "уменьшил", "уменьшен", "упал", "падени", "меньше", "ниже")
_UP = ("вырос", "выросл", "рост", "увеличил", "увеличен", "повысил", "повышен", "прирост", "больше", "выше")


def quote_in_text(quote: str, text: str) -> bool:
    q, t = normalize_text(quote), normalize_text(text)
    if len(re.findall(r"\w+", q)) < MIN_QUOTE_WORDS:
        return False
    if "..." in q or "…" in q:
        return _fragments_in_order(q, t)
    if q in t:
        return True
    q2 = _strip_punct(q)
    return bool(q2) and q2 in _strip_punct(t)


def _fragments_in_order(q: str, t: str) -> bool:
    """Цитата с многоточием: каждая часть (не короче 2 слов) есть в тексте, части идут по порядку."""
    parts = [_strip_punct(x) for x in re.split(r"\.{3,}|…", q)]
    parts = [x for x in parts if x]
    if not parts or any(len(x.split()) < 2 for x in parts):
        return False
    hay, pos = _strip_punct(t), 0
    for part in parts:
        pos = hay.find(part, pos)
        if pos < 0:
            return False
        pos += len(part)
    return True


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 or abs(a - b) <= 1e-3 * max(abs(a), abs(b))


def numbers_in_quote(metric: Metric) -> bool:
    wanted = [n for part in (metric.before, metric.after, metric.change) for n in extract_numbers(part)]
    have = extract_numbers(metric.quote)
    return all(any(_close(w, h) for h in have) for w in wanted)


def direction_consistent(metric: Metric) -> bool:
    """Знак change не противоречит словам цитаты («+23%» при «снизилось на 23%» — ложь).

    Без явного знака или при словах обоих направлений не судим."""
    change = (metric.change or "").strip()
    if not change or change[0] not in "+-−–":
        return True
    q = normalize_text(metric.quote)
    down = any(w in q for w in _DOWN)
    up = any(w in q for w in _UP)
    if down == up:
        return True
    return (change[0] == "+") == up


def verify_metric(metric: Metric, text: str) -> bool:
    return quote_in_text(metric.quote, text) and numbers_in_quote(metric) and direction_consistent(metric)
