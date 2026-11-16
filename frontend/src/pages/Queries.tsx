import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet } from "../api";
import type { Level, QueriesResp } from "../types";

const levelClasses: Record<Level, string> = {
  мир: "level-world",
  "регионы РФ": "level-rf_regions",
  "Свердловская область": "level-sverdlovsk",
};
const languages = new Map([["ru", "русский"], ["en", "английский"]]);

export function Queries() {
  const [data, setData] = useState<QueriesResp>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    apiGet<QueriesResp>("/api/queries").then(
      (result) => { if (active) setData(result); },
      () => { if (active) setFailed(true); },
    );
    return () => { active = false; };
  }, []);

  return (
    <>
      <section className="hero"><div>
        <h1>Поисковые запросы</h1>
        <p className="muted">С какими запросами сбор ищет статьи о внедрении ИИ. Список правится в файле <code>config/queries.yaml</code> и попадает сюда после выкладки.</p>
      </div></section>

      <section className="card prose">
        <h2>Что означают поля</h2>
        <dl className="field-help">
          <dt>Уровень</dt>
          <dd>Мир, регионы РФ или Свердловская область. Уровень запроса определяет набор сайтов при поиске по справочнику. Уровень самого кейса определяется по стране и региону из текста статьи и может отличаться от уровня запроса.</dd>
          <dt>Текст запроса</dt>
          <dd>Фраза, которую сбор отправляет в поисковый сервис Tavily. {data && <>Ищутся статьи за последние {data.freshness_days} дн. (настройка <code>freshness_days</code>). </>}Каждый запрос стоит 1 кредит Tavily (лимит — 1000 в месяц).</dd>
          <dt>Только по справочнику</dt>
          <dd><b>да</b> — поиск только по сайтам из <Link to="/sources">справочника источников</Link> для этого уровня. Круг поиска сужается, а результаты обычно надёжнее. <b>нет</b> — поиск по всему интернету, где встречается больше случайных статей.</dd>
          <dt>Язык</dt>
          <dd>Язык запроса. Для мирового уровня часть запросов на английском.</dd>
        </dl>
      </section>

      {failed || data?.error ? (
        <section className="empty card">
          <h2>Список запросов недоступен</h2>
          <p className="error" role="alert">{data?.error ?? "Не удалось загрузить поисковые запросы."}</p>
        </section>
      ) : !data ? <p className="muted" role="status">Загрузка запросов…</p>
        : data.total === 0 ? (
          <section className="empty card">
            <h2>Запросов нет</h2>
            <p className="muted">Файл <code>config/queries.yaml</code> пуст.</p>
          </section>
        ) : <>
          <p className="summary"><b>Всего запросов: {data.total}</b></p>
          {data.groups.map(({ level, queries }) => (
            <section className="card" key={level}>
              <h2><span className={`level ${levelClasses[level]}`}>{level}</span> <small className="muted">{queries.length}</small></h2>
              <div className="table-wrap">
                <table className="table">
                  <thead><tr>
                    <th scope="col">Текст запроса</th><th scope="col">Только по справочнику</th><th scope="col">Язык</th>
                  </tr></thead>
                  <tbody>
                    {queries.map((query, index) => (
                      <tr key={index}>
                        <td>{query.text}</td>
                        <td className="nowrap">
                          <span className={`pill pill-${query.use_registry_domains ? "ok" : "muted"}`}>
                            {query.use_registry_domains ? "да" : "нет"}
                          </span>
                        </td>
                        <td className="nowrap">{languages.get(query.language) ?? query.language}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </>}
    </>
  );
}
