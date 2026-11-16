import { useEffect, useRef, useState } from "react";
import { ApiError, apiGet, apiPost } from "../api";
import type { Credits, RunCurrent, RunRow, RunStarted } from "../types";

const noStore = { cache: "no-store" } as const;
const pollDelay = 5000;

function isExhausted(credits: Credits) {
  return credits.known && credits.remaining !== null && credits.remaining <= 0;
}

function CreditsCard({ credits, failed, onRetry }: { credits?: Credits; failed: boolean; onRetry: () => void }) {
  const percent = credits?.known && credits.used !== null && credits.limit
    ? Math.min(100, Math.max(0, 100 * credits.used / credits.limit))
    : 0;
  return (
    <section className="card">
      <h2>Кредиты поиска</h2>
      {failed ? <>
        <p className="error" role="alert">Не удалось загрузить кредиты поиска.</p>
        <button className="btn btn-ghost" type="button" onClick={onRetry}>Повторить загрузку кредитов</button>
      </>
        : !credits ? <p className="muted" role="status">Загрузка кредитов…</p>
        : <>
          {credits.known ? <>
            <div className="meter" aria-hidden="true">
              <div className={`meter-fill${percent >= 80 ? " meter-warn" : ""}`} style={{ width: `${percent}%` }} />
            </div>
            <p className="meter-text">
              потрачено {credits.used} из {credits.limit} (по данным Tavily) · осталось {credits.remaining}
            </p>
          </> : <p className="meter-text">расход неизвестен — Tavily не ответил</p>}
          <p className="muted">Один запуск тратит до {credits.run_budget} кредитов.</p>
        </>}
    </section>
  );
}

function RunStatus({ run }: { run: RunRow }) {
  const tone = run.state === "ok" ? "ok"
    : ["limit", "interrupted", "busy"].includes(run.state) ? "warn"
    : run.state === "running" ? "muted" : "bad";
  return <span className={`pill pill-${tone}`}>{run.label}</span>;
}

function DebugParams({ params }: { params: RunRow["params"] }) {
  const entries = Object.entries(params);
  if (entries.length === 0) return null;
  return (
    <small className="run-reason">
      <b>отладочный</b> · {entries.map(([key, value]) =>
        `${key}=${typeof value === "string" ? value : JSON.stringify(value)}`,
      ).join(", ")}
    </small>
  );
}

function LogLink({ id, label }: { id: string; label: string }) {
  // Серверные идентификаторы состоят из ASCII-символов и не меняют сегменты пути.
  if (!/^[a-z0-9_-]+$/i.test(id)) return null;
  return <a href={`/api/runs/${id}/log`} target="_blank" rel="noopener noreferrer">{label}</a>;
}

function startedAt(started: string) {
  return `${started.slice(0, 10).split("-").reverse().join(".")} ${started.slice(11, 16)}`;
}

function RunHistory({ history }: { history: RunRow[] }) {
  const [last] = history;
  if (!last) return null;
  const report = Object.entries(last.report).filter(([key]) => !key.startsWith("Флаг"));
  return (
    <>
      <section className="card">
        <div className="card-head">
          <h2>Последний запуск</h2>
          <RunStatus run={last} />
        </div>
        {last.reason ? <p className={last.state === "error" ? "error" : "run-note"}>{last.reason}</p>
          : last.state === "error" ? <p className="error">Сбор завершился с ошибкой — подробности в логе.</p>
          : last.state === "interrupted" ? <p>Сбор был прерван. Новые данные, которые он успел сохранить, уже в базе.</p>
          : null}
        <p className="muted">
          {startedAt(last.started)}{last.finished && ` · длился ${last.minutes} мин`}
          {" · "}<LogLink id={last.run_id} label="полный лог" />
        </p>
        <DebugParams params={last.params} />
        {report.length > 0 && (
          <dl className="stats">
            {report.map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
          </dl>
        )}
      </section>
      {history.length > 1 && (
        <section className="card">
          <h2>История запусков</h2>
          <div className="table-wrap">
            <table className="table compact">
              <thead><tr>
                <th scope="col">Начат</th><th scope="col">Длительность</th>
                <th scope="col">Итог</th><th scope="col">Новых кейсов</th><th scope="col">Лог</th>
              </tr></thead>
              <tbody>
                {history.map((run) => (
                  <tr key={run.run_id}>
                    <td>{startedAt(run.started)}</td>
                    <td>{run.finished ? `${run.minutes} мин` : "—"}</td>
                    <td>
                      <RunStatus run={run} />
                      {run.reason && <small className="run-reason">{run.reason}</small>}
                      <DebugParams params={run.params} />
                    </td>
                    <td>{run.report["Кейсов новых"] ?? "—"}</td>
                    <td><LogLink id={run.run_id} label="лог" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

export function Run() {
  const [credits, setCredits] = useState<Credits>();
  const [current, setCurrent] = useState<RunCurrent>();
  const [history, setHistory] = useState<RunRow[]>();
  const [creditsFailed, setCreditsFailed] = useState(false);
  const [statusFailed, setStatusFailed] = useState(false);
  const [historyFailed, setHistoryFailed] = useState(false);
  const [startError, setStartError] = useState("");
  const start = useRef<(() => void) | null>(null);
  const retryCredits = useRef<(() => void) | null>(null);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let creditsRequest = 0;
    let historyRequest = 0;
    let availableCredits: Credits | undefined;
    let lastStatus: RunCurrent | undefined;
    let initialHistoryHasRunning = false;

    async function loadCredits() {
      const request = ++creditsRequest;
      retryCredits.current = null;
      availableCredits = undefined;
      setCredits(undefined);
      setCreditsFailed(false);
      try {
        const data = await apiGet<Credits>("/api/credits", noStore);
        if (!active || request !== creditsRequest) return;
        availableCredits = data;
        setCredits(data);
      } catch {
        if (active && request === creditsRequest) {
          retryCredits.current = loadCredits;
          setCreditsFailed(true);
        }
      }
    }

    function reconcileInitialHistory() {
      if (!initialHistoryHasRunning || lastStatus?.running !== false) return;
      initialHistoryHasRunning = false;
      void loadHistory();
    }

    async function loadHistory() {
      const request = ++historyRequest;
      try {
        const data = await apiGet<RunRow[]>("/api/runs", noStore);
        if (!active || request !== historyRequest) return;
        setHistory(data);
        setHistoryFailed(false);
        if (request === 1) {
          initialHistoryHasRunning = data.some((run) => run.state === "running");
          reconcileInitialHistory();
        }
      } catch {
        if (active && request === historyRequest) setHistoryFailed(true);
      }
    }

    async function loadCurrent(refreshWhenIdle: boolean) {
      try {
        const data = await apiGet<RunCurrent>("/api/runs/current", noStore);
        if (!active) return;
        const previousId = lastStatus?.running ? lastStatus.run_id : undefined;
        lastStatus = data;
        setCurrent(data);
        setStatusFailed(false);
        if (data.running) {
          if (previousId && previousId !== data.run_id) void loadHistory();
          timer = setTimeout(() => { void loadCurrent(true); }, pollDelay);
        } else if (refreshWhenIdle) {
          void loadCredits();
          void loadHistory();
        } else {
          reconcileInitialHistory();
        }
      } catch {
        if (!active) return;
        setStatusFailed(true);
        timer = setTimeout(() => { void loadCurrent(refreshWhenIdle); }, pollDelay);
      }
    }

    start.current = async () => {
      if (!active || lastStatus?.running !== false || !availableCredits || isExhausted(availableCredits)) return;
      // Блокируем повторный клик сразу, до обновления кнопки React.
      lastStatus = undefined;
      setCurrent(undefined);
      setStartError("");
      try {
        await apiPost<RunStarted>("/api/runs");
      } catch (error) {
        if (active) setStartError(error instanceof ApiError ? error.message : "Не удалось запустить сбор.");
      }
      if (active) void loadCurrent(true);
    };

    // В StrictMode первый эффект сразу снимается. Запускаем запросы только для активного эффекта.
    queueMicrotask(() => {
      if (!active) return;
      void loadCredits();
      void loadHistory();
      void loadCurrent(false);
    });
    return () => {
      active = false;
      start.current = null;
      retryCredits.current = null;
      clearTimeout(timer);
    };
  }, []);

  const running = current?.running ? current : null;
  const exhausted = credits ? isExhausted(credits) : false;
  return (
    <>
      <section className="hero"><div>
        <h1>Запуск сбора</h1>
        <p className="muted">Сбор ищет свежие статьи за последние 30 дней, достаёт из них кейсы с цифрами и ищет подтверждения во втором издании. Обычно занимает 5–15 минут.</p>
      </div></section>
      <div className="grid-2 run-grid">
        <CreditsCard credits={credits} failed={creditsFailed} onRetry={() => retryCredits.current?.()} />
        <section className="card run-card" data-running={running ? "" : undefined}>
          {running ? <>
            <h2><span className="spinner" aria-hidden="true" /> Идёт сбор</h2>
            <p>Начат в <b>{running.started.slice(11, 16)}</b> ({running.minutes} мин назад). Страницу можно закрыть — сбор продолжится.</p>
          </> : <>
            <h2>Новый сбор</h2>
            <p>{current
              ? "Нажмите кнопку — сбор пойдёт в фоне, а новые кейсы появятся в списке по мере обработки."
              : "Проверяем состояние сбора…"}</p>
          </>}
          <button className="btn btn-primary btn-lg" type="button"
            disabled={!current || !!running || !credits || exhausted}
            onClick={() => start.current?.()}>
            Запустить сбор
          </button>
          {exhausted && <p className="error">Лимит кредитов исчерпан — новый запуск возможен после пополнения лимита Tavily.</p>}
          {startError && <p className="error" role="alert">{startError}</p>}
          {statusFailed && <p className="error" role="alert">Не удалось обновить состояние сбора. Запрос повторится автоматически.</p>}
        </section>
      </div>
      {running && (
        <section className="card">
          <h2>Что происходит сейчас</h2>
          <pre className="log">{running.tail.join("\n") || "Сбор идёт. Сообщения о ходе работы появятся после первого поискового запроса…"}</pre>
          <p className="hint">Следующее обновление запрашивается через 5 секунд после ответа.</p>
        </section>
      )}
      {historyFailed && <p className="error" role="alert">Не удалось загрузить историю запусков.</p>}
      {history && <RunHistory history={history} />}
    </>
  );
}
