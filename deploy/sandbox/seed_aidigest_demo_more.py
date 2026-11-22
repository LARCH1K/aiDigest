"""Однократная загрузка демонстрационных кейсов в PostgreSQL aiDigest."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date

from aidigest.db.engine import make_engine
from aidigest.methodology import select_methodology
from aidigest.models import Case, Level, Sector
from aidigest.store import PgCaseStore, StoreData


def demo_cases() -> list[Case]:
    today = date.today()
    cases = []
    for entry in json.loads(CASES_JSON):
        entry["summary"] = "Демонстрационный кейс, добавленный вручную. " + entry["summary"]
        case = Case(
            **entry, first_seen=today, updated=today,
            methodology=select_methodology(Level(entry["level"]), Sector(entry["sector"])),
            confirmation_attempts=1,
        )
        case.recompute_status()
        cases.append(case)
    return cases


CASES_JSON = r"""
[
  {
    "id": "demo-klarna-support",
    "level": "мир",
    "country": "Швеция",
    "sector": "бизнес",
    "stage": "внедрён",
    "organization": "Klarna",
    "industry": "Финтех",
    "ai_technology": "Генеративный ИИ",
    "title": "ИИ-ассистент в клиентской поддержке Klarna",
    "summary": "Компания запустила чат-ассистента в нескольких странах. В карточке приведены показатели первого месяца по данным поставщика технологии.",
    "sources": [
      {
        "url": "https://openai.com/index/klarna/",
        "title": "Klarna’s AI assistant does the work of 700 full-time agents",
        "published_at": null,
        "domain": "openai.com",
        "source_type": "кейсы",
        "reliability": "средняя"
      }
    ],
    "metrics": [
      {
        "source_url": "https://openai.com/index/klarna/",
        "name": "Время решения вопроса, мин",
        "criterion": "время процесса",
        "quote": "less than 2 mins compared to 11 mins previously",
        "quote_verified": true,
        "before": "11",
        "after": "менее 2",
        "unit": "мин"
      },
      {
        "source_url": "https://openai.com/index/klarna/",
        "name": "Диалоги ассистента за первый месяц",
        "criterion": "прочее",
        "quote": "The AI assistant has had 2.3 million conversations",
        "quote_verified": true,
        "after": "2,3 млн",
        "unit": "диалогов"
      }
    ]
  },
  {
    "id": "demo-google-cooling",
    "level": "мир",
    "country": "Не указана",
    "sector": "бизнес",
    "stage": "внедрён",
    "organization": "Google, DeepMind",
    "industry": "Центры обработки данных",
    "ai_technology": "Машинное обучение",
    "title": "ИИ-управление охлаждением дата-центров Google",
    "summary": "Система управляет оборудованием по данным датчиков. Экономию оценивали на контуре охлаждения относительно исторической базовой линии.",
    "sources": [
      {
        "url": "https://deepmind.google/blog/safety-first-ai-for-autonomous-data-centre-cooling-and-industrial-control/",
        "title": "Safety-first AI for autonomous data centre cooling and industrial control",
        "published_at": "2018-08-17",
        "domain": "deepmind.google",
        "source_type": "кейсы",
        "reliability": "средняя"
      }
    ],
    "metrics": [
      {
        "source_url": "https://deepmind.google/blog/safety-first-ai-for-autonomous-data-centre-cooling-and-industrial-control/",
        "name": "Средняя экономия энергии на охлаждении",
        "criterion": "операционные затраты",
        "quote": "consistent energy savings of around 30 percent on average",
        "quote_verified": true,
        "change": "около 30%",
        "unit": "%"
      }
    ]
  },
  {
    "id": "demo-sweden-masai",
    "level": "мир",
    "country": "Швеция",
    "sector": "госсектор",
    "stage": "пилот",
    "organization": "Исследовательская группа MASAI",
    "industry": "Здравоохранение",
    "ai_technology": "Компьютерное зрение",
    "title": "Испытание ИИ в маммографическом скрининге MASAI",
    "summary": "В шведской программе скрининга сравнили чтение снимков с поддержкой ИИ и стандартное двойное чтение. Результат относится к промежуточному анализу исследования.",
    "sources": [
      {
        "url": "https://pubmed.ncbi.nlm.nih.gov/37541274/",
        "title": "MASAI: clinical safety analysis of a randomised screening accuracy study",
        "published_at": "2023-08-01",
        "domain": "pubmed.ncbi.nlm.nih.gov",
        "source_type": "статистика",
        "reliability": "высокая"
      }
    ],
    "metrics": [
      {
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/37541274/",
        "name": "Снижение нагрузки по чтению снимков",
        "criterion": "производительность и труд",
        "quote": "The screen-reading workload was reduced by 44·3% using AI",
        "quote_verified": true,
        "change": "−44,3%",
        "unit": "%"
      }
    ]
  },
  {
    "id": "demo-bryansk-forest",
    "level": "регионы РФ",
    "country": "Россия",
    "region": "Брянская область",
    "sector": "госсектор",
    "stage": "внедрён",
    "organization": "Управление лесами Брянской области",
    "industry": "Лесное хозяйство",
    "ai_technology": "Компьютерное зрение",
    "title": "Раннее обнаружение лесных пожаров в Брянской области",
    "summary": "Система «Лесохранитель» помогает диспетчерам обнаруживать задымление по видеопотоку и координировать выезд расчётов. Показатели приведены на дату публикации за период с начала года.",
    "sources": [
      {
        "url": "https://rosleshoz.gov.ru/news/tsfo/lesokhranitel-na-strazhe-bryanskikh-lesov/",
        "title": "«Лесохранитель» на страже брянских лесов",
        "published_at": "2026-08-11",
        "domain": "rosleshoz.gov.ru",
        "source_type": "официальная",
        "reliability": "высокая"
      },
      {
        "url": "https://rosleshoz.gov.ru/news/tsfo/iskusstvennyy-intellekt-na-zashchite-lesov-ot-pozharov/",
        "title": "Искусственный интеллект на защите лесов от пожаров",
        "published_at": null,
        "domain": "rosleshoz.gov.ru",
        "source_type": "официальная",
        "reliability": "высокая"
      }
    ],
    "metrics": [
      {
        "source_url": "https://rosleshoz.gov.ru/news/tsfo/lesokhranitel-na-strazhe-bryanskikh-lesov/",
        "name": "Обнаруженные лесные пожары",
        "criterion": "прочее",
        "quote": "В 39 случаях система обнаружила лесные пожары",
        "quote_verified": true,
        "after": "39",
        "unit": "пожаров"
      },
      {
        "source_url": "https://rosleshoz.gov.ru/news/tsfo/lesokhranitel-na-strazhe-bryanskikh-lesov/",
        "name": "Среднее время до прибытия расчёта, мин",
        "criterion": "скорость",
        "quote": "до прибытия пожарных расчётов на место составило 37 минут",
        "quote_verified": true,
        "after": "37",
        "unit": "мин"
      }
    ]
  },
  {
    "id": "demo-mosreg-waste",
    "level": "регионы РФ",
    "country": "Россия",
    "region": "Московская область",
    "sector": "госсектор",
    "stage": "внедрён",
    "organization": "Минэкологии Московской области",
    "industry": "Экология",
    "ai_technology": "ИИ-анализ данных мониторинга",
    "title": "Контроль незаконных свалок стройотходов в Подмосковье",
    "summary": "Система «ОССиГ-контроль» помогает отслеживать перевозку строительных отходов и выявлять незаконные сбросы. В карточке приведены итоги регионального министерства за первые девять месяцев года.",
    "sources": [
      {
        "url": "https://mosreg.ru/sobytiya/novosti/organy/ministerstvo-ekologii-i-prirodopolzovaniya/v-podmoskove-pochti-vdvoe-sokratilos-chislo-novykh-svalok-stroiotkhodov-blagodarya-sisteme-ossig-kontrol",
        "title": "В Подмосковье почти вдвое сократилось число новых свалок стройотходов благодаря системе «ОССиГ-контроль»",
        "published_at": "2026-10-23",
        "domain": "mosreg.ru",
        "source_type": "официальная",
        "reliability": "высокая"
      }
    ],
    "metrics": [
      {
        "source_url": "https://mosreg.ru/sobytiya/novosti/organy/ministerstvo-ekologii-i-prirodopolzovaniya/v-podmoskove-pochti-vdvoe-sokratilos-chislo-novykh-svalok-stroiotkhodov-blagodarya-sisteme-ossig-kontrol",
        "name": "Доля ликвидированных свалок среди выявленных",
        "criterion": "прочее",
        "quote": "ликвидировано 99 % выявленных свалок",
        "quote_verified": true,
        "after": "99%",
        "unit": "%"
      },
      {
        "source_url": "https://mosreg.ru/sobytiya/novosti/organy/ministerstvo-ekologii-i-prirodopolzovaniya/v-podmoskove-pochti-vdvoe-sokratilos-chislo-novykh-svalok-stroiotkhodov-blagodarya-sisteme-ossig-kontrol",
        "name": "Выявленные свалки стройотходов",
        "criterion": "прочее",
        "quote": "в регионе выявили 293 несанкционированные свалки строительных отходов",
        "quote_verified": true,
        "after": "293",
        "unit": "свалок"
      }
    ]
  },
  {
    "id": "demo-severstal-staffing",
    "level": "регионы РФ",
    "country": "Россия",
    "region": "Вологодская область",
    "municipality": "Череповец",
    "sector": "бизнес",
    "stage": "внедрён",
    "organization": "Северсталь",
    "industry": "Металлургия",
    "ai_technology": "Компьютерное зрение",
    "title": "Оценка загрузки производственных участков «Северстали»",
    "summary": "Система анализирует видео из цеха и распознаёт производственные операции. По этим данным предприятие перераспределяет персонал и уточняет сменные задания. Факт и прогноз приведены по оценке компании на дату интервью.",
    "sources": [
      {
        "url": "https://www.osp.ru/articles/2025/0402/13059355",
        "title": "«Северсталь»: ИИ оптимизирует загрузку персонала",
        "published_at": "2025-04-02",
        "domain": "www.osp.ru",
        "source_type": "СМИ",
        "reliability": "средняя"
      }
    ],
    "metrics": [
      {
        "source_url": "https://www.osp.ru/articles/2025/0402/13059355",
        "name": "Экономический эффект за 2024 год, руб.",
        "criterion": "операционные затраты",
        "quote": "В 2024 году фактический экономический эффект составил 21 млн руб.",
        "quote_verified": true,
        "after": "21 млн",
        "unit": "руб."
      },
      {
        "source_url": "https://www.osp.ru/articles/2025/0402/13059355",
        "name": "Прогноз экономического эффекта на 2025 год, руб.",
        "criterion": "операционные затраты",
        "quote": "ожидается увеличение эффекта до 58 млн руб.",
        "quote_verified": true,
        "after": "58 млн",
        "unit": "руб.",
        "kind": "план"
      }
    ]
  },
  {
    "id": "demo-evraz-wheel-marking",
    "level": "Свердловская область",
    "country": "Россия",
    "region": "Свердловская область",
    "municipality": "Нижний Тагил",
    "sector": "бизнес",
    "stage": "внедрён",
    "organization": "ЕВРАЗ НТМК",
    "industry": "Металлургия",
    "ai_technology": "Машинное зрение",
    "title": "Распознавание маркировки колёс и бандажей на ЕВРАЗ НТМК",
    "summary": "Камеры читают горячую маркировку, а распознанный номер записывается в цифровой паспорт изделия. Годовой эффект в публикациях приведён как оценка.",
    "sources": [
      {
        "url": "https://mstrok.ru/news/evraz-ntmk-vnedryaet-sistemu-mashinnogo-zreniya-dlya-proizvodstva-kolyos-i-bandazhey",
        "title": "ЕВРАЗ НТМК внедряет систему машинного зрения для производства колёс и бандажей",
        "published_at": "2026-08-24",
        "domain": "mstrok.ru",
        "source_type": "СМИ",
        "reliability": "средняя"
      },
      {
        "url": "https://ura.news/news/1053121948",
        "title": "ЕВРАЗ НТМК внедрил машинное зрение для производства колес и бандажей",
        "published_at": "2026-08-27",
        "domain": "ura.news",
        "source_type": "СМИ",
        "reliability": "средняя"
      }
    ],
    "metrics": [
      {
        "source_url": "https://mstrok.ru/news/evraz-ntmk-vnedryaet-sistemu-mashinnogo-zreniya-dlya-proizvodstva-kolyos-i-bandazhey",
        "name": "Ожидаемый годовой эффект, руб.",
        "criterion": "операционные затраты",
        "quote": "ожидаемая экономическая выгода составляет около 9 млн рублей ежегодно",
        "quote_verified": true,
        "after": "около 9 млн",
        "unit": "руб./год",
        "kind": "план",
        "confirmed_by": [
          "https://ura.news/news/1053121948"
        ]
      },
      {
        "source_url": "https://mstrok.ru/news/evraz-ntmk-vnedryaet-sistemu-mashinnogo-zreniya-dlya-proizvodstva-kolyos-i-bandazhey",
        "name": "Инвестиции в проект, руб.",
        "criterion": "прочее",
        "quote": "Инвестиции в проект превысили 7,2 млн рублей",
        "quote_verified": true,
        "after": "более 7,2 млн",
        "unit": "руб.",
        "confirmed_by": [
          "https://ura.news/news/1053121948"
        ]
      }
    ]
  },
  {
    "id": "demo-sverdlovsk-voice-notes",
    "level": "Свердловская область",
    "country": "Россия",
    "region": "Свердловская область",
    "municipality": "Екатеринбург",
    "sector": "госсектор",
    "stage": "пилот",
    "organization": "Минздрав Свердловской области",
    "industry": "Здравоохранение",
    "ai_technology": "Распознавание речи",
    "title": "Голосовое заполнение медкарт в свердловских поликлиниках",
    "summary": "На пилотных площадках врач диктует данные, а помощник переносит их в карту. Оснащение кабинетов микрофонами описано как план расширения.",
    "sources": [
      {
        "url": "https://xn--b1ag8a.xn--p1ai/news/36490",
        "title": "Успешный опыт совершенствования медпомощи распространят на все свердловские больницы",
        "published_at": null,
        "domain": "xn--b1ag8a.xn--p1ai",
        "source_type": "официальная",
        "reliability": "высокая"
      },
      {
        "url": "https://ku66.ru/news/vrach_govorit_ii_zapolnyaet_kartu_v_sverdlovskoj_oblasti_mikrofonami_osnastyat_981_kabinet",
        "title": "Врач говорит — ИИ заполняет карту: в Свердловской области микрофонами оснастят 981 кабинет",
        "published_at": "2026-10-09",
        "domain": "ku66.ru",
        "source_type": "СМИ",
        "reliability": "средняя"
      }
    ],
    "metrics": [
      {
        "source_url": "https://xn--b1ag8a.xn--p1ai/news/36490",
        "name": "Время заполнения медицинской карты",
        "criterion": "скорость",
        "quote": "сократило время заполнения медицинской карты на треть",
        "quote_verified": true,
        "change": "на треть меньше"
      },
      {
        "source_url": "https://xn--b1ag8a.xn--p1ai/news/36490",
        "name": "Кабинеты в плане оснащения",
        "criterion": "прочее",
        "quote": "планируется оснастить 981 кабинет",
        "quote_verified": true,
        "after": "981",
        "unit": "кабинетов",
        "kind": "план",
        "confirmed_by": [
          "https://ku66.ru/news/vrach_govorit_ii_zapolnyaet_kartu_v_sverdlovskoj_oblasti_mikrofonami_osnastyat_981_kabinet"
        ]
      }
    ]
  },
  {
    "id": "demo-yekaterinburg-rovers",
    "level": "Свердловская область",
    "country": "Россия",
    "region": "Свердловская область",
    "municipality": "Екатеринбург",
    "sector": "бизнес",
    "stage": "масштабирование",
    "organization": "Яндекс Лавка",
    "industry": "Логистика",
    "ai_technology": "Автономная навигация, компьютерное зрение",
    "title": "Автономная доставка заказов роверами в Екатеринбурге",
    "summary": "Роботы доставляют заказы в отдельных районах города. Бортовые модели распознают дорожную обстановку, а расширение сети указано как план компании.",
    "sources": [
      {
        "url": "https://autonomy.yandex.ru/blog/robodostavka-masshtabiruetsya-na-urale-rovery-yandeksa-nachali-privozit-zakazy-zhitelyam-ekaterinburga",
        "title": "Рободоставка масштабируется на Урале — роверы Яндекса начали привозить заказы жителям Екатеринбурга",
        "published_at": "2026-11-10",
        "domain": "autonomy.yandex.ru",
        "source_type": "кейсы",
        "reliability": "средняя"
      },
      {
        "url": "https://www.interfax.ru/russia/1127997",
        "title": "«Яндекс» запустил рободоставку в Екатеринбурге",
        "published_at": "2026-11-10",
        "domain": "www.interfax.ru",
        "source_type": "СМИ",
        "reliability": "средняя"
      }
    ],
    "metrics": [
      {
        "source_url": "https://autonomy.yandex.ru/blog/robodostavka-masshtabiruetsya-na-urale-rovery-yandeksa-nachali-privozit-zakazy-zhitelyam-ekaterinburga",
        "name": "Дарксторы с доставкой на старте",
        "criterion": "прочее",
        "quote": "Роверы привезут заказ из шести дарксторов Яндекс Лавки",
        "quote_verified": true,
        "after": "6",
        "unit": "дарксторов"
      },
      {
        "source_url": "https://autonomy.yandex.ru/blog/robodostavka-masshtabiruetsya-na-urale-rovery-yandeksa-nachali-privozit-zakazy-zhitelyam-ekaterinburga",
        "name": "Целевой охват дарксторов",
        "criterion": "прочее",
        "quote": "дарксторов Лавки планируем довести до 20",
        "quote_verified": true,
        "after": "20",
        "unit": "дарксторов",
        "kind": "план",
        "confirmed_by": [
          "https://www.interfax.ru/russia/1127997"
        ]
      }
    ]
  }
]
"""


def seed_cases(store: Store, cases: list[Case]) -> int:
    with store.write_lock() as locked:
        existing = {case.id for case in locked.load().cases}
        pending = [case for case in cases if case.id not in existing]
        if pending:
            locked.save(StoreData(cases=pending))
        saved = {case.id for case in locked.load().cases}
        if not all(case.id in saved for case in cases):
            raise RuntimeError("Часть демонстрационных кейсов отсутствует в базе.")
    return len(pending)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="проверить модели без подключения к базе")
    args = parser.parse_args()
    cases = demo_cases()
    if args.check:
        for case in cases:
            print(f"{case.level}: {case.title} ({len(case.metrics)} показателей)")
        return

    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("Задайте DATABASE_URL для базы стенда.")
    engine = make_engine()
    try:
        added = seed_cases(PgCaseStore(engine), cases)
    finally:
        engine.dispose()
    print(f"Добавлено: {added}. Демонстрационных кейсов в базе: {len(cases)}.")


if __name__ == "__main__":
    main()
