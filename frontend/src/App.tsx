import { Route, Routes } from "react-router-dom";
import { AuthProvider, RequireAuth } from "./auth";
import { Layout } from "./components/Layout";
import { CaseDetailPage } from "./pages/CaseDetail";
import { Cases } from "./pages/Cases";
import { Help } from "./pages/Help";
import { Login } from "./pages/Login";
import { NotFound } from "./pages/NotFound";
import { Queries } from "./pages/Queries";
import { Run } from "./pages/Run";
import { Sources } from "./pages/Sources";

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
            <Route path="/run" element={<Run />} />
            <Route path="/queries" element={<Queries />} />
            <Route path="/sources" element={<Sources />} />
            <Route path="/help" element={<Help />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  );
}
