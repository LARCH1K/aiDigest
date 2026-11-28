import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ApiError, apiGet } from "../api";
import { Flags } from "../components/Flags";
import { formatDate } from "../formatDate";
import { safeUrl } from "../safeUrl";
import type { CaseDetail, Meta, Metric, Option, PlanLink, QualitativeEvidence, Source } from "../types";
import { formatLabel } from "../formatLabel";

function CaseHeader({ data }: { data: CaseDetail }) {
  const place = [data.region || data.country, data.municipality].filter(Boolean).join(", ");
  return (
    <section className="card case-head">
      <div className="case-head-top">
        <h1>{data.title}</h1>
        <span className={`pill pill-lg pill-${data.status_class}`}>{formatLabel(data.status_label)}</span>
      </div>
      <dl className="props">
        <div><dt>Уровень</dt><dd>{formatLabel(data.level)}</dd></div>
        <div><dt>Место</dt><dd>{place}</dd></div>
        {data.organization && <div><dt>Кто внедрил</dt><dd>{data.organization}</dd></div>}
        <div><dt>Сектор</dt><dd>{formatLabel(data.sector)}</dd></div>
        {data.industry && <div><dt>Отрасль</dt><dd>{formatLabel(data.industry)}</dd></div>}
        {data.ai_technology && <div><dt>Технология</dt><dd>{data.ai_technology}</dd></div>}
        <div><dt>Стадия</dt><dd>{formatLabel(data.stage)}</dd></div>
        <div><dt>Методика</dt><dd>{data.methodology}</dd></div>
        <div><dt>Обновлён</dt><dd><time dateTime={data.updated}>{formatDate(data.updated)}</time></dd></div>
      </dl>
      {data.summary && <p className="summary-box">{data.summary}</p>}
    </section>
  );
}

const ratioFormat = new Intl.NumberFormat("ru", { maximumSignificantDigits: 4 });

function MetricRow({ metric, ratio }: { metric: Metric; ratio: number | null | undefined }) {
  const { before, after, change } = metric;
  const sourceLabel = metric.source_url.replace(/^https?:\/\//i, "");
  return (
    <tr>
      <td><b>{metric.name}</b>{metric.kind === "план" && <small className="tag">План</small>}</td>
      <td className="value">
        {before && after ? `${before} → ${after}` : after || before}
        {change && change !== after && <div className="change">{change}</div>}
        {ratio != null && <div className="hint">Р-1 (Base / Project) {ratioFormat.format(ratio)}</div>}
      </td>
      <td>{formatLabel(metric.criterion)}</td>
      <td className="quote">
        <blockquote>«{metric.quote}»</blockquote>
        <a className="src" href={safeUrl(metric.source_url)} target="_blank" rel="noopener noreferrer">
          {sourceLabel.length > 48 ? `${sourceLabel.slice(0, 47)}…` : sourceLabel}
        </a>
      </td>
      <td className="checks-cell">
        {metric.quote_verified
          ? <div className="ok-line">✔ Цитата найдена в тексте</div>
          : <div className="bad-line">⚠ Цитата или число не найдены</div>}
        {metric.confirmed_by.map((url, index) => {
          const href = safeUrl(url);
          const evidence = metric.confirmation_evidence?.find((item) => item.source_url === url);
          return (
            <div className="ok-line" key={index}>
              ✔ Подтверждено: <a href={href} target="_blank" rel="noopener noreferrer">
                {href === "#" ? url : new URL(href).host}
              </a>
              {evidence && <details className="quote">
                <summary>Как проверили</summary>
                <blockquote>«{evidence.quote}»</blockquote>
                {evidence.basis_quote !== evidence.quote && <blockquote>«{evidence.basis_quote}»</blockquote>}
              </details>}
            </div>
          );
        })}
        {metric.conflicting_values.map((value, index) => (
          <div className="bad-line" key={index}>≠ Другое значение: {value}</div>
        ))}
      </td>
    </tr>
  );
}

function PlanLinks({ links, indicators }: { links: PlanLink[]; indicators: Option[] }) {
  const byIndicator = new Map<string, PlanLink[]>();
  for (const link of links) {
    const evidence = byIndicator.get(link.indicator_id);
    if (evidence) evidence.push(link);
    else byIndicator.set(link.indicator_id, [link]);
  }
  return (
    <section className="card plan-links">
      <h2>Показатели нацплана</h2>
      {[...byIndicator].map(([id, evidence]) => {
        const indicator = indicators.find(({ value }) => value === id);
        return (
          <div className="plan-item" key={id}>
            <h3>{indicator ? `${id}. ${indicator.label}` : `Пункт ${id}`}</h3>
            <ul>
              {evidence.map(({ explanation, quote, source_url }) => (
                <li key={source_url} className="quote">
                  <p>{explanation}</p>
                  <blockquote>«{quote}»</blockquote>
                  <a className="src" href={safeUrl(source_url)} target="_blank" rel="noopener noreferrer">Публикация</a>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
    </section>
  );
}

function M1Profile({ profile }: { profile: Record<string, QualitativeEvidence[]> }) {
  return (
    <section className="card plan-links">
      <h2>Качественная карта М-1</h2>
      {Object.entries(profile).map(([criterion, items]) => (
        <div className="plan-item" key={criterion}>
          <h3>{formatLabel(criterion)}</h3>
          {items.length === 0 ? <p className="muted">Нет сохранённых свидетельств.</p> : (
            <ul>
              {items.map(({ fact, quote, source_url }, index) => (
                <li key={`${source_url}-${index}`} className="quote">
                  <p>{fact}</p>
                  <blockquote>«{quote}»</blockquote>
                  <a className="src" href={safeUrl(source_url)} target="_blank" rel="noopener noreferrer">Публикация</a>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </section>
  );
}

function Metrics({ metrics, ratios }: { metrics: Metric[]; ratios: (number | null)[] }) {
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
              {metrics.map((metric, index) => <MetricRow key={index} metric={metric} ratio={ratios[index]} />)}
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
          const published = formatDate(source.published_at);
          return (
            <li key={index}>
              <a href={safeUrl(source.url)} target="_blank" rel="noopener noreferrer">{source.title || source.domain}</a>
              <span className="muted">{source.domain}</span>
              {published
                ? <time className="muted" dateTime={source.published_at?.slice(0, 10)}>{published}</time>
                : <span className="muted">Дата публикации не указана</span>}
              <span className={`tag tag-${tag}`}>Достоверность: {source.reliability.replace("_", " ")}</span>
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
  const [meta, setMeta] = useState<Meta>();
  const [metaFailed, setMetaFailed] = useState(false);
  const needsMeta = Boolean(data && (data.flags.length || data.plan_links.length));

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

  useEffect(() => {
    if (!needsMeta) return;
    let active = true;
    apiGet<Meta>("/api/meta").then(
      (result) => { if (active) setMeta(result); },
      () => { if (active) setMetaFailed(true); },
    );
    return () => { active = false; };
  }, [needsMeta]);

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
      <Metrics metrics={data.metrics} ratios={data.r1_ratios} />
      {data.methodology === "М-1" && <M1Profile profile={data.m1_profile} />}
      {data.plan_links.length > 0 && (
        <PlanLinks links={data.plan_links} indicators={meta?.plan_indicators ?? []} />
      )}
      <div className="grid-2">
        <Sources sources={data.sources} />
        <Flags flags={data.flags} help={meta?.flag_help} failed={metaFailed} />
      </div>
      <p className="hint">В базе с <time dateTime={data.first_seen}>{formatDate(data.first_seen)}</time>.</p>
    </>
  );
}

export function CaseDetailPage() {
  const { id = "" } = useParams();

  return (
    <>
      <CaseListLink className="back">← К списку кейсов</CaseListLink>
      <CaseContent key={id} id={id} />
    </>
  );
}
