import { useState } from "react";
import { Link, NavLink, Outlet, useMatch } from "react-router-dom";
import { ApiError } from "../api";
import { useAuth } from "../auth";

const pages = [
  { path: "/run", title: "Запуск" },
  { path: "/queries", title: "Запросы" },
  { path: "/sources", title: "Источники" },
  { path: "/help", title: "Справка" },
];

export function Layout({ showNav = true }: { showNav?: boolean }) {
  const { loginRequired, logout } = useAuth();
  const casePage = useMatch("/case/:id");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function signOut() {
    setPending(true);
    setError("");
    try {
      await logout();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Не удалось выйти. Попробуйте ещё раз.");
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <Link className="brand" to="/">
            <span className="brand-mark" aria-hidden="true">AI</span>
            <span className="brand-text"><b>aiDigest</b><small>кейсы внедрения ИИ</small></span>
          </Link>
          {showNav && (
            <>
              <nav className="nav" aria-label="Разделы">
                <NavLink to="/" end className={({ isActive }) => isActive || casePage ? "active" : ""}>
                  Кейсы
                </NavLink>
                {pages.map(({ path, title }) => <NavLink to={path} key={path}>{title}</NavLink>)}
              </nav>
              {loginRequired && (
                <button className="btn btn-ghost nav-logout" onClick={signOut} disabled={pending}>
                  {pending ? "Выходим…" : "Выйти"}
                </button>
              )}
            </>
          )}
        </div>
      </header>
      <main className="page">
        {error && <p className="notice notice-bad" role="alert">{error}</p>}
        <Outlet />
      </main>
      <footer className="footer">
        aiDigest · данные собраны автоматически — перед использованием проверяйте цифры по ссылкам
      </footer>
    </>
  );
}
