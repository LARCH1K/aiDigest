import { Fragment, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { apiGet } from "../api";
import type { Reliability, SourceInfo, SourcesResp } from "../types";

const filterFields = ["level", "reliability"] as const;
const anyRfLabel = "регионы РФ и Свердловская область";
const reliabilityStyle: Record<Reliability, string> = {
  высокая: "ok", средняя: "warn", низкая: "bad", не_оценена: "muted",
};
const reliabilityRanks = Object.keys(reliabilityStyle);
const collator = new Intl.Collator("ru", { numeric: true, sensitivity: "base" });
const columns: { label: string; value: (source: SourceInfo) => string }[] = [
  { label: "Название", value: (source) => source.name },
  { label: "Домены", value: (source) => source.domains.join(", ") },
  { label: "Уровень", value: (source) => source.level ?? anyRfLabel },
  { label: "Достоверность", value: (source) => String(reliabilityRanks.indexOf(source.reliability)) },
  { label: "Тип информации", value: (source) => source.source_type },
  { label: "Обновление", value: (source) => source.update_frequency },
];

function sourceFilters(entries: URLSearchParams | FormData) {
  const query = new URLSearchParams();
  for (const field of filterFields) {
    const value = entries.get(field);
    if (typeof value === "string" && value) query.set(field, value);
  }
  return query;
}

function SourceFilters({ query, data }: { query: URLSearchParams; data: SourcesResp }) {
  const [, setSearch] = useSearchParams();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSearch(sourceFilters(new FormData(event.currentTarget)));
  }

  return (
    <form className="filters card" method="get" action="/sources" onSubmit={submit}>
      <label className="field">
        <span>Уровень</span>
        <select name="level" defaultValue={query.get("level") ?? ""}>
          <option value="">Все уровни</option>
          {data.level_options.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <label className="field">
        <span>Достоверность</span>
        <select name="reliability" defaultValue={query.get("reliability") ?? ""}>
          <option value="">Любая</option>
          {data.reliability_options.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
        </select>
      </label>
      <div className="filter-actions">
        <button className="btn btn-primary" type="submit">Показать</button>
        <Link className="btn btn-ghost" to="/sources">Сбросить</Link>
      </div>
    </form>
  );
}

function SourceTable({ sources, ratings }: { sources: SourceInfo[]; ratings: SourcesResp["reliability_options"] }) {
  const [sort, setSort] = useState<{ column: number; direction: "ascending" | "descending" }>();
  const sorted = sort ? [...sources].sort((a, b) => {
    const { value } = columns[sort.column];
    return collator.compare(value(a), value(b)) * (sort.direction === "ascending" ? 1 : -1);
  }) : sources;

  function sortBy(column: number) {
    setSort((previous) => ({
      column,
      direction: previous?.column === column && previous.direction === "ascending" ? "descending" : "ascending",
    }));
  }

  return (
    <>
      <div className="table-wrap card">
        <table className="table sortable">
          <thead><tr>
            {columns.map(({ label }, column) => (
              <th key={label} scope="col" data-sort="text" tabIndex={0}
                aria-sort={sort?.column === column ? sort.direction : undefined}
                onClick={() => sortBy(column)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    sortBy(column);
                  }
                }}>
                {label}
              </th>
            ))}
          </tr></thead>
          <tbody>
            {sorted.map((source) => (
              <tr key={JSON.stringify([source.name, source.level, source.domains])}>
                <td><b>{source.name}</b></td>
                <td>{source.domains.map((domain, index) => (
                  <Fragment key={index}>{index > 0 && ", "}<code>{domain}</code></Fragment>
                ))}</td>
                <td>{source.level ?? anyRfLabel}</td>
                <td><span className={`pill pill-${reliabilityStyle[source.reliability]}`}>
                  {ratings.find(({ value }) => value === source.reliability)?.label ?? source.reliability.replace("_", " ")}
                </span></td>
                <td>{source.source_type}</td>
                <td>{source.update_frequency || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">Клик по заголовку колонки сортирует таблицу.</p>
    </>
  );
}

function SourceResults({ query }: { query: URLSearchParams }) {
  const search = query.toString();
  const [data, setData] = useState<SourcesResp>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    apiGet<SourcesResp>(search ? `/api/sources?${search}` : "/api/sources").then(
      (result) => { if (active) setData(result); },
      () => { if (active) setFailed(true); },
    );
    return () => { active = false; };
  }, [search]);

  if (failed || data?.error) return (
    <section className="empty card">
      <h2>Справочник недоступен</h2>
      <p className="error" role="alert">{data?.error ?? "Не удалось загрузить справочник источников."}</p>
      {search && <Link to="/sources">Сбросить фильтры</Link>}
    </section>
  );
  if (!data) return <p className="muted" role="status">Загрузка справочника…</p>;

  return (
    <>
      <SourceFilters query={query} data={data} />
      <p className="summary"><b>Найдено {data.sources.length} из {data.total}</b></p>
      {data.sources.length > 0 ? <SourceTable sources={data.sources} ratings={data.reliability_options} /> : (
        <section className="empty card">
          <h2>Ничего не нашлось</h2>
          <p className="muted">Попробуйте <Link to="/sources">сбросить</Link> фильтры.</p>
        </section>
      )}
    </>
  );
}

export function Sources() {
  const [search] = useSearchParams();
  const { key } = useLocation();
  return (
    <>
      <section className="hero"><div>
        <h1>Справочник источников</h1>
        <p className="muted">Сайты, достоверность которых оценена. По этому списку сбор ставит оценку источникам кейсов и ограничивает поиск. Справочник правится в файле <code>config/sources.yaml</code> и попадает сюда после выкладки.</p>
      </div></section>

      <section className="card prose">
        <h2>Что означают поля</h2>
        <dl className="field-help">
          <dt>Название и домены</dt>
          <dd>Источник и его сайты. Статья с любого из этих доменов или их поддоменов получает оценку источника.</dd>
          <dt>Уровень</dt>
          <dd>Уровень запросов, для которых источник используется в поиске по справочнику (см. <Link to="/queries">«Запросы»</Link>). «{anyRfLabel}» — общероссийский источник, подходит обоим российским уровням. Оценка достоверности применяется к кейсам любого уровня.</dd>
          <dt>Достоверность</dt>
          <dd><b>высокая</b> — госорганы, статистика, международные организации. <b>средняя</b> — отраслевые СМИ, витрины кейсов, аналитика компаний. <b>низкая</b> — источники, которые требуют перепроверки. Оценки основаны на материалах команды «Аналитика». Оценки источников Свердловской области, Reuters и «Цифрового региона» выставила команда разработки, их стоит согласовать. Сайты вне справочника получают оценку <b>не оценена</b>, а кейс помечается флагом. Оценка ставится в момент сбора и сохраняется при последующих правках справочника.</dd>
          <dt>Тип информации</dt>
          <dd><b>официальная</b> — документы и новости госорганов. <b>статистика</b> — данные и исследования. <b>кейсы</b> — описания внедрений. <b>аналитика рынка</b> — обзоры и прогнозы. <b>СМИ</b> — новости.</dd>
          <dt>Обновление</dt>
          <dd>Как часто на источнике появляются новые материалы. Периодичность указана справочно, сбор от неё не зависит.</dd>
        </dl>
      </section>
      <SourceResults key={key} query={sourceFilters(search)} />
    </>
  );
}
