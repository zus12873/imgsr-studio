import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { ApiError } from "../api/client";
import { useMe } from "../api/hooks";
import { ErrorNote } from "./ErrorNote";

export function RequireAuth({ children }: { children: ReactNode }) {
  const me = useMe();
  const location = useLocation();
  if (me.isPending) return <p className="p-6 text-slate-500">加载中…</p>;
  if (me.error instanceof ApiError && me.error.status === 401) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (me.error) return <ErrorNote error={me.error} />;
  return <>{children}</>;
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const me = useMe();
  if (me.data?.role !== "admin") return <p className="text-slate-500">需要管理员权限。</p>;
  return <>{children}</>;
}
