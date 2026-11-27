"""Методики оценки эффекта ИИ и выбор методики для кейса."""
import math
import re

from aidigest.models import Case, Level, Methodology, Metric, MetricKind, QualitativeEvidence, Sector
from aidigest.quotes import normalize_text

CRITERIA: dict[Methodology, list[str]] = {
    Methodology.R1: ["скорость", "качество", "объективность", "экономическая эффективность", "персонализация"],
    Methodology.M1: ["результат услуги", "качество и надёжность", "производительность и труд",
                     "реализуемость и масштаб", "сопутствующие риски"],
    Methodology.BUSINESS: ["ROI", "операционные затраты", "время процесса", "уровень ошибок"],
}
OTHER_CRITERION = "прочее"

_EXAMPLES: dict[Methodology, dict[str, str]] = {
    Methodology.R1: {
        "скорость": "медианное время ответа на обращение, срок обработки заявления, время реагирования на инцидент",
        "качество": "доля корректных ответов без правки, точность обнаружения объекта, доля ошибочных рекомендаций",
        "объективность": "разброс оценок между исполнителями, согласованность решений",
        "экономическая эффективность": "предотвращённые потери, экономия на единицу услуги, экономия бюджета",
        "персонализация": "доля услуг, адаптированных к потребности, релевантность рекомендаций",
    },
    Methodology.M1: {
        "результат услуги": "время до решения, доступность по времени или каналу, доля решённых с первого обращения",
        "качество и надёжность": "правильные рекомендации, ошибки и отказы, устойчивость в реальных условиях",
        "производительность и труд": "кейсы на сотрудника, часы на кейс, доля ручной работы, нагрузка персонала",
        "реализуемость и масштаб": "готовность данных и кадров, стоимость расширения, интеграционные ограничения",
        "сопутствующие риски": "возможные негативные последствия, ограничения работы и риски исключения групп",
    },
    Methodology.BUSINESS: {
        "ROI": "(выгода − затраты на ИИ) / затраты × 100%",
        "операционные затраты": "экономия ресурсов, снижение расходов на ручной труд",
        "время процесса": "сокращение времени обработки заявок",
        "уровень ошибок": "снижение брака и ошибок в документах",
    },
}

_TITLES = {
    Methodology.R1: "Р-1 (госсектор в регионах РФ, включая Свердловскую область; модель Сбера)",
    Methodology.M1: "М-1 (госсектор за рубежом; OECD + UK AI Impact Evaluation Framework)",
    Methodology.BUSINESS: "бизнес-метрики (компании на любом уровне)",
}

_RUSSIA = {"россия", "рф", "russia", "российская федерация"}
_R1_NUMBER = r"[+−-]?(?:\d{1,3}(?: \d{3})+|\d+)(?:[.,]\d+)?"
_R1_VALUE = re.compile(rf"({_R1_NUMBER})(?:\s*(%|[а-яёa-z₽][а-яёa-z₽. /]*))?", re.I)
_R1_QUOTE_NUMBER = re.compile(rf"(?<![\w.,]){_R1_NUMBER}(?!\d)")
_R1_BASE_MARKERS = {"было", "ранее", "прежде"}
_R1_PROJECT_MARKERS = {"стало", "теперь", "сейчас"}
_R1_SEPARATOR = re.compile(r"(.*?)(?<!\w)(до|стало|теперь|сейчас|было|ранее|прежде|→)\s*")
_R1_MARKER = re.compile(r"\b(с|было|ранее|прежде|стало|теперь|сейчас)\s*$")
_R1_UNITS = {"процент": "%", "процента": "%", "процентов": "%", "минута": "мин", "минуты": "мин", "минут": "мин",
             "секунда": "сек", "секунды": "сек", "секунд": "сек", "рублей": "руб", "₽": "руб"}


def _r1_unit(unit: str) -> str:
    stripped = " ".join(unit.casefold().replace("ё", "е").replace(".", "").split())
    return _R1_UNITS.get(stripped, stripped)


def _r1_number(value: str) -> float:
    return float(value.replace(" ", "").replace(",", ".").replace("−", "-"))


def _r1_quote_supports_pair(quote: str, before: float, after: float, unit: str) -> bool:
    text = normalize_text(quote)
    numbers = list(_R1_QUOTE_NUMBER.finditer(text))
    aliases = {unit, *(name for name, normalized in _R1_UNITS.items() if normalized == unit)} - {""}
    for left, right in zip(numbers, numbers[1:]):
        separator = _R1_SEPARATOR.fullmatch(text[left.end():right.start()])
        if separator is None:
            continue
        unit_text, end_marker = separator.groups()
        marker = _R1_MARKER.search(text, 0, left.start())
        start_marker = marker[1] if marker else ""
        reverse = start_marker in _R1_PROJECT_MARKERS and end_marker in _R1_BASE_MARKERS
        forward = (end_marker == "→" or (start_marker, end_marker) == ("с", "до")
                   or (start_marker in _R1_BASE_MARKERS and end_marker in _R1_PROJECT_MARKERS))
        if not (forward or reverse):
            continue
        quoted = (_r1_number(left[0]), _r1_number(right[0]))
        if quoted != ((after, before) if reverse else (before, after)):
            continue
        left_unit = _r1_unit(re.sub(r"[,;]\s*(?:а\s*)?$", "", unit_text.strip()))
        if left_unit and left_unit != unit:
            continue
        tail = text[right.end():].lstrip()
        if any(re.match(r"\s+".join(re.escape(token) + r"\.?" for token in alias.split()) + r"(?![\w/])", tail)
               for alias in aliases):
            return True
        if left_unit == unit and (not tail or tail[0] in ",.;!?)…"):
            return True
    return False


def r1_ratio(metric: Metric) -> float | None:
    """Отношение базового значения к фактическому результату в сопоставимых единицах."""
    if (metric.kind != MetricKind.FACT or not metric.quote_verified or not metric.before or not metric.after
            or metric.criterion not in CRITERIA[Methodology.R1] or metric.conflicting_values):
        return None
    base = _R1_VALUE.fullmatch(" ".join(metric.before.split()))
    project = _R1_VALUE.fullmatch(" ".join(metric.after.split()))
    if not base or not project:
        return None
    unit = _r1_unit(metric.unit or "")
    base_unit, project_unit = (_r1_unit(match[2] or unit) for match in (base, project))
    if base_unit != project_unit or (unit and base_unit != unit):
        return None
    before, after = (_r1_number(match[1]) for match in (base, project))
    if not math.isfinite(before) or not math.isfinite(after) or after == 0:
        return None
    if not _r1_quote_supports_pair(metric.quote, before, after, base_unit):
        return None
    ratio = before / after
    return ratio if math.isfinite(ratio) else None


def m1_profile(case: Case) -> dict[str, list[QualitativeEvidence]]:
    if case.methodology != Methodology.M1:
        return {}
    profile: dict[str, list[QualitativeEvidence]] = {criterion: [] for criterion in CRITERIA[Methodology.M1]}
    for item in case.qualitative_evidence:
        if item.criterion in profile:
            profile[item.criterion].append(item)
    for metric in case.metrics:
        criterion = m1_metric_criterion(metric)
        if criterion not in profile or not metric.quote_verified or metric.conflicting_values:
            continue
        findings = profile[criterion]
        if not any(item.quote == metric.quote and item.source_url == metric.source_url for item in findings):
            findings.append(QualitativeEvidence(criterion=criterion, fact=metric.name,
                                                source_url=metric.source_url, quote=metric.quote))
    return profile


def select_methodology(level: Level, sector: Sector) -> Methodology:
    if sector == Sector.BUSINESS:
        return Methodology.BUSINESS
    return Methodology.M1 if level == Level.WORLD else Methodology.R1


def infer_level(country: str, region: str | None, *extra: str | None) -> Level:
    """extra — муниципалитет, организация: «Екатеринбург» или «Правительство Свердловской области»."""
    reg = " ".join(x for x in (region, *extra) if x).lower()
    if "свердлов" in reg or "екатеринбург" in reg:
        return Level.SVERDLOVSK
    if country.strip().lower() in _RUSSIA:
        return Level.RF_REGIONS
    return Level.WORLD


def methodology_prompt() -> str:
    lines = []
    for m, crits in CRITERIA.items():
        lines.append(f"Методика {_TITLES[m]}. Допустимые значения criterion:")
        for c in crits:
            lines.append(f"  - «{c}»: например, {_EXAMPLES[m][c]}")
    lines.append(f"Если показатель не подходит ни под один критерий своей методики — criterion «{OTHER_CRITERION}».")
    return "\n".join(lines)


# Подсказки для критерия, если LLM назвала критерий не из списка: ключевые слова (начала слов)
# в названии показателя → критерий. Порядок важен: проверяются сверху вниз.
_KEYWORDS: dict[Methodology, list[tuple[str, tuple[str, ...]]]] = {
    Methodology.BUSINESS: [
        ("ROI", ("roi", "окупаем", "возврат инвестиц", "рентабельн")),
        ("уровень ошибок", ("ошиб", "брак", "дефект", "точност")),
        ("время процесса", ("время", "времен", "скорост", "срок", "быстр", "ускор", "длительн")),
        ("операционные затраты", ("затрат", "расход", "эконом", "стоимост", "издерж", "персонал")),
    ],
    Methodology.R1: [
        ("персонализация", ("персонализ", "индивидуальн", "адаптирова", "рекоменд")),
        ("объективность", ("объектив", "согласован", "единообраз", "разброс")),
        ("качество", ("точност", "качеств", "ошиб", "корректн", "достоверн")),
        ("скорость", ("время", "времен", "скорост", "срок", "быстр", "ускор", "ожидан", "оператив")),
        ("экономическая эффективность", ("эконом", "бюджет", "затрат", "расход", "руб", "стоимост", "потер")),
    ],
    Methodology.M1: [
        ("сопутствующие риски", ("риск", "дискриминац", "утечк", "исключен", "апелляц")),
        ("качество и надёжность", ("точност", "ошиб", "отказ", "качеств", "правильн")),
        ("производительность и труд", ("производительн", "сотрудник", "нагрузк", "ручн", "трудозатрат")),
        ("результат услуги", ("время", "времен", "решен", "обращени", "срок", "доступн", "удовлетвор")),
        ("реализуемость и масштаб", ("пользовател", "охват", "масштаб", "объект", "ведомств", "муниципалитет",
                                     "число", "количеств")),
    ],
}


def guess_criterion(text: str, methodology: Methodology) -> str:
    low = text.lower().replace("ё", "е")
    for criterion, words in _KEYWORDS[methodology]:
        # совпадение с началом слова: «руб» не должно находиться в «трубопровод»
        if any(re.search(r"(?<!\w)" + re.escape(w.replace("ё", "е")), low) for w in words):
            return criterion
    return OTHER_CRITERION


def m1_metric_criterion(metric: Metric) -> str:
    if metric.criterion in {"опыт и доступность", "доверие и распределение эффекта"}:
        return guess_criterion(metric.name, Methodology.M1)
    return metric.criterion
