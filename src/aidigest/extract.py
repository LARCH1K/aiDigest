"""Извлечение кейсов внедрения ИИ из статьи с помощью LLM."""
from __future__ import annotations

import re
import uuid
from datetime import date
from typing import Any

from aidigest.llm import LLMClient, LLMFormatError
from aidigest.methodology import (CRITERIA, OTHER_CRITERION, guess_criterion, infer_level, methodology_prompt,
                                  select_methodology)
from aidigest.models import Article, Case, Level, Methodology, Metric, MetricKind, QualitativeEvidence, Sector, Stage
from aidigest.quotes import extract_numbers, literal_quote_in_text, metric_kind_from_quote, normalize_text, quote_in_text, verify_metric
from aidigest.registry import SourceRegistry
from aidigest.urls import normalize_url

SYSTEM_PROMPT = f"""Ты аналитик, который собирает кейсы внедрения искусственного интеллекта.
Тебе дают текст одной статьи. Найди в нём конкретные кейсы внедрения ИИ.

Кейс — это конкретное внедрение: известно, КТО внедрил (организация, ведомство, регион, компания),
ГДЕ и ЧТО сделано (какая система на основе ИИ и для какой задачи).
Каждый элемент cases — ровно одно внедрение для одной задачи. Если статья описывает несколько проектов,
верни отдельный объект для каждого проекта. Показатели, описание и отрасль относятся только к этому объекту.
Цифровизация, электронные формы и обычная автоматизация сами по себе не являются внедрением ИИ.
Упоминание ИИ в другом проекте статьи или в рассуждении об отрасли не доказывает применение ИИ здесь.
НЕ являются кейсами: общие новости рынка, мнения и интервью без конкретного проекта, анонсы конференций,
обзоры технологий, планы «внедрить ИИ» без указания конкретного проекта, отраслевая статистика и прогнозы
(суммарные затраты отрасли, опросы компаний, рейтинги регионов), продажа ИИ-продукта без названного заказчика.
Если кейсов нет — верни {{"cases": []}}.
Если сомневаешься, кейс ли это, всё равно верни его, но с is_concrete: false и причиной в not_concrete_reason.
Для настоящего кейса is_concrete: true.
Отсутствие цифр — НЕ причина ставить is_concrete: false. Пилот, проект в разработке или запущенная система
с названным исполнителем — это кейс, даже если результатов пока нет (тогда metrics: []).

Для каждого кейса укажи:
- implementation_quote — один короткий дословный фрагмент, в котором прямо сказано, что ИИ или конкретный
  метод ИИ применяют, тестируют или разрабатывают именно для этой задачи. Без склейки предложений и многоточий;
- application — конкретная задача системы или название проекта. Лучше скопировать эту часть
  implementation_quote из оригинала, даже если оригинал на другом языке;
- attribution_quote — короткая дословная цитата о месте внедрения или исполнителе этого проекта,
  если их названия отсутствуют в implementation_quote и в заголовке. Иначе null;
- country — страна по-русски («Россия», «Германия», «Республика Корея»);
- region — субъект/регион/штат или null; municipality — город/муниципалитет или null. Имена копируй из материала.
  Учитывай место самого внедрения. Название портала, издатель, охват поиска и место публикации его не определяют;
- organization — кто внедрил (название как в источнике), или null;
- sector — «госсектор» (органы власти, госучреждения, ЖКХ, госмедицина, образование) или «бизнес» (компании);
- industry — отрасль (транспорт, здравоохранение, ЖКХ, госуправление, промышленность…);
- ai_technology — какая технология ИИ (компьютерное зрение, генеративный ИИ, предиктивная аналитика…);
- title — короткое название кейса; summary — суть в 2–3 предложениях;
- stage — одно из: «в разработке», «пилот», «внедрён», «масштабирование», «неизвестно».

Показатели (metrics) — только ИЗМЕРИМЫЕ эффекты, которые прямо названы в тексте числами:
- name — что измеряли; before/after — значения «было»/«стало» (если есть); change — изменение («-23%», «в 2,5 раза»);
- unit — единица; kind — «факт» (уже достигнуто) или «план» (ожидается/целевое значение);
- quote — ДОСЛОВНАЯ цитата из статьи (одно предложение или его часть), в которой стоят эти числа.
  Цитату копируй символ в символ, не перефразируй.
- criterion — критерий методики (см. ниже), РОВНО одно из допустимых значений, символ в символ.
  Методика зависит от сектора и уровня: госсектор в России → Р-1; госсектор за рубежом → М-1;
  бизнес → бизнес-метрики (экономия денег и расходов → «операционные затраты»; сроки и скорость →
  «время процесса»; ошибки, брак, точность → «уровень ошибок»; окупаемость и доход → «ROI»).

ЗАПРЕЩЕНО придумывать, округлять или пересчитывать числа. Нет числа в тексте — нет показателя.
ЗАПРЕЩЕНО вычислять before/after из изменения: если в тексте сказано только «снизилось на 23%»,
заполни только change («-23%»), а before и after оставь null.

Извлекай ВСЕ числовые показатели кейса, каждый отдельным элементом metrics:
- эффект (время, затраты, число аварий/ошибок/обращений — было/стало или изменение);
- экономия денег;
- точность или качество работы ИИ-модели («точность прогноза свыше 90%»);
- охват: каждое число отдельно — число пользователей, ведомств, объектов, обработанных задач
  («426 госслужащих из 25 ведомств» → два показателя: 426 госслужащих и 25 ведомств).
Числа, упомянутые в summary, тоже должны быть в metrics.

Для М-1 заполни также qualitative_evidence: наблюдения о публичной услуге по пяти критериям М-1,
включая риски и ограничения. Для каждого наблюдения верни criterion, fact (кратко по-русски, без цифр)
и quote (дословный фрагмент, подтверждающий факт). Если свидетельства нет, пропусти этот критерий.
Для других методик оставь qualitative_evidence пустым.

{methodology_prompt()}

Ответ — только JSON без пояснений, строго такого вида:
{{"cases": [{{"is_concrete": true, "not_concrete_reason": null, "country": "", "region": null, "municipality": null, "organization": null,
  "implementation_quote": "", "application": "", "attribution_quote": null,
  "sector": "госсектор", "industry": "", "ai_technology": "", "title": "", "summary": "", "stage": "неизвестно",
  "qualitative_evidence": [{{"criterion": "", "fact": "", "quote": ""}}],
  "metrics": [{{"name": "", "criterion": "", "before": null, "after": null, "change": null,
               "unit": null, "kind": "факт", "quote": ""}}]}}]}}"""


def _enum(enum_cls, value: Any, default):
    try:
        return enum_cls(str(value).strip().lower() if value is not None else "")
    except ValueError:
        return default


def _criterion(value: Any, name: str, methodology) -> str:
    v = str(value or "").strip().lower()
    for c in CRITERIA[methodology]:
        if c.lower() == v:
            return c
    if v == OTHER_CRITERION:
        return OTHER_CRITERION  # LLM сознательно выбрала «прочее» — не переписываем
    return guess_criterion(f"{v} {name}", methodology)


def _opt(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _qualitative_evidence(rows: Any, text: str, url: str) -> list[QualitativeEvidence]:
    evidence = []
    if not isinstance(rows, list):
        return evidence
    for row in rows:
        if not isinstance(row, dict):
            continue
        fields = ("criterion", "fact", "quote")
        if any(not isinstance(row.get(field), str) for field in fields):
            continue
        criterion, fact, quote = (row[field].strip() for field in fields)
        if criterion in CRITERIA[Methodology.M1] and fact and not re.search(r"\d", fact) and quote_in_text(quote, text):
            item = QualitativeEvidence(criterion=criterion, fact=fact, quote=quote, source_url=url)
            if item not in evidence:
                evidence.append(item)
    return evidence


def _cases_from_reply(reply: Any) -> list[dict]:
    """Список кейсов из ответа LLM; ValueError, если структура не та."""
    # GigaChat иногда возвращает один кейс без обёртки или голый список — принимаем оба варианта.
    if isinstance(reply, list):
        cases = reply
    elif isinstance(reply, dict) and "cases" in reply:
        cases = reply["cases"]
    elif isinstance(reply, dict) and ("metrics" in reply or "title" in reply):
        cases = [reply]
    else:
        raise ValueError("ожидался объект с ключом cases")
    if not isinstance(cases, list) or not all(isinstance(c, dict) for c in cases):
        raise ValueError("cases должен быть списком объектов")
    return cases


FEDERAL_REGION = "федеральный уровень"

_AI_SIGNAL = re.compile(
    r"\b(?:ии|ai|copilot|chatgpt|госпромпт|искусственн\w+ интеллект\w*|машинн\w+ обучени\w*|"
    r"нейросет\w*|нейронн\w+ сет\w*|компьютерн\w+ зрени\w*|"
    r"больш\w+ языков\w+ модел\w*|llms?|artificial intelligence|machine learning|"
    r"deep learning|neural networks?|computer vision|large language models?)\b"
)
_SEPARATE_STATEMENTS = re.compile(r"[.!?;]\s+|,\s+(?=(?:но|однако|but|while)\b)")
_NEGATED_AI = re.compile(
    r"\b(?:без|не (?:использ\w*|примен\w*|внедр\w*)|without|not (?:use|using|apply|deploy))\s+(?:\w+\s+){0,2}$"
)
_ENTITY_WORDS = re.compile(r"[^\W_]+")
_GEO_FILLERS = {"г", "город", "обл", "область", "край", "регион", "округ", "республика", "штат", "the", "of"}
_REGION_MENTION = re.compile(r"\b[а-я]+ск(?:ая|ой|ую|ою)\s+област(?:ь|и|ью)\b")
_RU_ENDING = re.compile(r"(?<=[а-я]{5})(?:ский|ская|ское|ские|скую|ской|ского|ском|ским|"
                        r"ая|ой|ого|ому|ом|ов|ым|ам|ах|ью|[аеёиоуыюяь])$")
_REGION_ALIASES = {"свердловская область": ("средний урал", "екатеринбург")}
_COUNTRY_ALIASES = {"германия": ("germany", "deutschland"), "эстония": ("estonia", "eesti"),
                    "канада": ("canada",), "великобритания": ("united kingdom", "uk"),
                    "сша": ("united states", "usa")}
_LATIN_APPLICATION = re.compile(r"\b(?:build\w*|develop\w*|us(?:e|es|ed|ing)|analys\w*|analyz\w*|"
                                r"deploy\w*|detect\w*|apply\w*|appli\w*|implement\w*|guid\w*|"
                                r"help\w*|pilot\w*|automat\w*)\b")
_CYRILLIC = re.compile(r"[а-я]")
_AI_REFERENCE = re.compile(r"\b(?:на (?:его|ее|их) основе|эт(?:от|а|и) (?:алгоритм|модел|систем)\w*|"
                           r"(?:this|that|these) (?:model|algorithm|system)s?)\b")
_TASK_FILLERS = {"искус", "интел", "систе", "техно", "внедр", "помощ", "инстр", "испол"}


def _task_terms(text: str) -> set[str]:
    return {word[:5] for word in _ENTITY_WORDS.findall(text) if len(word) >= 5} - _TASK_FILLERS


def _task_in_statement(application: str, statement: str) -> bool:
    if literal_quote_in_text(application, statement):
        return True
    if _CYRILLIC.search(application) and not _CYRILLIC.search(statement):
        return bool(_LATIN_APPLICATION.search(statement))
    application_terms = _task_terms(application)
    return bool(application_terms) and len(application_terms & _task_terms(statement)) >= min(2, len(application_terms))


def _implementation_context(quote: str, application: str, text: str) -> str:
    evidence = normalize_text(quote)
    task = normalize_text(application)
    if not evidence or not task or len(evidence) > 650 or _AI_SIGNAL.fullmatch(task):
        return ""
    source = normalize_text(text)
    for statement in re.split(r"\.{3,}|…", evidence):
        for part in _SEPARATE_STATEMENTS.split(statement):
            part = part.strip(" .!?;,")
            if not _task_in_statement(task, part):
                continue
            offsets = [signal.start() for signal in _AI_SIGNAL.finditer(part)]
            for position in re.finditer(r"(?<!\w)" + re.escape(part) + r"(?!\w)", source):
                # Начало цитаты может скрывать отрицание. Соседний фрагмент также помогает установить регион.
                preceding = source[max(0, position.start() - 125):position.start()]
                if any(not _NEGATED_AI.search(preceding + part[:offset]) for offset in offsets):
                    return preceding + part
                if _AI_REFERENCE.search(part):
                    previous = _SEPARATE_STATEMENTS.split(preceding.rstrip(" .!?;"))[-1]
                    if any(not _NEGATED_AI.search(previous[:signal.start()]) for signal in _AI_SIGNAL.finditer(previous)):
                        return preceding + part
    return ""


def _entity_supported(name: str, context: str, *, geography: bool = False) -> bool:
    normalized = normalize_text(name)
    names = (normalized,)
    if "(" in normalized:
        names += (normalized.split("(", 1)[0].strip(), *re.findall(r"\(([^()]+)\)", normalized))
    if geography:
        names += _REGION_ALIASES.get(normalized, ()) + _COUNTRY_ALIASES.get(normalized, ())
    contextual_tokens = {_RU_ENDING.sub("", word) for word in _ENTITY_WORDS.findall(normalize_text(context))}
    for candidate in names:
        if literal_quote_in_text(candidate, context):
            return True
        tokens = _ENTITY_WORDS.findall(candidate)
        if geography:
            tokens = [token for token in tokens if token not in _GEO_FILLERS]
        if tokens and all(_RU_ENDING.sub("", token) in contextual_tokens for token in tokens):
            return True
    return False


def _record_rejection(rejected: list[str] | None, title: str, reason: str) -> None:
    if rejected is not None:
        rejected.append(f"{title}: {reason}")


def _numeric_slot(value: Any) -> str | None:
    slot = _opt(value)
    return slot if extract_numbers(slot) else None


def _verified_variant(metric: Metric, text: str) -> Metric:
    """Показатель с флагом проверки. LLM часто досчитывает недостающее: «стало 77%» из «−23%» или
    «+43,8%» из «16 → 23». Если без досчитанной части цитата подтверждается, убираем только её."""
    if verify_metric(metric, text):
        return metric.model_copy(update={"quote_verified": True})
    variants = []
    if metric.before or metric.after:
        variants.append({"change": None})
    if metric.change:
        variants.append({"before": None, "after": None})
    for update in variants:
        trimmed = metric.model_copy(update=update)
        if (trimmed.before or trimmed.after or trimmed.change) and verify_metric(trimmed, text):
            return trimmed.model_copy(update={"quote_verified": True})
    return metric.model_copy(update={"quote_verified": False})


def extract_cases(article: Article, llm: LLMClient, registry: SourceRegistry, today: date,
                  max_chars: int, rejected: list[str] | None = None) -> list[Case]:
    """Кейсы статьи. Отсеянные кандидаты (не конкретное внедрение) — в rejected как «название: причина»."""
    text = article.text[:max_chars]
    user = f"Заголовок: {article.title}\nURL: {article.url}\n\nТекст статьи:\n{text}"
    try:
        cases_raw = _cases_from_reply(llm.complete_json(SYSTEM_PROMPT, user, validate=_cases_from_reply))
    except ValueError as e:  # фейки и старые клиенты могут не применять validate сами
        raise LLMFormatError(str(e)) from e

    url = normalize_url(article.url)
    source = registry.to_source(article)
    source_regions = set(_REGION_MENTION.findall(normalize_text(text)))
    out: list[Case] = []
    seen_applications: set[tuple[str, str]] = set()
    for raw in cases_raw:
        title = _opt(raw.get("title")) or article.title
        country = _opt(raw.get("country")) or "неизвестно"
        region = _opt(raw.get("region"))
        organization = _opt(raw.get("organization"))
        municipality = _opt(raw.get("municipality"))
        if str(raw.get("is_concrete")).strip().lower() in ("false", "нет", "no", "0"):
            reason = _opt(raw.get("not_concrete_reason")) or "не конкретное внедрение"
            _record_rejection(rejected, title, reason)
            continue
        if not (organization or region or municipality or country != "неизвестно"):
            _record_rejection(rejected, title, "не указано, кто и где внедрил")
            continue
        quote = _opt(raw.get("implementation_quote")) or ""
        application = _opt(raw.get("application")) or ""
        evidence = _implementation_context(quote, application, text) or _implementation_context(quote, application, article.title)
        if not evidence:
            _record_rejection(rejected, title, "в источнике нет цитаты о применении ИИ для этой задачи")
            continue
        attribution = _opt(raw.get("attribution_quote")) or ""
        project_context = evidence
        if len(attribution) <= 400 and literal_quote_in_text(attribution, text):
            project_context += f"\n{attribution}"
        context = f"{article.title}\n{project_context}"
        if region:
            # Заголовок дайджеста может называть другую область, чем сам проект.
            region_in_evidence = _REGION_MENTION.search(normalize_text(project_context))
            region_context = project_context if region_in_evidence else context
            sole_region = (not region_in_evidence and source_regions
                           and all(_entity_supported(region, mention, geography=True) for mention in source_regions))
            if not sole_region and not _entity_supported(region, region_context, geography=True):
                _record_rejection(rejected, title, "регион внедрения не подтверждён источником")
                continue
        if municipality and not _entity_supported(municipality, context, geography=True):
            municipality = None
        if organization and not _entity_supported(organization, context):
            organization = None
        country_only = (country != "неизвестно" and infer_level(country, None) == Level.WORLD
                        and _entity_supported(country, context, geography=True))
        if not (region or municipality or organization or country_only):
            _record_rejection(rejected, title, "в источнике не указан исполнитель или место внедрения")
            continue
        application_key = (normalize_text(application), normalize_text(quote).rstrip(".!?"))
        if application_key in seen_applications:
            continue
        seen_applications.add(application_key)
        level = infer_level(country, region, municipality, organization)
        if level == Level.RF_REGIONS and not region and not municipality:
            region = FEDERAL_REGION
        sector = _enum(Sector, raw.get("sector"), Sector.GOV)
        methodology = select_methodology(level, sector)
        metrics = []
        for m in raw.get("metrics") or []:
            if not isinstance(m, dict) or not _opt(m.get("quote")):
                continue
            before, after, change = (_numeric_slot(m.get(key)) for key in ("before", "after", "change"))
            if not (before or after or change):
                continue
            metric_quote = str(m["quote"]).strip()
            metric = Metric(
                name=_opt(m.get("name")) or "показатель",
                criterion=_criterion(m.get("criterion"), str(m.get("name") or ""), methodology),
                before=before, after=after, change=change,
                unit=_opt(m.get("unit")), kind=metric_kind_from_quote(metric_quote, text)
                or _enum(MetricKind, m.get("kind"), MetricKind.FACT),
                quote=metric_quote, source_url=url,
            )
            metric = _verified_variant(metric, text)
            metrics.append(metric)
        qualitative = (_qualitative_evidence(raw.get("qualitative_evidence"), text, url)
                       if methodology == Methodology.M1 else [])
        out.append(Case(
            id=uuid.uuid4().hex[:12], first_seen=today, updated=today, level=level,
            country=country, region=region, municipality=municipality,
            organization=organization, sector=sector,
            industry=_opt(raw.get("industry")) or "", ai_technology=_opt(raw.get("ai_technology")) or "",
            title=title, summary=_opt(raw.get("summary")) or "",
            stage=_enum(Stage, raw.get("stage"), Stage.UNKNOWN), methodology=methodology,
            metrics=metrics, sources=[source.model_copy()], qualitative_evidence=qualitative,
        ))
    return out
