import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, apiGet } from "../api";
import { Flags } from "../components/Flags";
import { safeUrl } from "../safeUrl";
import type { CaseDetail, Metric, Source } from "../types";

function caseDate(date: string) {
  return date.split("-").reverse().join(".");
}

function CaseHeader({ data }: { data: CaseDetail }) {
  const place = [data.region || data.country, data.municipality].filter(Boolean).join(", ");
  return (
    <section className="card case-head">
      <div className="case-head-top">
        <h1>{data.title}</h1>
        <span className={`pill pill-lg pill-${data.status_class}`}>{data.status_label}</span>
      </div>
      <dl className="props">
        <div><dt>Уровень</dt><dd>{data.level}</dd></div>
        <div><dt>Место</dt><dd>{place}</dd></div>
        {data.organization && <div><dt>Кто внедрил</dt><dd>{data.organization}</dd></div>}
        <div><dt>Сектор</dt><dd>{data.sector}</dd></div>
        {data.industry && <div><dt>Отрасль</dt><dd>{data.industry}</dd></div>}
        {data.ai_technology && <div><dt>Технология</dt><dd>{data.ai_technology}</dd></div>}
        <div><dt>Стадия</dt><dd>{data.stage}</dd></div>
        <div><dt>Методика</dt><dd>{data.methodology}</dd></div>
      </dl>
      {data.summary && <p className="summary-box">{data.summary}</p>}
    </section>
  );
}

function MetricRow({ metric }: { metric: Metric }) {
  const { before, after, change } = metric;
  const sourceLabel = metric.source_url.replace(/^https?:\/\//i, "");
  return (
    <tr>
      <td><b>{metric.name}</b>{metric.kind === "план" && <small className="tag">план</small>}</td>
      <td className="value">
        {before && after ? `${before} → ${after}` : after || before}
        {change && change !== after && <div className="change">{change}</div>}
      </td>
      <td>{metric.criterion}</td>
      <td className="quote">
        <blockquote>«{metric.quote}»</blockquote>
        <a className="src" href={safeUrl(metric.source_url)} target="_blank" rel="noopener noreferrer">
          {sourceLabel.length > 48 ? `${sourceLabel.slice(0, 47)}…` : sourceLabel}
        </a>
      </td>
      <td className="checks-cell">
        {metric.quote_verified
          ? <div className="ok-line">✔ цитата найдена в тексте</div>
          : <div className="bad-line">⚠ цитата или число не найдены</div>}
        {metric.confirmed_by.map((url, index) => {
          const href = safeUrl(url);
          return (
            <div className="ok-line" key={index}>
              ✔ подтверждено: <a href={href} target="_blank" rel="noopener noreferrer">
                {href === "#" ? url : new URL(href).host}
              </a>
            </div>
          );
        })}
        {metric.conflicting_values.map((value, index) => (
          <div className="bad-line" key={index}>≠ другое значение: {value}</div>
        ))}
      </td>
    </tr>
  );
}

function Metrics({ metrics }: { metrics: Metric[] }) {
  return (
    <section className="card">
      <h2>Показатели</h2>
      {metrics.length === 0 ? (
        <p className="muted">Измеримых цифр в статье нет — кейс годится как пример внедрения.</p>
      ) : (
        <div className="table-wrap">
          <table className="table metrics">
            <thead>
              <tr>
                <th scope="col">Показатель</th>
                <th scope="col">Значение</th>
                <th scope="col">Критерий</th>
                <th scope="col">Цитата из статьи</th>
                <th scope="col">Проверка</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((metric, index) => <MetricRow key={index} metric={metric} />)}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function Sources({ sources }: { sources: Source[] }) {
  return (
    <section className="card">
      <h2>Источники</h2>
      <ul className="sources">
        {sources.map((source, index) => {
          const tag = source.reliability === "высокая" ? "ok" : source.reliability === "средняя" ? "warn" : "muted";
          return (
            <li key={index}>
              <a href={safeUrl(source.url)} target="_blank" rel="noopener noreferrer">{source.title || source.domain}</a>
              <span className="muted">{source.domain}</span>
              <span className={`tag tag-${tag}`}>достоверность: {source.reliability.replace("_", " ")}</span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function CaseListLink({ children, className }: { children: ReactNode; className?: string }) {
  const { state } = useLocation();
  const navigate = useNavigate();
  const savedSearch = state?.casesSearch;
  const fromList = typeof savedSearch === "string" && (savedSearch === "" || savedSearch.startsWith("?"));
  return (
    <Link className={className} to={{ pathname: "/", search: fromList ? savedSearch : "" }} onClick={(event) => {
      if (!fromList || event.button !== 0 || event.metaKey || event.altKey || event.ctrlKey || event.shiftKey) return;
      event.preventDefault();
      navigate(-1);
    }}>
      {children}
    </Link>
  );
}

function CaseContent({ id }: { id: string }) {
  const [data, setData] = useState<CaseDetail>();
  const [failure, setFailure] = useState<"missing" | "error">();

  useEffect(() => {
    let active = true;
    apiGet<CaseDetail>(`/api/cases/${encodeURIComponent(id)}`).then(
      (result) => { if (active) setData(result); },
      (error: unknown) => {
        if (active) setFailure(error instanceof ApiError && error.status === 404 ? "missing" : "error");
      },
    );
    return () => { active = false; };
  }, [id]);

  if (failure === "missing") {
    return (
      <section className="empty card">
        <h1>Кейс не найден</h1>
        <p className="muted">Возможно, кейс был удалён при пересборке базы. Вернитесь к <CaseListLink>списку кейсов</CaseListLink>.</p>
      </section>
    );
  }
  if (failure === "error") return <p className="notice notice-bad" role="alert">Не удалось загрузить кейс.</p>;
  if (!data) return <p className="muted" role="status">Загрузка кейса…</p>;

  return (
    <>
      <CaseHeader data={data} />
      <Metrics metrics={data.metrics} />
      <div className="grid-2">
        <Sources sources={data.sources} />
        <Flags flags={data.flags} />
      </div>
      <p className="hint">Найден {caseDate(data.first_seen)}, обновлён {caseDate(data.updated)}.</p>
    </>
  );
}

export function CaseDetailPage() {
  const { id = "" } = useParams();

  return (
    <>
      <CaseListLink className="back">← к списку кейсов</CaseListLink>
      <CaseContent key={id} id={id} />
    </>
  );
}
