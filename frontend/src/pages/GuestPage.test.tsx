import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mockFetch } from "../test/fetch";
import { makeRound } from "../test/fixtures";
import { renderWithProviders } from "../test/utils";
import GuestPage from "./GuestPage";

const quota = { limit: 3, remaining: 2, global_remaining: 90 };
const guestTask = (over = {}) => ({
  id: "g1",
  status: "done",
  source_w: 400,
  source_h: 300,
  created_at: "2026-10-14T06:00:00",
  expires_at: "2026-10-15T06:00:00",
  round: makeRound({ use_text_hint: false, review: null }),
  ...over,
});

test("shows the remaining quota and uploads with an optional prompt", async () => {
  const calls = mockFetch({ "/api/guest/quota": quota, "POST /api/guest/tasks": guestTask() });
  renderWithProviders(<GuestPage />, { route: "/guest", path: "/guest" });
  expect(await screen.findByText(/今日剩余 2 次/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("提示词"), "保持原样");
  await userEvent.upload(screen.getByTestId("file-input"), new File(["x"], "a.png", { type: "image/png" }));
  const body = calls.find((c) => c.init?.method === "POST")?.init?.body as FormData;
  expect(body.get("prompt")).toBe("保持原样");
  expect(await screen.findByRole("link", { name: "下载" })).toHaveAttribute("href", "/api/files/g1/download-1?download=1");
});

test("an exhausted quota disables uploading and explains why", async () => {
  mockFetch({ "/api/guest/quota": { ...quota, remaining: 0 } });
  renderWithProviders(<GuestPage />, { route: "/guest", path: "/guest" });
  expect(await screen.findByText(/今日剩余 0 次/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /拖入、粘贴或点击/ })).toHaveAttribute("aria-disabled", "true");
});

test("quota errors from the server are shown", async () => {
  mockFetch({
    "/api/guest/quota": quota,
    "POST /api/guest/tasks": json(429, { detail: "今日免费次数已用完，登录后可继续使用" }),
  });
  renderWithProviders(<GuestPage />, { route: "/guest", path: "/guest" });
  await userEvent.upload(await screen.findByTestId("file-input"), new File(["x"], "a.png", { type: "image/png" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("今日免费次数已用完");
});

test("refreshing with ?task= resumes the task", async () => {
  mockFetch({ "/api/guest/quota": quota, "/api/guest/tasks/g1": guestTask({ status: "generating", round: null }) });
  renderWithProviders(<GuestPage />, { route: "/guest?task=g1", path: "/guest" });
  expect(await screen.findByText("正在生成（约 1–3 分钟）…")).toBeInTheDocument();
});

test("a failed guest round explains and offers a fresh upload", async () => {
  mockFetch({
    "/api/guest/quota": quota,
    "/api/guest/tasks/g1": guestTask({ status: "round_failed", round: makeRound({ status: "failed", error: "上游繁忙：x", review: null }) }),
  });
  renderWithProviders(<GuestPage />, { route: "/guest?task=g1", path: "/guest" });
  expect(await screen.findByText(/上游繁忙：x/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "重新上传" }));
  expect(await screen.findByTestId("file-input")).toBeInTheDocument();
});
