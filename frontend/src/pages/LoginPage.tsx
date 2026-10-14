import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { useLogin } from "../api/hooks";
import { ErrorNote } from "../components/ErrorNote";

export default function LoginPage() {
  const login = useLogin();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <form
        className="w-full max-w-sm space-y-3 rounded-xl border border-slate-200 bg-white p-6"
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate({ username, password }, { onSuccess: () => navigate(from, { replace: true }) });
        }}
      >
        <h1 className="text-xl font-semibold">登录 imgsr</h1>
        <label className="block text-sm">
          用户名
          <input className="input mt-1" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </label>
        <label className="block text-sm">
          密码
          <input className="input mt-1" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        {login.error && <ErrorNote error={login.error} sessionAware={false} />}
        <button type="submit" className="btn-primary w-full" disabled={login.isPending}>
          登录
        </button>
        <p className="text-center text-sm text-slate-500">
          没有账号？
          <Link to="/guest" className="text-indigo-600">
            临时使用
          </Link>
        </p>
      </form>
    </div>
  );
}
