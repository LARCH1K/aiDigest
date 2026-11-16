export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

export const unauthorizedEvent = "aidigest:unauthorized";

type UnauthorizedDetail = { path: string; sessionVersion: number };
let sessionVersion = 0;

export function advanceSessionVersion() {
  sessionVersion += 1;
}

export function isSessionUnauthorized(event: Event): boolean {
  const detail = (event as CustomEvent<UnauthorizedDetail>).detail;
  // Сервер возвращает 401 при неверном пароле и при истечении сессии.
  return !detail || (detail.sessionVersion === sessionVersion && detail.path !== "/api/login");
}

function errorMessage(detail: unknown, status: number): string {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.flatMap((item) =>
      typeof item?.msg === "string" ? [item.msg] : [],
    );
    if (messages.length) return messages.join("; ");
  }
  return `Ошибка запроса (HTTP ${status})`;
}

async function request(path: string, method: "GET" | "POST", body?: unknown, cache?: RequestCache): Promise<Response> {
  const version = sessionVersion;
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    cache,
    headers: body === undefined
      ? { Accept: "application/json" }
      : { Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.ok) return response;

  if (response.status === 401) {
    window.dispatchEvent(new CustomEvent<UnauthorizedDetail>(unauthorizedEvent, {
      detail: { path, sessionVersion: version },
    }));
  }
  const problem = await response.json().catch(() => null);
  throw new ApiError(response.status, errorMessage(problem?.detail, response.status));
}

export async function apiGet<T>(path: string, options?: { cache: RequestCache }): Promise<T> {
  const response = await request(path, "GET", undefined, options?.cache);
  return response.json();
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T | null> {
  const response = await request(path, "POST", body);
  return response.status === 204 ? null : response.json();
}
