import { useEffect, useState } from "react";
import { apiGet } from "../api";
import type { Flag, Meta } from "../types";

function FlagList({ flags }: { flags: Flag[] }) {
  const [help, setHelp] = useState<Meta["flag_help"]>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    apiGet<Meta>("/api/meta").then(
      (meta) => { if (active) setHelp(meta.flag_help); },
      () => { if (active) setFailed(true); },
    );
    return () => { active = false; };
  }, []);

  return (
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
  );
}

export function Flags({ flags }: { flags: Flag[] }) {
  return (
    <section className="card">
      <h2>Флаги</h2>
      {flags.length > 0
        ? <FlagList flags={flags} />
        : <p className="ok-line">✔ Сомнений нет: цифры подтверждены цитатами.</p>}
    </section>
  );
}
