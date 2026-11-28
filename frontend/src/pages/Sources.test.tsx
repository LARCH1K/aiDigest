import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { App } from "../App";
import type { SourceInfo, SourcesResp } from "../types";

const source: SourceInfo = {
  name: "Региональный портал", domains: ["news.example", "javascript:alert(1)"],
  level: null, reliability: "высокая", source_type: "официальная", update_frequency: "регулярно",
};
const catalog: SourcesResp = {
  sources: [source], total: 2, error: null,
  level_options: [{ value: "rf", label: "регионы РФ и Свердловская область" }],
  reliability_options: [{ value: "высокая", label: "высокая" }],
};

function setup(path: string, respond: (path: string) => Response | Promise<Response>) {
  const fetch = vi.fn(async (url: string, _options: RequestInit) => url === "/api/me"
    ? Response.json({ authenticated: true, login_required: false })
    : respond(url));
  vi.stubGlobal("fetch", fetch);
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  return { fetch, user: userEvent.setup() };
}

it("отправляет выбранный уровень и достоверность, показывает число результатов и сбрасывает фильтры", async () => {
  const { fetch, user } = setup("/sources", (url) => Response.json({
    ...catalog,
    sources: url.includes("?") ? [] : catalog.sources,
  }));
  expect(await screen.findByText(source.name)).toBeVisible();
  expect(screen.getByText("javascript:alert(1)").closest("a")).toBeNull();
  await user.selectOptions(screen.getByLabelText("Уровень"), "rf");
  await user.selectOptions(screen.getByLabelText("Достоверность"), "высокая");
  expect(fetch.mock.calls.filter(([url]) => url.startsWith("/api/sources"))).toEqual([["/api/sources", expect.anything()]]);
  await user.click(screen.getByRole("button", { name: "Показать" }));

  expect(await screen.findByRole("heading", { name: "Ничего не нашлось" })).toBeVisible();
  expect(screen.getByText("Найдено 0 из 2")).toBeVisible();
  const filtered = fetch.mock.calls.find(([url]) => url.startsWith("/api/sources?"))?.[0];
  expect(Object.fromEntries(new URL(filtered!, "https://test.invalid").searchParams)).toEqual({
    level: "rf", reliability: "высокая",
  });
  expect(screen.getByLabelText("Уровень")).toHaveValue("rf");
  await user.click(screen.getByRole("link", { name: "Сбросить" }));
  expect(await screen.findByText(source.name)).toBeVisible();
  expect(screen.getByLabelText("Уровень")).toHaveValue("");
});

it("запоздалый ответ старого фильтра не подменяет результаты после перехода", async () => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  const { user, fetch } = setup("/sources?level=rf&extra=1", (url) => {
    if (url === "/api/queries") return Response.json({ groups: [], total: 0, freshness_days: 30, error: null });
    if (url === "/api/sources?level=rf") return pending;
    if (url === "/api/sources") return Response.json({
      ...catalog, sources: [{ ...source, name: "Обновлённый справочник" }],
    });
    throw new Error(`Неожиданный запрос ${url}`);
  });
  expect(await screen.findByText("Загрузка справочника…")).toHaveAttribute("role", "status");
  expect(fetch.mock.calls.map(([url]) => url)).toContain("/api/sources?level=rf");
  await user.click(screen.getByRole("link", { name: "Запросы" }));
  await user.click(screen.getByRole("link", { name: "Источники" }));
  expect(await screen.findByText("Обновлённый справочник")).toBeVisible();
  await act(async () => finish(Response.json(catalog)));
  expect(screen.queryByText(source.name)).toBeNull();
});

it("маршруты запросов и справки показывают параметры поиска и пояснения из API", async () => {
  const { user } = setup("/queries", (url) => {
    if (url === "/api/queries") return Response.json({
      total: 1, freshness_days: 14, error: null,
      groups: [{ level: "мир", queries: [
        { level: "мир", text: "AI in public transport", use_registry_domains: true, language: "en" },
      ] }],
    });
    if (url === "/api/meta") return Response.json({
      flag_help: { один_источник: ["Проверен один источник", "Найдите ещё одну статью"] },
    });
    throw new Error(`Неожиданный запрос ${url}`);
  });
  expect(await screen.findByText("AI in public transport")).toBeVisible();
  expect(screen.getByText("Английский")).toBeVisible();
  expect(screen.getByText(/старше 14 дн/)).toHaveTextContent("Материалы без даты остаются в выборке");
  await user.click(screen.getByRole("link", { name: "Справка" }));
  expect(await screen.findByRole("heading", { name: "Как читать таблицу" })).toBeVisible();
  expect(await screen.findByText("Найдите ещё одну статью")).toBeVisible();
});
