"""Однократная загрузка демонстрационных кейсов в PostgreSQL aiDigest."""
from __future__ import annotations

import argparse
import os
from datetime import date
from urllib.parse import urlsplit

from aidigest.db.engine import make_engine
from aidigest.methodology import select_methodology
from aidigest.models import Case, Level, Metric, Sector, Source, Stage
from aidigest.store import PgCaseStore, Store, StoreData


def source(url, title, published_at, *, official=False):
    return Source(
        url=url, domain=urlsplit(url).hostname, title=title, published_at=published_at,
        source_type="официальная" if official else "СМИ",
        reliability="высокая" if official else "средняя",
    )


def metric(source, name, criterion, quote, *, confirmed_by=None, **values):
    return Metric(
        name=name, criterion=criterion, quote=quote, source_url=source.url,
        quote_verified=True, confirmed_by=[confirmed_by.url] if confirmed_by else [],
        **values,
    )


def demo_cases() -> list[Case]:
    uk = source(
        "https://www.gov.uk/government/publications/microsoft-365-copilot-experiment-cross-government-findings-report/microsoft-365-copilot-experiment-cross-government-findings-report-html",
        "Microsoft 365 Copilot Experiment: Cross-Government Findings Report",
        "2025-06-02", official=True,
    )
    chelyabinsk = source(
        "https://www.chel.kp.ru/online/news/6831684/",
        "Цифровой рывок состоялся: Южный Урал стал одним из лидеров в стране по внедрению ИИ",
        "2026-02-21",
    )
    rbc = source(
        "https://chr.rbc.ru/chr/freenews/699851fb9a79474c7ec72bd1",
        "В Белгородской области используют ИИ для прогноза аварий на водоснабжении",
        "2026-02-20",
    )
    kazan = source(
        "https://kazanfirst.ru/news/v-tatarstane-zapustili-czifrovogo-pomoshhnika-gospromt",
        "В Татарстане запустили цифрового помощника «ГосПромт»",
        "2025-03-05",
    )
    comnews = source(
        "https://www.comnews.ru/content/237606/2025-02-05/2025-w06/1011/ii-pomoschnik-transformiruet-gosudarstvennoe-upravlenie-tatarstana",
        "ИИ-помощник трансформирует государственное управление Татарстана",
        "2025-02-05",
    )
    health = source(
        "https://minzdrav.gov.ru/regional_news/23363-iskusstvennyy-intellekt-obrabotal-bolee-milliona-izobrazheniy-grudnoy-kletki-patsientov-sverdlovskih-bolnits",
        "Искусственный интеллект обработал более миллиона изображений грудной клетки пациентов свердловских больниц",
        "2025-02-28", official=True,
    )
    channel4 = source(
        "https://www.channel4.ru/news/ii-obrabotal-million-snimkov-grudnoi-kletki-v-sverdlovskoi-oblasti",
        "Свердловские врачи в течении года использовали ИИ для работы",
        "2025-02-28",
    )

    entries = [
        dict(
            id="demo-uk-copilot", level=Level.WORLD, country="Великобритания",
            organization="Government Digital Service", stage=Stage.PILOT,
            industry="Государственное управление", ai_technology="Генеративный ИИ",
            title="Пилот Microsoft 365 Copilot у британских госслужащих",
            summary="Госслужащие тестировали ИИ-помощника для работы с документами, "
                    "перепиской и другими офисными задачами. Экономию времени оценивали по опросу участников.",
            sources=[uk],
            metrics=[
                metric(uk, "Средняя экономия времени, мин/день", "производительность и труд",
                       "Trial participants saved an average of 26 minutes a day",
                       change="26", unit="мин/день"),
                metric(uk, "Участники пилота", "реализуемость и масштаб",
                       "involving 20,000 government employees", after="20 000", unit="сотрудников"),
            ],
        ),
        dict(
            id="demo-chelyabinsk-traffic", level=Level.RF_REGIONS, country="Россия",
            region="Челябинская область", stage=Stage.DEPLOYED,
            industry="Транспорт", ai_technology="Компьютерное зрение",
            title="Компьютерное зрение для мониторинга дорог Челябинской области",
            summary="Система анализирует транспортный поток, фиксирует заторы и ДТП. "
                    "Показатель аварийности относится к местам установки пунктов учёта движения.",
            sources=[chelyabinsk, rbc],
            metrics=[
                metric(chelyabinsk, "Среднее время в заторе, мин", "скорость",
                       "среднее время пребывания автомобилистов в заторах сократилось в 2,5 раза — с 13 до 5 минут",
                       before="13", after="5", unit="мин", confirmed_by=rbc),
                metric(chelyabinsk, "Среднемесячное число ДТП", "прочее",
                       "со 161 до 122 аварий", before="161", after="122", unit="ДТП"),
            ],
        ),
        dict(
            id="demo-belgorod-water", level=Level.RF_REGIONS, country="Россия",
            region="Белгородская область", stage=Stage.DEPLOYED,
            industry="ЖКХ", ai_technology="Предиктивная аналитика, цифровой двойник",
            title="Цифровой двойник водоснабжения в Белгородской области",
            summary="ИИ оценивает риск аварий. Цифровой двойник помогает бригадам определить, "
                    "где перекрыть трубу и какие адреса затронет отключение.",
            sources=[rbc],
            metrics=[
                metric(rbc, "Доля длительных отключений воды", "скорость",
                       "сократила долю длительных отключений воды на 23%", change="−23%", unit="%"),
                metric(rbc, "Экономия регионального бюджета, руб.", "экономическая эффективность",
                       "сэкономила бюджету региона более 9 млн руб.", change="более 9 млн", unit="руб."),
            ],
        ),
        dict(
            id="demo-tatarstan-gosprompt", level=Level.RF_REGIONS, country="Россия",
            region="Республика Татарстан", stage=Stage.DEPLOYED,
            industry="Государственное управление", ai_technology="Большие языковые модели",
            title="ИИ-помощник «ГосПромпт» для госслужащих Татарстана",
            summary="На раннем этапе сервис помогал госслужащим работать с документами "
                    "и анализировать данные. Числа в карточке описывают охват на старте.",
            sources=[kazan, comnews],
            metrics=[
                metric(kazan, "Госслужащие на старте", "прочее",
                       "426 госслужащими из 25 ведомств республики", after="426", unit="сотрудников",
                       confirmed_by=comnews),
                metric(kazan, "Ведомства на старте", "прочее",
                       "426 госслужащими из 25 ведомств республики", after="25", unit="ведомств",
                       confirmed_by=comnews),
            ],
        ),
        dict(
            id="demo-sverdlovsk-radiology", level=Level.SVERDLOVSK, country="Россия",
            region="Свердловская область", organization="Минздрав Свердловской области",
            stage=Stage.SCALING, industry="Здравоохранение", ai_technology="Компьютерное зрение",
            title="ИИ-анализ снимков грудной клетки в Свердловской области",
            summary="Система «Третье Мнение» отмечает подозрительные участки снимков и помогает "
                    "врачам-рентгенологам расставлять приоритеты. После пилота систему начали масштабировать.",
            sources=[health, channel4],
            metrics=[
                metric(health, "Обработанные снимки грудной клетки", "прочее",
                       "обработано более миллиона цифровых изображений грудной клетки",
                       after="более 1 млн", unit="снимков", confirmed_by=channel4),
                metric(health, "Время обработки исследования, мин", "скорость",
                       "Обработка одного исследования занимает менее минуты", after="менее 1", unit="мин"),
                metric(health, "Подключённые учреждения", "прочее",
                       "свыше 160 учреждений здравоохранения Среднего Урала",
                       after="более 160", unit="учреждений", confirmed_by=channel4),
            ],
        ),
    ]
    today = date.today()
    cases = []
    for entry in entries:
        entry["summary"] = "Демонстрационный кейс, добавленный вручную. " + entry["summary"]
        case = Case(
            **entry, first_seen=today, updated=today, sector=Sector.GOV,
            methodology=select_methodology(entry["level"], Sector.GOV),
            confirmation_attempts=1,
        )
        case.recompute_status()
        cases.append(case)
    return cases


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
