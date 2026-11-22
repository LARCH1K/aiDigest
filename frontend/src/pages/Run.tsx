import { useEffect, useRef, useState } from "react";
import { ApiError, apiGet, apiPost } from "../api";
import type { RunCurrent, RunRow, RunStarted } from "../types";
import { formatLabel } from "../formatLabel";

const noStore = { cache: "no-store" } as const;
const pollDelay = 5000;

function RunStatus({ run }: { run: RunRow }) {
  const tone = run.state === "ok" ? "ok"
    : ["limit", "interrupted", "busy"].includes(run.state) ? "warn"
    : run.state === "running" ? "muted" : "bad";
  return <span className={`pill pill-${tone}`}>{formatLabel(run.label)}</span>;
}

function DebugParams({ params }: { params: RunRow["params"] }) {
  const entries = Object.entries(params);
  if (entries.length === 0) return null;
  return (
    <small className="run-reason">
      <b>Отладочный</b> · {entries.map(([key, value]) =>
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
          {" · "}<LogLink id={last.run_id} label="Полный лог" />
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
                    <td><LogLink id={run.run_id} label="Лог" /></td>
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
  const [current, setCurrent] = useState<RunCurrent>();
  const [history, setHistory] = useState<RunRow[]>();
  const [statusFailed, setStatusFailed] = useState(false);
  const [historyFailed, setHistoryFailed] = useState(false);
  const [startError, setStartError] = useState("");
  const start = useRef<(() => void) | null>(null);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let historyRequest = 0;
    let lastStatus: RunCurrent | undefined;
    let initialHistoryHasRunning = false;

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
      if (!active || lastStatus?.running !== false) return;
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
      void loadHistory();
      void loadCurrent(false);
    });
    return () => {
      active = false;
      start.current = null;
      clearTimeout(timer);
    };
  }, []);

  const running = current?.running ? current : null;
  return (
    <>
      <section className="hero"><div>
        <h1>Запуск сбора</h1>
        <p className="muted">Сбор ищет свежие статьи за последние 30 дней, достаёт из них кейсы с цифрами и ищет подтверждения во втором издании. Обычно занимает 5–15 минут.</p>
      </div></section>
      <section className="card run-card" data-running={running ? "" : undefined}>
        <div className="run-controls">
          <div>
            <h2>{running ? "Идёт сбор" : "Новый сбор"}</h2>
            <p className="muted">
              {running
                ? `Начат в ${running.started.slice(11, 16)} (${running.minutes} мин назад). Можно закрыть страницу, сбор продолжится.`
                : "Новые кейсы появятся в реестре по мере обработки."}
            </p>
          </div>
          <button className="btn btn-primary" type="button"
            disabled={!current || !!running || statusFailed}
            onClick={() => start.current?.()}>
            Запустить сбор
          </button>
        </div>
        <div className="run-state" role="status">
          <span className="muted">Состояние</span>
          <span className={`pill pill-${current && !running && !statusFailed ? "ok" : "muted"}`}>
            {statusFailed ? "Статус недоступен" : running ? "Выполняется" : current ? "Готов к запуску" : "Проверяем состояние сбора…"}
          </span>
        </div>
        {startError && <p className="error" role="alert">{startError}</p>}
        {statusFailed && <p className="error" role="alert">Не удалось обновить состояние сбора. Запрос повторится автоматически.</p>}
      </section>
      {running && (
        <section className="card">
          <h2>Что происходит сейчас</h2>
          <pre className="log">{running.tail.join("\n") || "Сбор идёт. Сообщения о ходе работы появятся после первого поискового запроса…"}</pre>
          <p className="hint">Следующее обновление запрашивается через 5 секунд после ответа.</p>
        </section>
      )}
      {historyFailed && <p className="error" role="alert">Не удалось загрузить историю запусков.</p>}
      {history && (history.length > 0 ? <RunHistory history={history} /> : (
        <section className="card">
          <h2>История запусков</h2>
          <p className="muted">Запусков пока нет.</p>
        </section>
      ))}
    </>
  );
}
