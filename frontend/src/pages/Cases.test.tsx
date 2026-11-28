import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, useLocation } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { App } from "../App";
import type { CaseRow, Metric } from "../types";

const metric: Metric = {
  name: "Время проверки", criterion: "скорость", before: "12 мин", after: "4 мин", change: null,
  unit: "мин", kind: "факт", quote: "Проверка заняла 4 минуты.", source_url: "https://report.example",
  quote_verified: false, confirmed_by: [], conflicting_values: [],
};

const row: CaseRow = {
  id: "water", title: "Контроль воды", level: "мир", country: "Япония", region: null,
  organization: "Водоканал", industry: "ЖКХ", stage: "пилот", first_seen: "2026-11-05",
  status: "один_источник", status_label: "без независимого подтверждения", status_class: "warn",
  headline: "Время 12 → 4 мин", headline_unverified: true, reliability: "низкая",
  reliability_label: "низкая", reliability_class: "warn", flags: [],
  updated: "2026-11-10", metrics: [metric], plan_links: [],
};

function setup(path: string, cases: (url: string) => Promise<Response>, metaStatus = 200) {
  const fetch = vi.fn(async (url: string) => {
    if (url === "/api/me") return Response.json({ authenticated: true, login_required: false });
    if (url === "/api/meta") {
      if (metaStatus !== 200) return Response.json({ detail: "Справочник недоступен" }, { status: metaStatus });
      return Response.json({
        levels: ["мир", "регионы РФ", "Свердловская область"],
        statuses: [{ value: "один_источник", label: "без независимого подтверждения", class: "warn" }],
        reliability: [{ value: "низкая", label: "низкая" }],
        criteria: [{ value: "скорость", label: "Скорость" }],
        industries: [{ value: "жкх", label: "ЖКХ" }],
        plan_indicators: [{
          value: "1.2", label: "Подготовка проектов ответов с ИИ",
        }],
        flag_help: {},
      });
    }
    return cases(url);
  });
  vi.stubGlobal("fetch", fetch);
  function Address() {
    return <output aria-label="Фильтры в адресе">{useLocation().search}</output>;
  }
  render(
    <MemoryRouter initialEntries={[path]}>
      <Link to="/?q=новый">Другой поиск</Link>
      <App />
      <Address />
    </MemoryRouter>,
  );
  return { fetch, user: userEvent.setup() };
}

it("фильтры из адреса уходят в запрос, а посторонний параметр исключается", async () => {
  const { fetch } = setup("/?level=мир&doubtful=1&extra=1", async () =>
    Response.json({ total: 1, updated: null, cases: [] }),
  );
  expect(await screen.findByRole("heading", { name: "Ничего не нашлось" })).toBeVisible();
  expect(fetch.mock.calls.map(([url]) => url)).toContain(
    "/api/cases?level=%D0%BC%D0%B8%D1%80&doubtful=1",
  );
  expect(await screen.findByLabelText("Уровень")).toHaveValue("мир");
  expect(screen.getByLabelText("Только с цифрами")).not.toBeChecked();
  expect(screen.getByLabelText("Скрыть сомнительные")).toBeChecked();
});

it("при ошибке справочника действительный фильтр из адреса по-прежнему загружает таблицу", async () => {
  const { fetch } = setup("/?level=мир", async () =>
    Response.json({ total: 1, updated: null, cases: [row] }), 500,
  );
  expect(await screen.findByRole("table")).toBeVisible();
  expect(screen.getByRole("link", { name: row.title })).toBeVisible();
  expect(fetch.mock.calls.map(([url]) => url)).toContain("/api/cases?level=%D0%BC%D0%B8%D1%80");
});

it.each([
  ["level", "РФ", "Уровень"],
  ["status", "проверено", "Подтверждение"],
  ["reliability", "любая", "Достоверность"],
])("старый фильтр %s остаётся видимым и даёт пустой результат без ошибки API", async (name, value, label) => {
  const { fetch, user } = setup("/?" + new URLSearchParams({ [name]: value }), async (url) => {
    const invalid = new URL(url, "https://aidigest.test").searchParams.has(name);
    return invalid
      ? Response.json({ detail: "Недопустимое значение" }, { status: 422 })
      : Response.json({ total: 1, updated: null, cases: [row] });
  });
  expect(await screen.findByRole("heading", { name: "Ничего не нашлось" })).toBeVisible();
  expect(screen.getByLabelText(label)).toHaveValue(value);
  expect(fetch.mock.calls.map(([url]) => url)).toContain("/api/cases?");
  expect(screen.queryByRole("table")).toBeNull();
  await user.click(screen.getByRole("link", { name: "Сбросить" }));
  expect(await screen.findByRole("link", { name: row.title })).toBeVisible();
  expect(screen.getByLabelText(label)).toHaveValue("");
});

it("отправка формы обновляет адрес и запрос, сброс возвращает фильтры по умолчанию", async () => {
  const { fetch, user } = setup("/", async () => Response.json({ total: 0, updated: null, cases: [] }));
  await user.type(await screen.findByLabelText("Поиск"), "вода & свет");
  await user.selectOptions(screen.getByLabelText("Уровень"), "мир");
  await user.selectOptions(screen.getByLabelText("Подтверждение"), "один_источник");
  await user.selectOptions(screen.getByLabelText("Достоверность"), "низкая");
  await user.click(screen.getByLabelText("Только с цифрами"));
  await user.click(screen.getByLabelText("Скрыть сомнительные"));
  await user.click(screen.getByRole("button", { name: "Показать" }));

  const search = screen.getByLabelText("Фильтры в адресе").textContent!;
  expect(Object.fromEntries(new URLSearchParams(search))).toEqual({
    q: "вода & свет", level: "мир", status: "один_источник",
    reliability: "низкая", metrics: "1", doubtful: "1",
  });
  expect(fetch.mock.calls.map(([url]) => url)).toContain("/api/cases" + search);

  await user.click(screen.getByRole("link", { name: "Сбросить" }));
  expect(screen.getByLabelText("Фильтры в адресе").textContent).toBe("");
  expect(screen.getByLabelText("Поиск")).toHaveValue("");
  expect(screen.getByLabelText("Только с цифрами")).not.toBeChecked();
  expect(screen.getByLabelText("Скрыть сомнительные")).not.toBeChecked();
});

it("пустая база — понятный текст, а не пустая таблица", async () => {
  setup("/", async () => Response.json({ total: 0, updated: null, cases: [] }));
  expect(await screen.findByRole("heading", { name: "Кейсов пока нет" })).toBeVisible();
  expect(screen.getByRole("link", { name: "«Запуск сбора»" })).toHaveAttribute("href", "/run");
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.getByRole("link", { name: "Выгрузить в Excel" }))
    .toHaveAttribute("href", "/api/export.xlsx");
});

it("качественный кейс Ливерпуля виден до включения фильтра цифр", async () => {
  const liverpool = { ...row, id: "liverpool", title: "Кейс Ливерпуля", metrics: [] };
  const { user } = setup("/", async (url) => {
    const withNumbers = new URL(url, "https://aidigest.test").searchParams.get("metrics") === "1";
    return Response.json({ total: 2, updated: null, cases: withNumbers ? [row] : [row, liverpool] });
  });
  expect(await screen.findByRole("link", { name: liverpool.title })).toBeVisible();
  const checkbox = screen.getByLabelText("Только с цифрами");
  expect(checkbox).not.toBeChecked();
  await user.click(checkbox);
  await user.click(screen.getByRole("button", { name: "Показать" }));
  expect(await screen.findByRole("link", { name: row.title })).toBeVisible();
  expect(screen.queryByRole("link", { name: liverpool.title })).toBeNull();
  expect(screen.getByLabelText("Только с цифрами")).toBeChecked();
});

it("непроверенный показатель помечен, заголовок сортирует строки", async () => {
  const { user } = setup("/", async () => Response.json({
    total: 2, updated: "2026-11-05T09:07:00Z",
    cases: [row, { ...row, id: "z", title: "Анализ воздуха", metrics: [] }],
  }));
  expect(await screen.findByTitle("Цифра не найдена в тексте статьи — проверьте по ссылке"))
    .toHaveTextContent("⚠");
  expect(screen.getByRole("link", { name: row.title })).toHaveAttribute("href", "/case/water");
  const header = screen.getByRole("columnheader", { name: "Кейс" });
  await user.click(header);
  expect(header).toHaveAttribute("aria-sort", "ascending");
  expect(screen.getAllByRole("row")[1]).toHaveTextContent("Анализ воздуха");
});

it("сортировка по кейсу учитывает организацию, а при равенстве сохраняет прежний порядок", async () => {
  const { fetch, user } = setup("/", async () => Response.json({
    total: 3, updated: null,
    cases: [
      { ...row, id: "z", organization: "Ясень", updated: "2026-11-01" },
      { ...row, id: "a", organization: "Альфа", updated: "2026-11-03" },
      { ...row, id: "b", organization: "Альфа", updated: "2026-11-02" },
    ],
  }));
  await user.click(await screen.findByRole("columnheader", { name: "Обновлён" }));
  const title = screen.getByRole("columnheader", { name: "Кейс" });
  await user.click(title);
  const ids = () => screen.getAllByRole("link", { name: row.title }).map((link) => link.getAttribute("href"));
  expect(ids()).toEqual(["/case/b", "/case/a", "/case/z"]);
  await user.click(title);
  expect(ids()).toEqual(["/case/z", "/case/b", "/case/a"]);
  expect(fetch.mock.calls.map(([url]) => url).filter((url) => url.startsWith("/api/cases?")))
    .toEqual(["/api/cases?"]);
});

it("обновление показано календарной датой и сортируется хронологически", async () => {
  const { user } = setup("/", async () => Response.json({
    total: 2, updated: null,
    cases: [row, { ...row, id: "z", title: "Анализ воздуха", updated: "2026-10-29T12:00:00Z" }],
  }));
  const header = await screen.findByRole("columnheader", { name: "Обновлён" });
  expect(screen.queryByRole("columnheader", { name: "В базе с" })).toBeNull();
  expect(screen.getByText("10.11.2026")).toBeVisible();
  expect(screen.getByText("29.10.2026")).toBeVisible();
  await user.click(header);
  expect(screen.getAllByRole("row")[1]).toHaveTextContent("Анализ воздуха");
});

it("показатели и связи с нацпланом раскрываются после трёх строк", async () => {
  const { user } = setup("/", async () => Response.json({
    total: 2, updated: null,
    cases: [{
      ...row,
      metrics: [
        metric,
        { ...metric, name: "Время расчёта", before: null, after: null, change: "−6 мин", quote_verified: true },
        { ...metric, name: "Число ошибок", before: "5%", after: "2%", quote_verified: true },
        { ...metric, name: "Пропускная способность", before: null, after: "150 заявок", quote_verified: true },
      ],
      plan_links: [{
        indicator_id: "1.2", explanation: "ИИ готовит проекты ответов.", source_url: metric.source_url,
        quote: "ИИ формирует проект ответа на обращение гражданина.",
      }],
    }, { ...row, id: "z", title: "Без показателей", metrics: [] }],
  }));
  expect(await screen.findByRole("columnheader", { name: "Показатели" })).toBeVisible();
  expect(screen.queryByRole("columnheader", { name: "Главная цифра" })).toBeNull();
  expect(screen.getAllByRole("columnheader")[0]).toHaveTextContent("Кейс");
  expect(screen.getByText(/Время проверки.*12 мин → 4 мин/)).toBeVisible();
  expect(screen.getByText(/Время расчёта.*−6 мин/)).toBeVisible();
  expect(screen.queryByText(/Пропускная способность/)).toBeNull();
  const display = within(screen.getByRole("row", { name: /Контроль воды/ }));
  expect(display.queryByText("Подготовка проектов ответов с ИИ")).toBeNull();
  const expand = screen.getByRole("button", { name: "Ещё 2" });
  expect(expand).toHaveAttribute("aria-expanded", "false");
  await user.click(expand);
  expect(screen.getByText(/Пропускная способность.*150 заявок/)).toBeVisible();
  expect(display.getByText("Подготовка проектов ответов с ИИ")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Свернуть" }));
  expect(screen.queryByText(/Пропускная способность/)).toBeNull();
  expect(within(screen.getByRole("row", { name: /Без показателей/ })).getByText("—")).toBeVisible();
});

it.each([
  ["", false],
  ["&metrics=1", true],
  ["&metrics=0", false],
])("URL сохраняет оба фильтра и учитывает параметр цифр %s", async (metrics, checked) => {
  const { fetch } = setup("/?criterion=скорость&plan=1.2&level=мир" + metrics, async () =>
    Response.json({ total: 1, updated: null, cases: [row] }));
  expect(await screen.findByLabelText("Тип эффекта")).toHaveValue("скорость");
  expect(screen.getByLabelText("Показатель нацплана")).toHaveValue("1.2");
  expect((screen.getByLabelText("Только с цифрами") as HTMLInputElement).checked).toBe(checked);
  expect(await screen.findByRole("table")).toBeVisible();
  const request = fetch.mock.calls.find(([url]) => url.startsWith("/api/cases?"))![0];
  expect(Object.fromEntries(new URL(request, "https://aidigest.test").searchParams)).toEqual({
    criterion: "скорость", plan: "1.2", level: "мир", ...(metrics ? { metrics: checked ? "1" : "0" } : {}),
  });
});

it("отрасль показывается первой и передаётся вместе с выбранным уровнем", async () => {
  const { fetch, user } = setup("/", async () => Response.json({ total: 1, cases: [row] }));
  const industry = await screen.findByLabelText("Отрасль");
  expect(screen.getAllByRole("combobox")[0]).toBe(industry);
  await user.selectOptions(industry, "жкх");
  await user.selectOptions(screen.getByLabelText("Уровень"), "мир");
  await user.click(screen.getByRole("button", { name: "Показать" }));
  const requests = fetch.mock.calls.map(([url]) => url).filter((url) => url.startsWith("/api/cases?"));
  const query = new URLSearchParams(requests.at(-1)?.split("?")[1]);
  expect(query.get("industry")).toBe("жкх");
  expect(query.get("level")).toBe("мир");
});

it("ссылка с названием отрасли в другом регистре сохраняет фильтр", async () => {
  const { fetch } = setup("/?industry=%20ЖКХ%20", async () => Response.json({ total: 1, cases: [row] }));
  expect(await screen.findByLabelText("Отрасль")).toHaveValue("жкх");
  expect(await screen.findByRole("link", { name: "Контроль воды" })).toBeVisible();
  expect(fetch.mock.calls.some(([url]) => new URL(url, "https://example.test").searchParams.get("industry") === "жкх"))
    .toBe(true);
});

it("выбор показателя нацплана сохраняет явное включение фильтра цифр", async () => {
  const { fetch, user } = setup("/", async () => Response.json({ total: 1, updated: null, cases: [row] }));
  const plan = await screen.findByLabelText("Показатель нацплана");
  const metrics = screen.getByLabelText("Только с цифрами");
  await user.selectOptions(plan, "1.2");
  expect(metrics).not.toBeChecked();
  await user.selectOptions(plan, "");
  expect(metrics).not.toBeChecked();
  await user.selectOptions(plan, "1.2");
  await user.selectOptions(screen.getByLabelText("Тип эффекта"), "скорость");
  await user.click(screen.getByRole("button", { name: "Показать" }));
  expect(Object.fromEntries(new URLSearchParams(screen.getByLabelText("Фильтры в адресе").textContent!)))
    .toEqual({ criterion: "скорость", plan: "1.2" });
  await user.click(screen.getByLabelText("Только с цифрами"));
  await user.click(screen.getByRole("button", { name: "Показать" }));
  const search = screen.getByLabelText("Фильтры в адресе").textContent!;
  expect(Object.fromEntries(new URLSearchParams(search))).toEqual({
    criterion: "скорость", plan: "1.2", metrics: "1",
  });
  expect(fetch.mock.calls.map(([url]) => url)).toContain("/api/cases" + search);
  await user.selectOptions(screen.getByLabelText("Показатель нацплана"), "");
  expect(screen.getByLabelText("Только с цифрами")).toBeChecked();
});

it("запоздалый список не подменяет результат нового поиска", async () => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  const { fetch, user } = setup("/?q=старый", (url) =>
    new URL(url, "https://aidigest.test").searchParams.get("q") === "старый"
      ? pending
      : Promise.resolve(Response.json({ total: 1, updated: null, cases: [{ ...row, title: "Новый кейс" }] })),
  );
  await screen.findByLabelText("Поиск");
  expect(fetch.mock.calls.map(([url]) => url)).toContain("/api/cases?q=%D1%81%D1%82%D0%B0%D1%80%D1%8B%D0%B9");
  await user.click(screen.getByRole("link", { name: "Другой поиск" }));
  expect(await screen.findByRole("link", { name: "Новый кейс" })).toBeVisible();
  await act(async () => finish(Response.json({ total: 1, updated: null, cases: [row] })));
  expect(screen.getByRole("link", { name: "Новый кейс" })).toBeVisible();
  expect(screen.queryByText(row.title)).toBeNull();
});
