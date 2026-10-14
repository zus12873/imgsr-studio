import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mockFetch } from "../test/fetch";
import { renderWithProviders } from "../test/utils";
import AdminPage from "./AdminPage";

const users = [
  { id: 1, username: "root", role: "admin", daily_quota: 50, disabled: false, created_at: "2026-10-14T06:00:00", used_today: 3 },
  { id: 2, username: "bob", role: "user", daily_quota: 50, disabled: false, created_at: "2026-10-14T06:00:00", used_today: 0 },
];
const settings = {
  effective: { image_model: "gpt-image-2.5", pixel_cap: 1550000 },
  overrides: {},
  restart_required: ["upstream_concurrency"],
};

function setup(extra: Record<string, unknown> = {}) {
  const calls = mockFetch({ "/api/admin/users": users, "/api/admin/settings": settings, ...extra });
  renderWithProviders(<AdminPage />);
  return calls;
}

const lastBody = (calls: { url: string; init?: RequestInit }[], url: string) =>
  JSON.parse([...calls].reverse().find((c) => c.url === url && c.init?.method !== "GET")?.init?.body as string);

test("creates a user with a default quota", async () => {
  const calls = setup({ "POST /api/admin/users": users[1] });
  await userEvent.type(await screen.findByLabelText("新用户名"), "carol");
  await userEvent.type(screen.getByLabelText("新用户密码"), "password123");
  await userEvent.click(screen.getByRole("button", { name: "新建用户" }));
  expect(lastBody(calls, "/api/admin/users")).toEqual({ username: "carol", password: "password123", role: "user", daily_quota: null });
});

test("disables a user and edits the quota", async () => {
  const calls = setup({ "PATCH /api/admin/users/2": users[1] });
  const rowButtons = await screen.findAllByRole("button", { name: "禁用" });
  await userEvent.click(rowButtons[1]);
  expect(lastBody(calls, "/api/admin/users/2")).toEqual({ disabled: true });
  const quota = screen.getByLabelText("bob 的每日额度");
  await userEvent.clear(quota);
  await userEvent.type(quota, "5");
  fireEvent.blur(quota);
  await waitFor(() => expect(lastBody(calls, "/api/admin/users/2")).toEqual({ daily_quota: 5 }));
});

test("resets a password inline", async () => {
  const calls = setup({ "PATCH /api/admin/users/2": users[1] });
  const resets = await screen.findAllByRole("button", { name: "重置密码" });
  await userEvent.click(resets[1]);
  await userEvent.type(screen.getByLabelText("bob 的新密码"), "newpassword1");
  await userEvent.click(screen.getByRole("button", { name: "保存密码" }));
  expect(lastBody(calls, "/api/admin/users/2")).toEqual({ password: "newpassword1" });
});

test("saves only changed settings with numbers kept numeric", async () => {
  const calls = setup({ "PATCH /api/admin/settings": settings });
  const save = await screen.findByRole("button", { name: "保存设置" });
  expect(save).toBeDisabled();
  await userEvent.clear(screen.getByLabelText("单次输出像素上限"));
  await userEvent.type(screen.getByLabelText("单次输出像素上限"), "1200000");
  await userEvent.click(save);
  expect(lastBody(calls, "/api/admin/settings")).toEqual({ pixel_cap: 1200000 });
});

test("setting validation errors are shown", async () => {
  setup({ "PATCH /api/admin/settings": json(400, { detail: "pixel_cap 必须在 100000 到 20000000 之间" }) });
  await userEvent.clear(await screen.findByLabelText("单次输出像素上限"));
  await userEvent.type(screen.getByLabelText("单次输出像素上限"), "10");
  await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("pixel_cap 必须在 100000 到 20000000 之间");
});
