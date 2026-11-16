import { expect, it, vi } from "vitest";
import { ApiError, apiGet, apiPost } from "./api";

it("401 бросает ApiError и шлёт aidigest:unauthorized", async () => {
  const fetch = vi.fn().mockResolvedValue(Response.json({ detail: "нужен вход" }, { status: 401 }));
  vi.stubGlobal("fetch", fetch);
  const unauthorized = vi.fn();
  window.addEventListener("aidigest:unauthorized", unauthorized);
  try {
    const result = apiGet("/api/meta");
    await expect(result).rejects.toBeInstanceOf(ApiError);
    await expect(result).rejects.toMatchObject({ status: 401, message: "нужен вход" });
    expect(unauthorized).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledWith("/api/meta", expect.objectContaining({ credentials: "same-origin" }));
  } finally {
    window.removeEventListener("aidigest:unauthorized", unauthorized);
  }
});

it("ошибка несёт detail из ответа", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ detail: "Сбор уже идёт…" }, { status: 409 })));
  await expect(apiPost("/api/runs")).rejects.toMatchObject({ status: 409, message: "Сбор уже идёт…" });
});

it("извлекает текст ошибки валидации", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({
    detail: [{ loc: ["body", "budget"], msg: "Ожидается положительное число" }],
  }, { status: 422 })));
  await expect(apiPost("/api/runs")).rejects.toMatchObject({
    status: 422, message: "Ожидается положительное число",
  });
});

it("401 с пустым ответом также уведомляет об истечении сессии", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));
  const unauthorized = vi.fn();
  window.addEventListener("aidigest:unauthorized", unauthorized, { once: true });
  await expect(apiGet("/api/meta")).rejects.toMatchObject({ status: 401 });
  expect(unauthorized).toHaveBeenCalledOnce();
});

it("отправляет JSON и обрабатывает пустой ответ 204", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetch);
  await expect(apiPost("/api/login", { username: "analyst", password: "example" })).resolves.toBeNull();
  expect(fetch).toHaveBeenCalledWith("/api/login", expect.objectContaining({
    method: "POST",
    credentials: "same-origin",
    headers: expect.objectContaining({ "Content-Type": "application/json" }),
    body: '{"username":"analyst","password":"example"}',
  }));
});
