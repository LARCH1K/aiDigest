import { useState } from "react";
import type { FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../api";
import { SessionVerificationError, useAuth } from "../auth";
import { safeNext } from "../safeUrl";

export function Login() {
  const { authenticated, login } = useAuth();
  const [search] = useSearchParams();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  if (authenticated) return <Navigate to={safeNext(search.get("next"))} replace />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;

    const form = new FormData(event.currentTarget);
    setPending(true);
    setError("");
    try {
      await login(String(form.get("username") ?? ""), String(form.get("password") ?? ""));
    } catch (cause) {
      setError(cause instanceof ApiError || cause instanceof SessionVerificationError
        ? cause.message
        : "Не удалось войти. Попробуйте ещё раз.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="login">
      <div className="card login-card">
        <h1>Вход</h1>
        <p className="muted">Данные для входа выдаёт команда проекта.</p>
        <form onSubmit={submit}>
          <label className="field">
            <span>Логин</span>
            <input name="username" autoComplete="username" autoFocus required />
          </label>
          <label className="field">
            <span>Пароль</span>
            <input type="password" name="password" autoComplete="current-password" required />
          </label>
          {error && <p className="error" role="alert">{error}</p>}
          <button className="btn btn-primary btn-block" type="submit" disabled={pending}>
            {pending ? "Входим…" : "Войти"}
          </button>
        </form>
      </div>
    </section>
  );
}
