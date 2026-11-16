import { Link } from "react-router-dom";

export function NotFound() {
  return (
    <section className="card empty">
      <h1>Страница не найдена</h1>
      <Link to="/">Перейти к кейсам</Link>
    </section>
  );
}
