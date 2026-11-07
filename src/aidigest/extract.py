"""Извлечение кейсов внедрения ИИ из статьи с помощью LLM."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from aidigest.llm import LLMClient, LLMFormatError
from aidigest.methodology import CRITERIA, OTHER_CRITERION, infer_level, methodology_prompt, select_methodology
from aidigest.models import Article, Case, Metric, MetricKind, Sector, Stage
from aidigest.quotes import verify_metric
from aidigest.registry import SourceRegistry
from aidigest.urls import normalize_url

SYSTEM_PROMPT = f"""Ты аналитик, который собирает кейсы внедрения искусственного интеллекта.
Тебе дают текст одной статьи. Найди в нём конкретные кейсы внедрения ИИ.

Кейс — это конкретное внедрение: известно, КТО внедрил (организация, ведомство, регион, компания),
ГДЕ и ЧТО сделано (какая система на основе ИИ и для какой задачи).
НЕ являются кейсами: общие новости рынка, мнения и интервью без конкретного проекта, анонсы конференций,
обзоры технологий, планы «внедрить ИИ» без указания конкретного проекта. Если кейсов нет — верни {{"cases": []}}.

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
- criterion — критерий методики (см. ниже). Методика зависит от сектора и уровня:
  госсектор в России → Р-1; госсектор за рубежом → М-1; бизнес → бизнес-метрики.

ЗАПРЕЩЕНО придумывать, округлять или пересчитывать числа. Нет числа в тексте — нет показателя.
Охват (число пользователей, объектов, ведомств) — тоже показатель.

{methodology_prompt()}

Ответ — только JSON без пояснений, строго такого вида:
{{"cases": [{{"country": "", "region": null, "municipality": null, "organization": null,
  "sector": "госсектор", "industry": "", "ai_technology": "", "title": "", "summary": "", "stage": "неизвестно",
  "metrics": [{{"name": "", "criterion": "", "before": null, "after": null, "change": null,
               "unit": null, "kind": "факт", "quote": ""}}]}}]}}"""


def _enum(enum_cls, value: Any, default):
    try:
        return enum_cls(str(value).strip().lower() if value is not None else "")
    except ValueError:
        return default


def _criterion(value: Any, allowed: list[str]) -> str:
    v = str(value or "").strip().lower()
    for c in allowed:
        if c.lower() == v:
            return c
    return OTHER_CRITERION


def _opt(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def extract_cases(article: Article, llm: LLMClient, registry: SourceRegistry, today: date,
                  max_chars: int) -> list[Case]:
    user = f"Заголовок: {article.title}\nURL: {article.url}\n\nТекст статьи:\n{article.text[:max_chars]}"
    reply = llm.complete_json(SYSTEM_PROMPT, user)
    if not isinstance(reply, dict) or not isinstance(reply.get("cases"), list):
        raise LLMFormatError("ожидался объект с ключом cases")

    url = normalize_url(article.url)
    source = registry.to_source(article)
    out: list[Case] = []
    for raw in reply["cases"]:
        if not isinstance(raw, dict):
            raise LLMFormatError("элемент cases — не объект")
        country = _opt(raw.get("country")) or "неизвестно"
        region = _opt(raw.get("region"))
        level = infer_level(country, region)
        sector = _enum(Sector, raw.get("sector"), Sector.GOV)
        methodology = select_methodology(level, sector)
        metrics = []
        for m in raw.get("metrics") or []:
            if not isinstance(m, dict) or not _opt(m.get("quote")):
                continue
            metric = Metric(
                name=_opt(m.get("name")) or "показатель",
                criterion=_criterion(m.get("criterion"), CRITERIA[methodology]),
                before=_opt(m.get("before")), after=_opt(m.get("after")), change=_opt(m.get("change")),
                unit=_opt(m.get("unit")), kind=_enum(MetricKind, m.get("kind"), MetricKind.FACT),
                quote=str(m["quote"]).strip(), source_url=url,
            )
            metric.quote_verified = verify_metric(metric, article.text)
            metrics.append(metric)
        out.append(Case(
            id=uuid.uuid4().hex[:12], first_seen=today, updated=today, level=level,
            country=country, region=region, municipality=_opt(raw.get("municipality")),
            organization=_opt(raw.get("organization")), sector=sector,
            industry=_opt(raw.get("industry")) or "", ai_technology=_opt(raw.get("ai_technology")) or "",
            title=_opt(raw.get("title")) or article.title, summary=_opt(raw.get("summary")) or "",
            stage=_enum(Stage, raw.get("stage"), Stage.UNKNOWN), methodology=methodology,
            metrics=metrics, sources=[source.model_copy()],
        ))
    return out
