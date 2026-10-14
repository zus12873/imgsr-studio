import { Route, Routes } from "react-router";
import { AppShell } from "./components/AppShell";
import { RequireAdmin, RequireAuth } from "./components/RequireAuth";
import AdminPage from "./pages/AdminPage";
import GuestPage from "./pages/GuestPage";
import HistoryPage from "./pages/HistoryPage";
import LoginPage from "./pages/LoginPage";
import NotFound from "./pages/NotFound";
import TaskPage from "./pages/TaskPage";
import WorkbenchPage from "./pages/WorkbenchPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/guest" element={<GuestPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<WorkbenchPage />} />
        <Route path="tasks/:id" element={<TaskPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route
          path="admin"
          element={
            <RequireAdmin>
              <AdminPage />
            </RequireAdmin>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
