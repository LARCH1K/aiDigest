import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { App } from "../App";
import type { CaseDetail, CaseRow } from "../types";

const unsafeUrl = "javascript:alert(1)";
const decree = "https://publication.pravo.gov.ru/document/0001202402150063";
const detail: CaseDetail = {
  id: "water", title: "Контроль воды", level: "мир", country: "Япония", region: null,
  municipality: "Токио", organization: "Водоканал", industry: "ЖКХ", sector: "госсектор",
  stage: "пилот", first_seen: "2026-11-05", updated: "2026-11-06",
  ai_technology: "Компьютерное зрение", summary: "Контроль качества воды.", methodology: "М-1",
  status_label: "Один источник", status_class: "warn", reliability_label: "низкая",
  confirmation_status: "один_источник", confirmation_attempts: 0, last_confirmation_attempt: null,
  flags: ["один_источник"],
  metrics: [{
    name: "Время проверки", criterion: "скорость", before: "12 мин", after: "4 мин", change: "−8 мин",
    kind: "план", unit: "мин", quote: "Проверка займёт 4 минуты.", source_url: unsafeUrl,
    quote_verified: true, confirmed_by: [unsafeUrl, "https://report.example/detail"], conflicting_values: ["6 мин"],
  }],
  strategy_links: [],
  sources: [{
    url: unsafeUrl, domain: "example.test", title: "Первый источник", published_at: null,
    reliability: "низкая", source_type: "СМИ",
  }, {
    url: "https://news.example/story", domain: "news.example", title: "", published_at: null,
    reliability: "средняя", source_type: "официальная",
  }],
};
const row: CaseRow = {
  ...detail,
  status: detail.confirmation_status, headline: "Время проверки 12 → 4 мин", headline_unverified: false,
  reliability: "средняя", reliability_class: "warn",
};
const list = { total: 2, updated: null, cases: [row, { ...row, id: "air", title: "Анализ воздуха" }] };

function HistoryControls() {
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  return (
    <>
      <output aria-label="Текущий адрес">{pathname + search}</output>
      <button onClick={() => navigate(-1)}>Назад в браузере</button>
    </>
  );
}

function setup(path: string, cases: (url: string) => Promise<Response> = async () => Response.json(detail)) {
  const fetch = vi.fn(async (url: string) => {
    if (url === "/api/me") return Response.json({ authenticated: true, login_required: false });
    if (url === "/api/meta") return Response.json({
      levels: ["мир"], statuses: [], reliability: [], criteria: [],
      strategy_kpis: [{ value: "ai_skills", label: "Навыки работы с ИИ", clause: "28.1 «е»", url: decree }],
      flag_help: { один_источник: ["Только один источник.", "Найдите второй источник."] },
    });
    return cases(url);
  });
  vi.stubGlobal("fetch", fetch);
  render(
    <MemoryRouter initialEntries={["/history-start", path]}>
      <Link to="/case/new">Другой кейс</Link>
      <HistoryControls />
      <App />
    </MemoryRouter>,
  );
  return Object.assign(userEvent.setup(), { fetch });
}

it("ссылки источников и показателей проходят через safeUrl", async () => {
  setup("/case/water");
  expect(await screen.findByRole("heading", { name: detail.title })).toBeVisible();
  for (const link of [
    ...screen.getAllByRole("link", { name: unsafeUrl }),
    screen.getByRole("link", { name: "Первый источник" }),
  ]) {
    expect(link).toHaveAttribute("href", "#");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  }
  expect(screen.getAllByRole("link", { name: unsafeUrl })).toHaveLength(2);
  expect(screen.getByRole("link", { name: "report.example" })).toHaveAttribute("href", "https://report.example/detail");
  expect(screen.getByRole("link", { name: "news.example" })).toHaveAttribute("href", "https://news.example/story");
  expect(screen.getByText("12 мин → 4 мин")).toBeVisible();
  expect(screen.getByText("≠ другое значение: 6 мин")).toBeVisible();
});

it("флаги показывают пояснение из meta.flag_help", async () => {
  setup("/case/water");
  expect(await screen.findByText("Только один источник.")).toBeVisible();
  expect(screen.getByText("Найдите второй источник.")).toBeVisible();
});

it("в основных сведениях есть дата обновления, у публикаций — свои даты", async () => {
  setup("/case/water", async () => Response.json({
    ...detail,
    updated: "2026-11-06T09:10:00Z",
    sources: [
      { ...detail.sources[0], published_at: "2026-11-03" },
      { ...detail.sources[1], published_at: "2026-11-04T09:10:00Z" },
      { ...detail.sources[1], title: "Старая запись", published_at: "2026-02-31" },
      { ...detail.sources[1], title: "Без даты", published_at: null },
    ],
  }));
  expect(await screen.findByText("Обновлён")).toBeVisible();
  expect(screen.getByText("06.11.2026")).toBeVisible();
  expect(screen.getByText(/05\.11\.2026/)).toBeVisible();
  const dates = screen.getAllByRole("listitem").filter((item) => within(item).queryByRole("link"));
  expect(dates[0]).toHaveTextContent("03.11.2026");
  expect(dates[1]).toHaveTextContent("04.11.2026");
  expect(dates[2]).toHaveTextContent("Дата публикации не указана");
  expect(dates[3]).toHaveTextContent("Дата публикации не указана");
});

it("свидетельства одного KPI сгруппированы с подпунктом и безопасными ссылками", async () => {
  const { fetch } = setup("/case/water", async () => Response.json({
    ...detail,
    metrics: [],
    strategy_links: [{
      kpi_id: "ai_skills", explanation: "Публикация описывает обучение работников.",
      source_url: "https://news.example/story", quote: "Работники прошли обучение.",
    }, {
      kpi_id: "ai_skills", explanation: "Вторая публикация подтверждает обучение.",
      source_url: unsafeUrl, quote: "Обучение завершено.",
    }],
  }));
  expect(await screen.findByRole("heading", { name: "Навыки работы с ИИ" })).toBeVisible();
  expect(screen.getAllByRole("heading", { name: "Навыки работы с ИИ" })).toHaveLength(1);
  expect(screen.getByRole("link", { name: /28\.1 «е»/ })).toHaveAttribute("href", decree);
  expect(screen.getByText("Публикация описывает обучение работников.")).toBeVisible();
  expect(screen.getByText("«Работники прошли обучение.»")).toBeVisible();
  const evidence = screen.getAllByRole("link", { name: "Публикация" });
  expect(evidence[0]).toHaveAttribute("href", "https://news.example/story");
  expect(evidence[1]).toHaveAttribute("href", "#");
  expect(evidence[1]).toHaveAttribute("rel", "noopener noreferrer");
  expect(screen.getByText("Только один источник.")).toBeVisible();
  expect(fetch.mock.calls.filter(([url]) => url === "/api/meta")).toHaveLength(1);
});

it("неизвестный кейс — страница «Кейс не найден»", async () => {
  const user = setup("/case/missing", async (url) => url === "/api/cases/missing"
    ? Response.json({ detail: "Кейс не найден" }, { status: 404 })
    : Response.json({ total: 0, updated: null, cases: [] }));
  expect(await screen.findByRole("heading", { name: "Кейс не найден" })).toBeVisible();
  expect(screen.getByText(/Возможно, кейс был удалён при пересборке базы/)).toBeVisible();
  expect(screen.getByRole("link", { name: "списку кейсов" })).toHaveAttribute("href", "/");
  const back = screen.getByRole("link", { name: "← к списку кейсов" });
  expect(back).toHaveAttribute("href", "/");
  await user.click(back);
  expect(screen.getByLabelText("Текущий адрес")).toHaveTextContent(/^\/$/);
  expect(await screen.findByRole("heading", { name: "Кейсов пока нет" })).toBeVisible();
});

it("запоздалый 404 предыдущего кейса не закрывает новую карточку", async () => {
  let finish!: (response: Response) => void;
  let started = false;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  const user = setup("/case/old", (url) => {
    if (url === "/api/cases/old") {
      started = true;
      return pending;
    }
    return Promise.resolve(Response.json({ ...detail, id: "new", title: "Новый кейс" }));
  });
  await screen.findByRole("navigation");
  expect(started).toBe(true);
  await user.click(screen.getByRole("link", { name: "Другой кейс" }));
  expect(await screen.findByRole("heading", { name: "Новый кейс" })).toBeVisible();
  await act(async () => finish(Response.json({}, { status: 404 })));
  expect(screen.getByRole("heading", { name: "Новый кейс" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Кейс не найден" })).toBeNull();
});

it("возврат из карточки восстанавливает запись истории и фильтры", async () => {
  const user = setup("/?q=вода&metrics=0", async (url) =>
    Response.json(url.startsWith("/api/cases?") ? list : detail));
  await user.click(await screen.findByRole("columnheader", { name: "Кейс" }));
  await user.click(await screen.findByRole("link", { name: detail.title }));
  expect(await screen.findByRole("heading", { name: detail.title })).toBeVisible();
  const back = screen.getByRole("link", { name: "← к списку кейсов" });
  expect(back).toHaveAttribute("href", "/?q=вода&metrics=0");
  await user.click(back);
  expect(await screen.findByLabelText("Поиск")).toHaveValue("вода");
  expect(screen.getByLabelText("только с цифрами")).not.toBeChecked();
  await user.click(screen.getByRole("button", { name: "Назад в браузере" }));
  expect(screen.getByLabelText("Текущий адрес")).toHaveTextContent("/history-start");
});

it("после возврата из карточки таблица сохраняет направление и порядок сортировки", async () => {
  const user = setup("/", async (url) => Response.json(url.startsWith("/api/cases?") ? list : detail));
  await user.click(await screen.findByRole("columnheader", { name: "Кейс" }));
  await user.click(screen.getByRole("link", { name: detail.title }));
  expect(await screen.findByRole("heading", { name: detail.title })).toBeVisible();
  await user.click(screen.getByRole("link", { name: "← к списку кейсов" }));
  expect(await screen.findByRole("columnheader", { name: "Кейс" })).toHaveAttribute("aria-sort", "ascending");
  expect(screen.getAllByRole("row")[1]).toHaveTextContent("Анализ воздуха");
});
