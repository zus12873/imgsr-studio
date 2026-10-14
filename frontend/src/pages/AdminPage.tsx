import { useState } from "react";
import {
  useAdminSettings,
  useAdminUsers,
  useCreateUser,
  usePatchSettings,
  usePatchUser,
} from "../api/hooks";
import type { AdminUser, SettingsView } from "../api/types";
import { ErrorNote } from "../components/ErrorNote";

const SETTING_LABEL: Record<string, string> = {
  image_model: "生图模型",
  transcribe_model: "转写模型",
  review_model: "审查模型",
  pixel_cap: "单次输出像素上限",
  upstream_concurrency: "上游并发（重启后生效）",
  guest_daily_per_ip: "游客每 IP 每日次数",
  guest_daily_global: "游客全站每日次数",
  user_daily_default: "新用户默认每日额度",
  retention_user_days: "登录用户保留天数",
  retention_guest_hours: "游客保留小时数",
  max_upload_mb: "上传大小上限（MB）",
  max_pixels: "上传像素上限",
};

export default function AdminPage() {
  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold">管理</h1>
      <UsersSection />
      <SettingsSection />
    </div>
  );
}

function UsersSection() {
  const users = useAdminUsers();
  const create = useCreateUser();
  const patch = usePatchUser();
  const [form, setForm] = useState({ username: "", password: "", role: "user" as "user" | "admin", quota: "" });
  const [resetFor, setResetFor] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const error = users.error ?? create.error ?? patch.error;
  return (
    <section className="space-y-3">
      <h2 className="font-semibold">用户</h2>
      {error && <ErrorNote error={error} />}
      <form
        className="flex flex-wrap items-end gap-2 rounded-xl border border-slate-200 bg-white p-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            {
              username: form.username.trim(),
              password: form.password,
              role: form.role,
              daily_quota: form.quota === "" ? null : Number(form.quota),
            },
            { onSuccess: () => setForm({ username: "", password: "", role: "user", quota: "" }) },
          );
        }}
      >
        <label className="text-sm">
          用户名
          <input aria-label="新用户名" className="input mt-1" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
        </label>
        <label className="text-sm">
          密码
          <input aria-label="新用户密码" type="password" className="input mt-1" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </label>
        <label className="text-sm">
          角色
          <select aria-label="新用户角色" className="input mt-1" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as "user" | "admin" })}>
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </select>
        </label>
        <label className="text-sm">
          每日额度
          <input aria-label="新用户额度" type="number" min={0} placeholder="默认" className="input mt-1 w-24" value={form.quota} onChange={(e) => setForm({ ...form, quota: e.target.value })} />
        </label>
        <button type="submit" className="btn-primary" disabled={create.isPending}>
          新建用户
        </button>
      </form>
      <div className="overflow-x-auto">
        <table className="w-full rounded-xl border border-slate-200 bg-white text-sm">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="p-2">用户名</th>
              <th>角色</th>
              <th>今日/额度</th>
              <th>状态</th>
              <th className="p-2">操作</th>
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id} className="border-t border-slate-100">
                <td className="p-2">{u.username}</td>
                <td>{u.role === "admin" ? "管理员" : "普通用户"}</td>
                <td>
                  <QuotaEditor user={u} onSave={(q) => patch.mutate({ id: u.id, daily_quota: q })} />
                </td>
                <td>{u.disabled ? "已禁用" : "正常"}</td>
                <td className="space-x-2 p-2 whitespace-nowrap">
                  <button type="button" className="btn-secondary" onClick={() => patch.mutate({ id: u.id, disabled: !u.disabled })}>
                    {u.disabled ? "启用" : "禁用"}
                  </button>
                  {resetFor === u.id ? (
                    <span className="inline-flex gap-1">
                      <input aria-label={`${u.username} 的新密码`} type="password" className="input w-36" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() =>
                          patch.mutate(
                            { id: u.id, password: newPassword },
                            {
                              onSuccess: () => {
                                setResetFor(null);
                                setNewPassword("");
                              },
                            },
                          )
                        }
                      >
                        保存密码
                      </button>
                    </span>
                  ) : (
                    <button type="button" className="btn-secondary" onClick={() => setResetFor(u.id)}>
                      重置密码
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function QuotaEditor({ user, onSave }: { user: AdminUser; onSave: (quota: number) => void }) {
  const [value, setValue] = useState(String(user.daily_quota));
  return (
    <span className="inline-flex items-center gap-1">
      {user.used_today}/
      <input
        aria-label={`${user.username} 的每日额度`}
        type="number"
        min={0}
        className="input w-20"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => {
          if (value !== "" && Number(value) !== user.daily_quota) onSave(Number(value));
        }}
      />
    </span>
  );
}

function SettingsSection() {
  const settings = useAdminSettings();
  const patch = usePatchSettings();
  if (!settings.data) return settings.error ? <ErrorNote error={settings.error} /> : null;
  return <SettingsForm view={settings.data} pending={patch.isPending} error={patch.error} onSave={(c) => patch.mutate(c)} />;
}

function SettingsForm({
  view,
  pending,
  error,
  onSave,
}: {
  view: SettingsView;
  pending: boolean;
  error: unknown;
  onSave: (changes: Record<string, string | number>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(view.effective).map(([k, v]) => [k, String(v)])),
  );
  const changes: Record<string, string | number> = Object.fromEntries(
    Object.entries(values)
      .filter(([k, v]) => v !== String(view.effective[k]))
      .map(([k, v]) => [k, typeof view.effective[k] === "number" ? Number(v) : v]),
  );
  return (
    <form
      className="space-y-3 rounded-xl border border-slate-200 bg-white p-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSave(changes);
      }}
    >
      <h2 className="font-semibold">系统设置</h2>
      {error ? <ErrorNote error={error} /> : null}
      <div className="grid gap-3 sm:grid-cols-2">
        {Object.keys(view.effective).map((key) => (
          <label key={key} className="text-sm">
            {SETTING_LABEL[key] ?? key}
            <input
              aria-label={SETTING_LABEL[key] ?? key}
              className="input mt-1"
              value={values[key]}
              onChange={(e) => setValues({ ...values, [key]: e.target.value })}
            />
          </label>
        ))}
      </div>
      <button type="submit" className="btn-primary" disabled={pending || Object.keys(changes).length === 0}>
        保存设置
      </button>
    </form>
  );
}
