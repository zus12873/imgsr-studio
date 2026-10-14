import { NavLink, Outlet, useNavigate } from "react-router";
import { useLogout, useMe } from "../api/hooks";

function navClass({ isActive }: { isActive: boolean }) {
  return `rounded-md px-3 py-1.5 text-sm ${isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100"}`;
}

export function AppShell() {
  const me = useMe();
  const logout = useLogout();
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-2 px-4 py-2">
          <span className="mr-4 font-semibold">imgsr</span>
          <NavLink to="/" end className={navClass}>
            工作台
          </NavLink>
          <NavLink to="/history" className={navClass}>
            历史
          </NavLink>
          {me.data?.role === "admin" && (
            <NavLink to="/admin" className={navClass}>
              管理
            </NavLink>
          )}
          <span className="ml-auto text-sm text-slate-500">
            {me.data?.username} · 今日 {me.data?.used_today}/{me.data?.daily_quota}
          </span>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => logout.mutate(undefined, { onSuccess: () => navigate("/login") })}
          >
            退出
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl p-4">
        <Outlet />
      </main>
    </div>
  );
}
