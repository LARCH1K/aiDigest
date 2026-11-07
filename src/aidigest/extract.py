"""Извлечение кейсов внедрения ИИ из статьи с помощью LLM."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from aidigest.llm import LLMClient, LLMFormatError
from aidigest.methodology import (CRITERIA, OTHER_CRITERION, guess_criterion, infer_level, methodology_prompt,
                                  select_methodology)
from aidigest.models import Article, Case, Level, Metric, MetricKind, Sector, Stage
from aidigest.quotes import verify_metric
from aidigest.registry import SourceRegistry
from aidigest.urls import normalize_url

SYSTEM_PROMPT = f"""Ты аналитик, который собирает кейсы внедрения искусственного интеллекта.
Тебе дают текст одной статьи. Найди в нём конкретные кейсы внедрения ИИ.

Кейс — это конкретное внедрение: известно, КТО внедрил (организация, ведомство, регион, компания),
ГДЕ и ЧТО сделано (какая система на основе ИИ и для какой задачи).
НЕ являются кейсами: общие новости рынка, мнения и интервью без конкретного проекта, анонсы конференций,
обзоры технологий, планы «внедрить ИИ» без указания конкретного проекта, отраслевая статистика и прогнозы
(суммарные затраты отрасли, опросы компаний, рейтинги регионов), продажа ИИ-продукта без названного заказчика.
Если кейсов нет — верни {{"cases": []}}.
Если сомневаешься, кейс ли это, всё равно верни его, но с is_concrete: false и причиной в not_concrete_reason.
Для настоящего кейса is_concrete: true.

Для каждого кейса укажи:
- country — страна по-русски («Россия», «Германия», «Республика Корея»);
- region — субъект/регион/штат или null; municipality — город/муниципалитет или null;
- organization — кто внедрил, или null;
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

{methodology_prompt()}

Ответ — только JSON без пояснений, строго такого вида:
{{"cases": [{{"is_concrete": true, "not_concrete_reason": null, "country": "", "region": null, "municipality": null, "organization": null,
  "sector": "госсектор", "industry": "", "ai_technology": "", "title": "", "summary": "", "stage": "неизвестно",
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
    return guess_criterion(f"{v} {name}", methodology)


def _opt(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


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
    user = f"Заголовок: {article.title}\nURL: {article.url}\n\nТекст статьи:\n{article.text[:max_chars]}"
    try:
        cases_raw = _cases_from_reply(llm.complete_json(SYSTEM_PROMPT, user, validate=_cases_from_reply))
    except ValueError as e:  # фейки и старые клиенты могут не применять validate сами
        raise LLMFormatError(str(e)) from e

    url = normalize_url(article.url)
    source = registry.to_source(article)
    out: list[Case] = []
    for raw in cases_raw:
        title = _opt(raw.get("title")) or article.title
        country = _opt(raw.get("country")) or "неизвестно"
        region = _opt(raw.get("region"))
        organization = _opt(raw.get("organization"))
        municipality = _opt(raw.get("municipality"))
        if raw.get("is_concrete") is False:
            reason = _opt(raw.get("not_concrete_reason")) or "не конкретное внедрение"
            if rejected is not None:
                rejected.append(f"{title}: {reason}")
            continue
        if not (organization or region or municipality):
            if rejected is not None:
                rejected.append(f"{title}: не указано, кто и где внедрил")
            continue
        level = infer_level(country, region)
        if level == Level.RF_REGIONS and not region:
            region = FEDERAL_REGION
        sector = _enum(Sector, raw.get("sector"), Sector.GOV)
        methodology = select_methodology(level, sector)
        metrics = []
        for m in raw.get("metrics") or []:
            if not isinstance(m, dict) or not _opt(m.get("quote")):
                continue
            metric = Metric(
                name=_opt(m.get("name")) or "показатель",
                criterion=_criterion(m.get("criterion"), str(m.get("name") or ""), methodology),
                before=_opt(m.get("before")), after=_opt(m.get("after")), change=_opt(m.get("change")),
                unit=_opt(m.get("unit")), kind=_enum(MetricKind, m.get("kind"), MetricKind.FACT),
                quote=str(m["quote"]).strip(), source_url=url,
            )
            metric = _verified_variant(metric, article.text)
            metrics.append(metric)
        out.append(Case(
            id=uuid.uuid4().hex[:12], first_seen=today, updated=today, level=level,
            country=country, region=region, municipality=municipality,
            organization=organization, sector=sector,
            industry=_opt(raw.get("industry")) or "", ai_technology=_opt(raw.get("ai_technology")) or "",
            title=title, summary=_opt(raw.get("summary")) or "",
            stage=_enum(Stage, raw.get("stage"), Stage.UNKNOWN), methodology=methodology,
            metrics=metrics, sources=[source.model_copy()],
        ))
    return out
