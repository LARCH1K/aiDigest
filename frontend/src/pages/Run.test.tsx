import { StrictMode } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Credits, RunCurrent, RunRow } from "../types";
import { Run } from "./Run";

const credits: Credits = {
  known: true, used: 10, limit: 1000, remaining: 990, plan: "", run_budget: 30,
};
const idle: RunCurrent = { running: false };
const running: RunCurrent = {
  running: true, run_id: "new", started: "2026-11-15T09:00:00", minutes: 2, tail: ["Поиск начат"],
};
const finished: RunRow = {
  run_id: "new", state: "ok", label: "Успешно", started: running.started,
  finished: "2026-11-15T09:03:00", minutes: 3, exit_code: 0, reason: null,
  report: { "Кейсов новых": "4", "Флаг: один источник": "2" }, params: {},
};

function deferredResponse() {
  let resolve!: (value: Response) => void;
  const promise = new Promise<Response>((done) => { resolve = done; });
  return { promise, resolve };
}

function setup(overrides: Partial<Record<string, () => Response | Promise<Response>>> = {}) {
  const responses = {
    "/api/credits": () => Response.json(credits),
    "/api/runs/current": () => Response.json(idle),
    "/api/runs": () => Response.json([]),
    ...overrides,
  };
  const fetch = vi.fn(async (path: string, options: RequestInit) => {
    const key = options.method === "POST" ? `POST ${path}` : path;
    const handler = responses[key as keyof typeof responses];
    if (!handler) throw new Error(`Неожиданный запрос ${key}`);
    return handler();
  });
  vi.stubGlobal("fetch", fetch);
  return {
    ...render(<StrictMode><Run /></StrictMode>),
    calls(path: string, method = "GET") {
      return fetch.mock.calls.filter(([url, options]) => url === path && options.method === method).length;
    },
  };
}

const button = () => screen.getByRole("button", { name: /Запустить сбор/ });

async function tick(ms = 0) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}

afterEach(() => vi.useRealTimers());

it("показывает минуты и лог, не накладывает опросы и обновляет историю после окончания", async () => {
  vi.useFakeTimers();
  const poll = deferredResponse();
  const oldHistory = deferredResponse();
  const current = vi.fn()
    .mockReturnValueOnce(Response.json(running))
    .mockReturnValueOnce(poll.promise)
    .mockImplementation(() => Response.json(idle));
  const history = vi.fn()
    .mockReturnValueOnce(oldHistory.promise)
    .mockImplementation(() => Response.json([finished]));
  const { calls } = setup({ "/api/runs/current": current, "/api/runs": history });
  await tick();
  expect(screen.getByText(/2 мин назад/)).toBeVisible();
  expect(screen.getByText("Поиск начат")).toBeVisible();
  expect(button()).toBeDisabled();
  fireEvent.click(button());
  fireEvent.click(button());
  expect(calls("/api/runs", "POST")).toBe(0);

  await tick(4999);
  expect(current).toHaveBeenCalledTimes(1);
  await tick(1);
  expect(current).toHaveBeenCalledTimes(2);
  await tick(10_000);
  expect(current).toHaveBeenCalledTimes(2);
  await act(async () => poll.resolve(Response.json({ ...running, minutes: 3, tail: ["Сверка цифр"] })));
  expect(screen.getByText("Сверка цифр")).toBeVisible();
  await tick(4999);
  expect(current).toHaveBeenCalledTimes(2);
  await tick(1);
  expect(current).toHaveBeenCalledTimes(3);
  expect(history).toHaveBeenCalledTimes(2);
  expect(calls("/api/credits")).toBe(2);
  expect(screen.getByText("Успешно")).toBeVisible();
  expect(screen.queryByText("Сверка цифр")).toBeNull();
  expect(button()).toBeEnabled();
  await act(async () => oldHistory.resolve(Response.json([])));
  expect(screen.getByText("Успешно")).toBeVisible();
  await tick(10_000);
  expect(current).toHaveBeenCalledTimes(3);
});

it("однократно отправляет запуск и показывает detail ответа 409, затем принимает активный сбор", async () => {
  vi.useFakeTimers();
  const post = deferredResponse();
  const status = deferredResponse();
  const { calls } = setup({
    "/api/runs/current": vi.fn().mockReturnValueOnce(Response.json(idle)).mockReturnValue(status.promise),
    "POST /api/runs": () => post.promise,
  });
  await tick();
  act(() => {
    fireEvent.click(button());
    fireEvent.click(button());
  });
  expect(calls("/api/runs", "POST")).toBe(1);
  expect(button()).toBeDisabled();
  await act(async () => post.resolve(Response.json({ detail: "Другой запуск уже начат" }, { status: 409 })));
  expect(screen.getByRole("alert")).toHaveTextContent("Другой запуск уже начат");
  expect(button()).toBeDisabled();
  await act(async () => status.resolve(Response.json(running)));
  expect(screen.getByRole("heading", { name: "Идёт сбор" })).toBeVisible();
  expect(button()).toBeDisabled();
});

it("при исчерпанном известном лимите два клика не отправляют запуск", async () => {
  const { calls } = setup({
    "/api/credits": () => Response.json({ ...credits, used: 1000, remaining: 0 }),
  });
  expect(await screen.findByText(/потрачено 1000 из 1000 \(по данным Tavily\)/)).toBeVisible();
  expect(button()).toBeDisabled();
  fireEvent.click(button());
  fireEvent.click(button());
  expect(calls("/api/runs", "POST")).toBe(0);
});

it.each([
  { recovered: { ...credits, used: 20, remaining: 980 }, enabled: true, label: /по данным Tavily/ },
  { recovered: { ...credits, used: 1000, remaining: 0 }, enabled: false, label: /по данным Tavily/ },
  {
    recovered: { ...credits, known: false, used: null, limit: null, remaining: null },
    enabled: true, label: /расход неизвестен/,
  },
])("повторяет загрузку кредитов после сбоя (остаток: $recovered.remaining)", async ({ recovered, enabled, label }) => {
  vi.useFakeTimers();
  const retry = deferredResponse();
  const { calls } = setup({
    "/api/credits": vi.fn().mockReturnValueOnce(Response.json({}, { status: 503 })).mockReturnValue(retry.promise),
  });
  await tick();
  expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить кредиты поиска");
  expect(button()).toBeDisabled();

  const retryButton = screen.getByRole("button", { name: "Повторить загрузку кредитов" });
  act(() => {
    fireEvent.click(retryButton);
    fireEvent.click(retryButton);
  });
  expect(calls("/api/credits")).toBe(2);
  expect(button()).toBeDisabled();
  await act(async () => retry.resolve(Response.json(recovered)));
  expect(screen.getByText(label)).toBeVisible();
  expect(screen.queryByRole("alert")).toBeNull();
  if (enabled) {
    expect(button()).toBeEnabled();
  } else {
    expect(button()).toBeDisabled();
    fireEvent.click(button());
    expect(calls("/api/runs", "POST")).toBe(0);
  }
});

it("при неизвестном расходе позволяет запустить сбор и сразу получает состояние", async () => {
  const { calls } = setup({
    "/api/credits": () => Response.json({ ...credits, known: false, used: null, limit: null, remaining: null }),
    "/api/runs/current": vi.fn().mockReturnValueOnce(Response.json(idle))
      .mockImplementation(() => Response.json(running)),
    "POST /api/runs": () => Response.json({ run_id: running.run_id }, { status: 202 }),
  });
  expect(await screen.findByText(/расход неизвестен — Tavily не ответил/i)).toBeVisible();
  expect(button()).toBeEnabled();
  fireEvent.click(button());
  expect(await screen.findByText("Поиск начат")).toBeVisible();
  expect(calls("/api/runs/current")).toBe(2);
  expect(button()).toBeDisabled();
});

it.each(["история", "статус"])("перечитывает противоречивую начальную историю один раз, первым пришёл ответ «%s»", async (first) => {
  vi.useFakeTimers();
  const initialHistory = deferredResponse();
  const initialStatus = deferredResponse();
  const activeRun = { ...finished, state: "running", label: "идёт", finished: null, exit_code: null };
  const history = vi.fn().mockReturnValueOnce(initialHistory.promise)
    .mockImplementation(() => Response.json([finished]));
  const { calls } = setup({
    "/api/runs": history,
    "/api/runs/current": () => initialStatus.promise,
  });
  await tick();
  const replyHistory = () => initialHistory.resolve(Response.json([activeRun]));
  const replyStatus = () => initialStatus.resolve(Response.json(idle));
  await act(async () => { (first === "история" ? replyHistory : replyStatus)(); });
  expect(history).toHaveBeenCalledTimes(1);
  await act(async () => { (first === "история" ? replyStatus : replyHistory)(); });
  expect(history).toHaveBeenCalledTimes(2);
  expect(screen.getByText(finished.label)).toBeVisible();
  expect(screen.queryByText(activeRun.label)).toBeNull();
  await tick(15_000);
  expect(history).toHaveBeenCalledTimes(2);
  expect(calls("/api/runs/current")).toBe(1);
});

it("при повторном противоречивом ответе истории третьего запроса нет", async () => {
  vi.useFakeTimers();
  const { calls } = setup({
    "/api/runs": () => Response.json([{ ...finished, state: "running", finished: null }]),
  });
  await tick(15_000);
  expect(calls("/api/runs")).toBe(2);
  expect(calls("/api/runs/current")).toBe(1);
});

it("показывает причину прерывания, параметры отладки и безопасные ссылки на логи", async () => {
  setup({
    "/api/runs": () => Response.json([
      { ...finished, state: "interrupted", label: "Прерван", reason: "Сервис был остановлен",
        params: { budget: 5, offline: true, levels: ["мир"] } },
      { ...finished, run_id: "../logout?x" },
    ]),
  });
  expect(await screen.findByRole("heading", { name: "Последний запуск" })).toBeVisible();
  const history = within(screen.getByRole("table"));
  expect(history.getByText("Сервис был остановлен")).toBeVisible();
  expect(history.getByText("отладочный").parentElement).toHaveTextContent(/budget=5.*offline=true.*мир/);
  const fullLog = screen.getByRole("link", { name: "полный лог" });
  expect(fullLog).toHaveAttribute("href", "/api/runs/new/log");
  expect(fullLog).toHaveAttribute("rel", "noopener noreferrer");
  expect(history.getAllByRole("link")).toHaveLength(1);
  expect(screen.queryByText(/Флаг: один источник/)).toBeNull();
});

it("после размонтирования запоздалый ответ опроса не планирует новый запрос", async () => {
  vi.useFakeTimers();
  const poll = deferredResponse();
  const { calls, unmount } = setup({
    "/api/runs/current": vi.fn().mockReturnValueOnce(Response.json(running)).mockReturnValue(poll.promise),
  });
  await tick();
  await tick(5000);
  expect(calls("/api/runs/current")).toBe(2);
  unmount();
  await act(async () => poll.resolve(Response.json(running)));
  await tick(10_000);
  expect(calls("/api/runs/current")).toBe(2);
  expect(calls("/api/runs")).toBe(1);
});

it("после ухода со страницы ответ запуска не запускает опрос", async () => {
  vi.useFakeTimers();
  const post = deferredResponse();
  const { calls, unmount } = setup({ "POST /api/runs": () => post.promise });
  await tick();
  fireEvent.click(button());
  expect(calls("/api/runs", "POST")).toBe(1);
  unmount();
  await act(async () => post.resolve(Response.json({ run_id: running.run_id }, { status: 202 })));
  await tick(10_000);
  expect(calls("/api/runs/current")).toBe(1);
});

it("обновляет историю, если между опросами первый сбор завершился и начался другой", async () => {
  vi.useFakeTimers();
  const { calls } = setup({
    "/api/runs/current": vi.fn().mockReturnValueOnce(Response.json(running))
      .mockImplementation(() => Response.json({ ...running, run_id: "another", tail: ["Другой сбор"] })),
    "/api/runs": vi.fn().mockReturnValueOnce(Response.json([]))
      .mockImplementation(() => Response.json([finished])),
  });
  await tick();
  await tick(5000);
  expect(screen.getByText("Другой сбор")).toBeVisible();
  expect(screen.getByText("Успешно")).toBeVisible();
  expect(calls("/api/runs")).toBe(2);
  expect(button()).toBeDisabled();
  await tick(5000);
  expect(calls("/api/runs/current")).toBe(3);
  expect(calls("/api/runs")).toBe(2);
});
