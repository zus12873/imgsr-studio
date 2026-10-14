import { Link } from "react-router";
import { ApiError } from "../api/client";

export function ErrorNote({ error, sessionAware = true }: { error: unknown; sessionAware?: boolean }) {
  const expired = sessionAware && error instanceof ApiError && error.status === 401;
  const message = error instanceof Error ? error.message : "出错了，请稍后重试";
  return (
    <div role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">
      {expired ? "登录已过期，请重新登录。" : message}
      {expired && (
        <Link to="/login" className="ml-2 underline">
          去登录
        </Link>
      )}
    </div>
  );
}
