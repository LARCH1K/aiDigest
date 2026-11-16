import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, useLocation } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { App } from "../App";
import type { CaseRow } from "../types";

const row: CaseRow = {
  id: "water", title: "Контроль воды", level: "мир", country: "Япония", region: null,
  organization: "Водоканал", industry: "ЖКХ", stage: "пилот", first_seen: "2026-11-05",
  status: "один_источник", status_label: "Один источник", status_class: "warn",
  headline: "Время 12 → 4 мин", headline_unverified: true, reliability: "низкая",
  reliability_label: "низкая", reliability_class: "warn", flags: [],
};

function setup(path: string, cases: (url: string) => Promise<Response>, metaStatus = 200) {
  const fetch = vi.fn(async (url: string) => {
    if (url === "/api/me") return Response.json({ authenticated: true, login_required: false });
    if (url === "/api/meta") {
      if (metaStatus !== 200) return Response.json({ detail: "Справочник недоступен" }, { status: metaStatus });
      return Response.json({
        levels: ["мир", "регионы РФ", "Свердловская область"],
        statuses: [{ value: "один_источник", label: "Один источник", class: "warn" }],
        reliability: [{ value: "низкая", label: "низкая" }],
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
    "/api/cases?level=%D0%BC%D0%B8%D1%80&metrics=1&doubtful=1",
  );
  expect(await screen.findByLabelText("Уровень")).toHaveValue("мир");
  expect(screen.getByLabelText("только с цифрами")).toBeChecked();
  expect(screen.getByLabelText("скрыть сомнительные")).toBeChecked();
});

it("при ошибке справочника действительный фильтр из адреса по-прежнему загружает таблицу", async () => {
  const { fetch } = setup("/?level=мир", async () =>
    Response.json({ total: 1, updated: null, cases: [row] }), 500,
  );
  expect(await screen.findByRole("table")).toBeVisible();
  expect(screen.getByRole("link", { name: row.title })).toBeVisible();
  expect(fetch.mock.calls.map(([url]) => url)).toContain("/api/cases?level=%D0%BC%D0%B8%D1%80&metrics=1");
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
  expect(fetch.mock.calls.map(([url]) => url)).toContain("/api/cases?metrics=1");
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
  await user.click(screen.getByLabelText("только с цифрами"));
  await user.click(screen.getByLabelText("скрыть сомнительные"));
  await user.click(screen.getByRole("button", { name: "Показать" }));

  const search = screen.getByLabelText("Фильтры в адресе").textContent!;
  expect(Object.fromEntries(new URLSearchParams(search))).toEqual({
    q: "вода & свет", level: "мир", status: "один_источник",
    reliability: "низкая", metrics: "0", doubtful: "1",
  });
  expect(fetch.mock.calls.map(([url]) => url)).toContain("/api/cases" + search);

  await user.click(screen.getByRole("link", { name: "Сбросить" }));
  expect(screen.getByLabelText("Фильтры в адресе").textContent).toBe("");
  expect(screen.getByLabelText("Поиск")).toHaveValue("");
  expect(screen.getByLabelText("только с цифрами")).toBeChecked();
  expect(screen.getByLabelText("скрыть сомнительные")).not.toBeChecked();
});

it("пустая база — понятный текст, а не пустая таблица", async () => {
  setup("/", async () => Response.json({ total: 0, updated: null, cases: [] }));
  expect(await screen.findByRole("heading", { name: "Кейсов пока нет" })).toBeVisible();
  expect(screen.getByRole("link", { name: "«Запуск сбора»" })).toHaveAttribute("href", "/run");
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.getByRole("link", { name: "Выгрузить в Excel" }))
    .toHaveAttribute("href", "/api/export.xlsx");
});

it("непроверенная главная цифра помечена, заголовок сортирует строки", async () => {
  const { user } = setup("/", async () => Response.json({
    total: 2, updated: "2026-11-05T09:07:00Z",
    cases: [row, { ...row, id: "z", title: "Анализ воздуха", headline_unverified: false }],
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
      { ...row, id: "z", organization: "Ясень", first_seen: "2026-11-01" },
      { ...row, id: "a", organization: "Альфа", first_seen: "2026-11-03" },
      { ...row, id: "b", organization: "Альфа", first_seen: "2026-11-02" },
    ],
  }));
  await user.click(await screen.findByRole("columnheader", { name: "В базе с" }));
  const title = screen.getByRole("columnheader", { name: "Кейс" });
  await user.click(title);
  const ids = () => screen.getAllByRole("link", { name: row.title }).map((link) => link.getAttribute("href"));
  expect(ids()).toEqual(["/case/b", "/case/a", "/case/z"]);
  await user.click(title);
  expect(ids()).toEqual(["/case/z", "/case/b", "/case/a"]);
  expect(fetch.mock.calls.map(([url]) => url).filter((url) => url.startsWith("/api/cases?")))
    .toEqual(["/api/cases?metrics=1"]);
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
  expect(fetch.mock.calls.map(([url]) => url)).toContain("/api/cases?q=%D1%81%D1%82%D0%B0%D1%80%D1%8B%D0%B9&metrics=1");
  await user.click(screen.getByRole("link", { name: "Другой поиск" }));
  expect(await screen.findByRole("link", { name: "Новый кейс" })).toBeVisible();
  await act(async () => finish(Response.json({ total: 1, updated: null, cases: [row] })));
  expect(screen.getByRole("link", { name: "Новый кейс" })).toBeVisible();
  expect(screen.queryByText(row.title)).toBeNull();
});
