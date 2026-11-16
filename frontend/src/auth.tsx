import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { advanceSessionVersion, apiGet, apiPost, isSessionUnauthorized, unauthorizedEvent } from "./api";
import type { SessionState } from "./types";

type Auth = {
  authenticated: boolean;
  loginRequired: boolean;
  login(username: string, password: string): Promise<void>;
  logout(): Promise<void>;
};

const AuthContext = createContext<Auth | null>(null);

export class SessionVerificationError extends Error {
  constructor() {
    super("Сервер не подтвердил сессию. Проверьте, разрешены ли cookie для этого сайта, и попробуйте ещё раз.");
    this.name = "SessionVerificationError";
  }
}

function getSession() {
  return apiGet<SessionState>("/api/me", { cache: "no-store" });
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionState | null>(null);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const changingSession = useRef(false);

  useEffect(() => {
    let active = true;
    getSession().then(
      (current) => { if (active) setSession(current); },
      () => { if (active) setError(true); },
    );
    return () => { active = false; };
  }, [attempt]);

  useEffect(() => {
    function onUnauthorized(event: Event) {
      if (!isSessionUnauthorized(event)) return;
      setSession((current) => current?.login_required && current.authenticated
        ? { ...current, authenticated: false }
        : current);
    }
    window.addEventListener(unauthorizedEvent, onUnauthorized);
    return () => window.removeEventListener(unauthorizedEvent, onUnauthorized);
  }, []);

  async function changeSession(update: () => Promise<SessionState>) {
    if (changingSession.current) throw new Error("Дождитесь завершения предыдущего запроса.");
    changingSession.current = true;
    try {
      const current = await update();
      advanceSessionVersion();
      setSession(current);
    } finally {
      changingSession.current = false;
    }
  }

  if (error) {
    return (
      <main className="page">
        <p className="notice notice-bad" role="alert">Не удалось проверить сессию.</p>
        <button className="btn btn-primary" onClick={() => {
          setError(false);
          setAttempt((current) => current + 1);
        }}>Повторить</button>
      </main>
    );
  }
  if (!session) return <main className="page muted" role="status">Проверяем сессию…</main>;

  return (
    <AuthContext.Provider value={{
      authenticated: session.authenticated,
      loginRequired: session.login_required,
      login: (username, password) => changeSession(async () => {
        await apiPost("/api/login", { username, password });
        const current = await getSession();
        if (current.authenticated !== true) throw new SessionVerificationError();
        return current;
      }),
      logout: () => changeSession(async () => {
        await apiPost("/api/logout");
        return { ...session, authenticated: !session.login_required };
      }),
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) throw new Error("useAuth требует AuthProvider");
  return auth;
}

export function RequireAuth() {
  const { authenticated } = useAuth();
  const { pathname, search, hash } = useLocation();
  if (authenticated) return <Outlet />;

  const next = new URLSearchParams({ next: pathname + search + hash });
  return <Navigate to={`/login?${next}`} replace />;
}
