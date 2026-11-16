import { Route, Routes } from "react-router-dom";
import { AuthProvider, RequireAuth } from "./auth";
import { Layout } from "./components/Layout";
import { CaseDetailPage } from "./pages/CaseDetail";
import { Cases } from "./pages/Cases";
import { Login } from "./pages/Login";
import { NotFound } from "./pages/NotFound";

function Placeholder({ title }: { title: string }) {
  return (
    <section className="card empty">
      <h1>{title}</h1>
      <p className="muted">Раздел в разработке.</p>
    </section>
  );
}

export function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route element={<Layout showNav={false} />}>
          <Route path="/login" element={<Login />} />
        </Route>
        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route index element={<Cases />} />
            <Route path="/case/:id" element={<CaseDetailPage />} />
            <Route path="/run" element={<Placeholder title="Запуск" />} />
            <Route path="/queries" element={<Placeholder title="Запросы" />} />
            <Route path="/sources" element={<Placeholder title="Источники" />} />
            <Route path="/help" element={<Placeholder title="Справка" />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  );
}
