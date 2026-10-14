import { screen } from "@testing-library/react";
import { ApiError } from "../api/client";
import { renderWithProviders } from "../test/utils";
import { ErrorNote } from "./ErrorNote";

test("a 401 mid-session asks the user to log in again", () => {
  renderWithProviders(<ErrorNote error={new ApiError(401, "请先登录")} />);
  expect(screen.getByRole("alert")).toHaveTextContent("登录已过期，请重新登录");
  expect(screen.getByRole("link", { name: "去登录" })).toHaveAttribute("href", "/login");
});

test("other errors show the server message", () => {
  renderWithProviders(<ErrorNote error={new ApiError(429, "今日生成次数已用完")} />);
  expect(screen.getByRole("alert")).toHaveTextContent("今日生成次数已用完");
});

test("the login form shows 401 messages verbatim", () => {
  renderWithProviders(<ErrorNote error={new ApiError(401, "用户名或密码错误")} sessionAware={false} />);
  expect(screen.getByRole("alert")).toHaveTextContent("用户名或密码错误");
});
