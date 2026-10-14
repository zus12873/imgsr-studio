import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mockFetch } from "./test/fetch";
import { renderApp } from "./test/utils";

const alice = { id: 1, username: "alice", role: "user", daily_quota: 50, used_today: 2 };

test("unauthenticated visits are sent to the login page", async () => {
  mockFetch({ "/api/me": json(401, { detail: "请先登录" }) });
  renderApp("/");
  expect(await screen.findByRole("heading", { name: "登录 imgsr" })).toBeInTheDocument();
});

test("logging in returns to the page the user came from", async () => {
  let loggedIn = false;
  const calls = mockFetch({
    "/api/me": () => (loggedIn ? alice : json(401, { detail: "请先登录" })),
    "POST /api/auth/login": () => {
      loggedIn = true;
      return alice;
    },
    "/api/tasks": { items: [], next_cursor: null },
  });
  renderApp("/history");
  await userEvent.type(await screen.findByLabelText("用户名"), "alice");
  await userEvent.type(screen.getByLabelText("密码"), "password123");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));
  expect(await screen.findByRole("heading", { name: "历史" })).toBeInTheDocument();
  expect(screen.getByText(/alice · 今日 2\/50/)).toBeInTheDocument();
  const login = calls.find((c) => c.url === "/api/auth/login");
  expect(JSON.parse(login?.init?.body as string)).toEqual({ username: "alice", password: "password123" });
});

test("a wrong password shows the server message", async () => {
  mockFetch({
    "/api/me": json(401, { detail: "请先登录" }),
    "POST /api/auth/login": json(401, { detail: "用户名或密码错误" }),
  });
  renderApp("/login");
  await userEvent.type(screen.getByLabelText("用户名"), "alice");
  await userEvent.type(screen.getByLabelText("密码"), "nope");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("用户名或密码错误");
});

test("only admins see the admin link", async () => {
  mockFetch({ "/api/me": alice, "/api/tasks": { items: [], next_cursor: null } });
  renderApp("/");
  expect(await screen.findByRole("link", { name: "工作台" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "管理" })).not.toBeInTheDocument();
});

test("admins see the admin link", async () => {
  mockFetch({ "/api/me": { ...alice, role: "admin" }, "/api/tasks": { items: [], next_cursor: null } });
  renderApp("/");
  expect(await screen.findByRole("link", { name: "管理" })).toBeInTheDocument();
});

test("unknown routes show the not-found page", async () => {
  mockFetch({ "/api/me": alice });
  renderApp("/nope/nope");
  expect(await screen.findByText("页面不存在")).toBeInTheDocument();
});
