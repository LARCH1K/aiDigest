import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { apiGet } from "../api";
import { AuthProvider, RequireAuth } from "../auth";
import { Layout } from "../components/Layout";
import { Login } from "./Login";

const anonymous = { authenticated: false, login_required: true };
const signedIn = { authenticated: true, login_required: true };
const json = (body: unknown, status = 200) => Response.json(body, { status });
const empty = () => new Response(null, { status: 204 });

function setup(path: string, fetch: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetch);
  function Address() {
    const { pathname, search, hash } = useLocation();
    return <output aria-label="Адрес">{pathname + search + hash}</output>;
  }
  render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<RequireAuth />}>
            <Route element={<Layout />}>
              <Route path="*" element={<h1>Запуск</h1>} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
      <Address />
    </MemoryRouter>,
  );
  return userEvent.setup();
}

async function submit(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText("Логин"), "analyst");
  await user.type(screen.getByLabelText("Пароль"), "example");
  await user.click(screen.getByRole("button", { name: "Войти" }));
}

it("неверный пароль показывает текст ошибки сервера", async () => {
  const user = setup("/queries", vi.fn()
    .mockResolvedValueOnce(json(anonymous))
    .mockResolvedValueOnce(json({ detail: "Неверный логин или пароль" }, 401)));
  await submit(user);
  expect(await screen.findByRole("alert")).toHaveTextContent("Неверный логин или пароль");
  expect(screen.getByLabelText("Адрес")).toHaveTextContent("/login?next=%2Fqueries");
});

it.each([
  ["/case/42?tab=metrics#effect", "/case/42?tab=metrics#effect"],
  ["//evil.test", "/"],
  ["/\\evil.test", "/"],
  ["/%252fevil.test", "/"],
])("после входа обрабатывает next %s", async (next, expected) => {
  const user = setup("/login?" + new URLSearchParams({ next }), vi.fn()
    .mockResolvedValueOnce(json(anonymous))
    .mockResolvedValueOnce(empty())
    .mockResolvedValueOnce(json(signedIn)));
  await submit(user);
  await screen.findByRole("navigation");
  expect(screen.getByLabelText("Адрес").textContent).toBe(expected);
});

it("ждёт подтверждения cookie перед переходом на защищённый маршрут", async () => {
  let verifySession!: (response: Response) => void;
  const verification = new Promise<Response>((resolve) => { verifySession = resolve; });
  const fetch = vi.fn().mockResolvedValueOnce(json(anonymous))
    .mockResolvedValueOnce(empty())
    .mockReturnValueOnce(verification);
  const user = setup("/login?next=%2Frun", fetch);

  await submit(user);
  expect(fetch.mock.calls.map(([path, init]) => [path, init.method])).toEqual([
    ["/api/me", "GET"], ["/api/login", "POST"], ["/api/me", "GET"],
  ]);
  expect(fetch).toHaveBeenLastCalledWith("/api/me", expect.objectContaining({
    cache: "no-store", credentials: "same-origin",
  }));
  expect(screen.getByRole("button", { name: "Входим…" })).toBeDisabled();
  expect(screen.getByLabelText("Адрес")).toHaveTextContent("/login?next=%2Frun");
  expect(screen.queryByRole("navigation")).toBeNull();

  await act(async () => { verifySession(json(signedIn)); });
  expect(await screen.findByRole("navigation")).toBeVisible();
  expect(screen.getByLabelText("Адрес").textContent).toBe("/run");
});

it("показывает ошибку формы для отклонённой cookie и позволяет войти повторно", async () => {
  const user = setup("/login?next=%2Frun", vi.fn()
    .mockResolvedValueOnce(json(anonymous))
    .mockResolvedValueOnce(empty())
    .mockResolvedValueOnce(json(anonymous))
    .mockResolvedValueOnce(empty())
    .mockResolvedValueOnce(json(signedIn)));

  await submit(user);
  expect(await screen.findByRole("alert")).toHaveTextContent(/сервер не подтвердил сессию.*cookie/i);
  expect(screen.getByLabelText("Адрес")).toHaveTextContent("/login?next=%2Frun");
  expect(screen.queryByRole("navigation")).toBeNull();

  await user.click(screen.getByRole("button", { name: "Войти" }));
  expect(await screen.findByRole("navigation")).toBeVisible();
  expect(screen.getByLabelText("Адрес").textContent).toBe("/run");
});

it("без пароля открывает защищённый маршрут без кнопки выхода", async () => {
  setup("/run", vi.fn().mockResolvedValue(json({ authenticated: true, login_required: false })));
  expect(await screen.findByRole("heading", { name: "Запуск" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Выйти" })).toBeNull();
});

it("показывает ошибку проверки сессии и позволяет повторить запрос", async () => {
  const user = setup("/run", vi.fn()
    .mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockResolvedValueOnce(json(signedIn)));
  expect(await screen.findByRole("alert")).toHaveTextContent("Не удалось проверить сессию");
  expect(screen.getByLabelText("Адрес")).toHaveTextContent("/run");
  await user.click(screen.getByRole("button", { name: "Повторить" }));
  expect(await screen.findByRole("heading", { name: "Запуск" })).toBeVisible();
});

it("текущий 401 отправляет на вход с путём, запросом и якорем", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(json(signedIn))
    .mockResolvedValueOnce(json({ detail: "нужен вход" }, 401));
  setup("/sources?level=world#list", fetch);
  await screen.findByRole("navigation");
  await act(async () => {
    await expect(apiGet("/api/sources")).rejects.toMatchObject({ status: 401 });
  });
  expect(await screen.findByRole("heading", { name: "Вход" })).toBeVisible();
  expect(screen.getByLabelText("Адрес").textContent)
    .toBe("/login?next=%2Fsources%3Flevel%3Dworld%23list");
});

it("запоздалый 401 от старой сессии не сбрасывает новый вход", async () => {
  let finish!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  const fetch = vi.fn().mockResolvedValueOnce(json(anonymous))
    .mockReturnValueOnce(pending)
    .mockResolvedValueOnce(empty())
    .mockResolvedValueOnce(json(signedIn));
  const user = setup("/login", fetch);
  await screen.findByRole("heading", { name: "Вход" });
  const stale = apiGet("/api/meta").catch((error: unknown) => error);
  await submit(user);
  await screen.findByRole("navigation");
  await act(async () => {
    finish(json({ detail: "нужен вход" }, 401));
    await stale;
  });
  expect(screen.getByRole("navigation")).toBeVisible();
  expect(screen.getByLabelText("Адрес").textContent).toBe("/");
});

it("ошибка выхода сохраняет сессию и показывает detail", async () => {
  const user = setup("/run", vi.fn().mockResolvedValueOnce(json(signedIn))
    .mockResolvedValueOnce(json({ detail: "Недопустимый источник запроса" }, 403))
    .mockResolvedValueOnce(empty()));
  await user.click(await screen.findByRole("button", { name: "Выйти" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Недопустимый источник запроса");
  expect(screen.getByRole("navigation")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Выйти" }));
  expect(await screen.findByRole("heading", { name: "Вход" })).toBeVisible();
});
