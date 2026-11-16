import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, apiGet } from "../api";
import type { CaseList, CaseRow, Level, Meta, Option } from "../types";

const selectFilters = [
  { name: "level", label: "Уровень", empty: "Все уровни" },
  { name: "status", label: "Подтверждение", empty: "Любое" },
  { name: "reliability", label: "Достоверность", empty: "Любая" },
] as const;
type FilterOptions = Record<(typeof selectFilters)[number]["name"], Option[]>;
type Sort = { index: number; direction: "ascending" | "descending" };
const textFilters = ["q", ...selectFilters.map(({ name }) => name)] as const;
const warning = "Цифра не найдена в тексте статьи — проверьте по ссылке";
const levelClasses: Record<Level, string> = {
  мир: "level-world",
  "регионы РФ": "level-rf_regions",
  "Свердловская область": "level-sverdlovsk",
};
const reliabilityRanks = ["высокая", "средняя", "низкая"];
const columns: {
  label: string;
  value?: (row: CaseRow) => string;
  secondary?: (row: CaseRow) => string;
  title?: string;
}[] = [
  { label: "Уровень", value: (row) => row.level },
  { label: "Регион", value: (row) => row.region || row.country },
  { label: "Кейс", value: (row) => row.title, secondary: (row) => row.organization ?? "" },
  { label: "Главная цифра" },
  { label: "Стадия", value: (row) => row.stage },
  { label: "Статус", value: (row) => row.status_label },
  {
    label: "Достоверность",
    value: (row) => String(reliabilityRanks.includes(row.reliability ?? "")
      ? reliabilityRanks.indexOf(row.reliability ?? "") : reliabilityRanks.length),
    title: "Лучшая оценка среди источников кейса",
  },
  { label: "В базе с", value: (row) => row.first_seen, title: "Когда кейс впервые попал в базу" },
];
const collator = new Intl.Collator("ru", { numeric: true, sensitivity: "base" });

function queryFromAddress(search: URLSearchParams) {
  const query = new URLSearchParams();
  for (const key of textFilters) {
    const value = search.get(key);
    if (value) query.set(key, value);
  }
  query.set("metrics", search.get("metrics") === "0" ? "0" : "1");
  if (search.get("doubtful") === "1") query.set("doubtful", "1");
  return query;
}

function CasesFilters({ query, options }: { query: URLSearchParams; options: FilterOptions }) {
  const [, setSearch] = useSearchParams();

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const search = new URLSearchParams();
    for (const key of textFilters) {
      const value = String(data.get(key) ?? "");
      if (value) search.set(key, value);
    }
    search.set("metrics", data.has("metrics") ? "1" : "0");
    if (data.has("doubtful")) search.set("doubtful", "1");
    setSearch(search);
  }

  return (
    <form className="filters card" method="get" action="/" onSubmit={submit}>
      <label className="field field-grow">
        <span>Поиск</span>
        <input type="search" name="q" defaultValue={query.get("q") ?? ""}
          placeholder="Например: Екатеринбург, водоканал, чат-бот" />
      </label>
      {selectFilters.map(({ name, label, empty }) => {
        const current = query.get(name) ?? "";
        return (
          <label className="field" key={name}>
            <span>{label}</span>
            <select name={name} defaultValue={current}>
              <option value="">{empty}</option>
              {current && !options[name].some(({ value }) => value === current) && (
                <option value={current}>{current} (устаревшее значение)</option>
              )}
              {options[name].map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
        );
      })}
      <div className="checks">
        <label className="check">
          <input type="checkbox" name="metrics" value="1" defaultChecked={query.get("metrics") === "1"} />
          {" "}только с цифрами
        </label>
        <label className="check">
          <input type="checkbox" name="doubtful" value="1" defaultChecked={query.get("doubtful") === "1"} />
          {" "}скрыть сомнительные
        </label>
      </div>
      <div className="filter-actions">
        <button className="btn btn-primary" type="submit">Показать</button>
        <Link className="btn btn-ghost" to="/" onClick={(event) => event.currentTarget.closest("form")?.reset()}>
          Сбросить
        </Link>
      </div>
    </form>
  );
}

function CasesTable({ rows }: { rows: CaseRow[] }) {
  const { pathname, search, hash, state } = useLocation();
  const navigate = useNavigate();
  const sorts: Sort[] = state?.casesSorts ?? [];
  const primary = sorts[0];
  // При равенстве сохраняем порядок, заданный предыдущими сортировками.
  const sorted = [...rows];
  for (const { index, direction } of [...sorts].reverse()) {
    const { value, secondary } = columns[index];
    if (!value) continue;
    const sign = direction === "ascending" ? 1 : -1;
    sorted.sort((a, b) => {
      const comparison = collator.compare(value(a), value(b));
      return sign * (comparison || (secondary ? collator.compare(secondary(a), secondary(b)) : 0));
    });
  }

  function sortBy(index: number) {
    const next: Sort = {
      index,
      direction: primary?.index === index && primary.direction === "ascending" ? "descending" : "ascending",
    };
    navigate({ pathname, search, hash }, {
      replace: true,
      preventScrollReset: true,
      state: { casesSorts: [next, ...sorts.filter((sort) => sort.index !== index)] },
    });
  }

  return (
    <>
      <div className="table-wrap card">
        <table className="table sortable">
          <thead>
            <tr>
              {columns.map(({ label, value, title }, index) => value ? (
                <th key={label} scope="col" data-sort="text" tabIndex={0} title={title ?? "Сортировать"}
                  aria-sort={primary?.index === index ? primary.direction : undefined}
                  onClick={() => sortBy(index)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      sortBy(index);
                    }
                  }}>
                  {label}
                </th>
              ) : <th key={label} scope="col">{label}</th>)}
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.id}>
                <td><span className={`level ${levelClasses[row.level]}`}>{row.level}</span></td>
                <td className="col-region">{row.region || row.country}</td>
                <td className="case-title">
                  <Link to={`/case/${encodeURIComponent(row.id)}`} state={{ casesSearch: search }}>{row.title}</Link>
                  {row.organization && <small>{row.organization}</small>}
                </td>
                <td className="headline">
                  {row.headline}
                  {row.headline_unverified && <> <span className="warn-mark" title={warning}>⚠</span></>}
                </td>
                <td className="nowrap">{row.stage}</td>
                <td><span className={`pill pill-${row.status_class}`}>{row.status_label}</span></td>
                <td><span className={`pill pill-${row.reliability_class}`}>{row.reliability_label}</span></td>
                <td className="nowrap">{row.first_seen.split("-").reverse().join(".")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">Клик по заголовку колонки сортирует таблицу. ⚠ — цифру не удалось найти в тексте статьи.</p>
    </>
  );
}

function NoMatches() {
  return (
    <div className="empty card">
      <h2>Ничего не нашлось</h2>
      <p className="muted">Попробуйте убрать часть фильтров или <Link to="/">сбросить</Link> их.</p>
    </div>
  );
}

function CasesResults({ query, unmatched, validateOnServer }: {
  query: string;
  unmatched: boolean;
  validateOnServer: boolean;
}) {
  const [data, setData] = useState<CaseList>();
  const [failure, setFailure] = useState<"unmatched" | "error">();

  useEffect(() => {
    let active = true;
    apiGet<CaseList>(`/api/cases?${query}`).then(
      (result) => { if (active) setData(result); },
      (error: unknown) => {
        if (!active) return;
        const invalidFilters = validateOnServer && error instanceof ApiError && error.status === 422;
        setFailure(invalidFilters ? "unmatched" : "error");
      },
    );
    return () => { active = false; };
  }, [query, validateOnServer]);

  if (failure === "unmatched") return <NoMatches />;
  if (failure === "error") return <p className="notice notice-bad" role="alert">Не удалось загрузить кейсы.</p>;
  if (!data) return <p className="muted" role="status">Загрузка кейсов…</p>;

  const { total, updated } = data;
  const cases = unmatched ? [] : data.cases;
  return (
    <>
      <p className="summary">
        <b>Найдено {cases.length} из {total}</b>
        {updated && <>
          <span className="dot">·</span> база обновлена{" "}
          {updated.slice(0, 10).split("-").reverse().join(".")} {updated.slice(11, 16)}
        </>}
      </p>
      {total === 0 ? (
        <div className="empty card">
          <h2>Кейсов пока нет</h2>
          <p className="muted">Запустите сбор на странице <Link to="/run">«Запуск сбора»</Link> — через несколько минут здесь появятся кейсы.</p>
        </div>
      ) : cases.length === 0 ? (
        <NoMatches />
      ) : <CasesTable rows={cases} />}
    </>
  );
}

export function Cases() {
  const [search] = useSearchParams();
  const location = useLocation();
  const query = queryFromAddress(search);
  const [meta, setMeta] = useState<Meta>();
  const [metaFailed, setMetaFailed] = useState(false);
  const options: FilterOptions | undefined = meta && {
    level: meta.levels.map((level) => ({ value: level, label: level })),
    status: meta.statuses,
    reliability: meta.reliability,
  };
  const needsOptions = selectFilters.some(({ name }) => query.has(name));
  const apiQuery = new URLSearchParams(query);
  if (options) {
    for (const { name } of selectFilters) {
      const current = query.get(name);
      if (current && !options[name].some(({ value }) => value === current)) apiQuery.delete(name);
    }
  }
  const requestQuery = apiQuery.toString();

  useEffect(() => {
    let active = true;
    apiGet<Meta>("/api/meta").then(
      (result) => { if (active) setMeta(result); },
      () => { if (active) setMetaFailed(true); },
    );
    return () => { active = false; };
  }, []);

  return (
    <>
      <section className="hero">
        <div>
          <h1>Кейсы внедрения ИИ</h1>
          <p className="muted">Мир, регионы России и Свердловская область. Каждая цифра — с дословной цитатой из статьи.</p>
        </div>
        <a className="btn btn-ghost" href="/api/export.xlsx" title="Вся база в Excel">Выгрузить в Excel</a>
      </section>
      {options && <CasesFilters key={`filters:${location.search}`} query={query} options={options} />}
      {metaFailed && <p className="notice notice-bad" role="alert">Не удалось загрузить варианты фильтров.</p>}
      {options || !needsOptions || metaFailed ? (
        <CasesResults
          key={`results:${requestQuery}`}
          query={requestQuery}
          unmatched={requestQuery !== query.toString()}
          validateOnServer={metaFailed && needsOptions}
        />
      ) : <p className="muted" role="status">Загрузка кейсов…</p>}
    </>
  );
}
