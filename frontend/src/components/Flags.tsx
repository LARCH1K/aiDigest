import type { Flag, Meta } from "../types";

export function Flags({ flags, help, failed }: {
  flags: Flag[];
  help?: Meta["flag_help"];
  failed: boolean;
}) {
  return (
    <section className="card">
      <h2>Флаги</h2>
      {flags.length > 0 ? (
        <>
          {failed && <p className="error" role="alert">Не удалось загрузить пояснения к флагам.</p>}
          <ul className="flags">
            {flags.map((flag) => {
              const explanation = help?.[flag];
              return (
                <li key={flag}>
                  <code>{flag}</code>
                  {explanation && <>
                    <p>{explanation[0]}</p>
                    <p className="muted"><b>Что делать:</b> {explanation[1]}</p>
                  </>}
                </li>
              );
            })}
          </ul>
        </>
      ) : <p className="ok-line">✔ Сомнений нет: цифры подтверждены цитатами.</p>}
    </section>
  );
}
