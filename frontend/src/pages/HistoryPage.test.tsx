import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockFetch } from "../test/fetch";
import { renderWithProviders } from "../test/utils";
import HistoryPage from "./HistoryPage";

const item = (id: string) => ({
  id,
  status: "done" as const,
  source_w: 400,
  source_h: 300,
  created_at: "2026-10-14T06:00:00",
  final_round_id: 1,
  rounds: 2,
});

test("lists tasks and loads more with the cursor", async () => {
  const calls = mockFetch({
    "/api/tasks": (_init: RequestInit | undefined, url: string) =>
      url.includes("cursor=")
        ? { items: [item("cccccccc")], next_cursor: null }
        : { items: [item("aaaaaaaa"), item("bbbbbbbb")], next_cursor: "2026-10-14T05:00:00" },
  });
  renderWithProviders(<HistoryPage />);
  expect(await screen.findByRole("link", { name: "任务 aaaaaaaa" })).toHaveAttribute("href", "/tasks/aaaaaaaa");
  expect(screen.getAllByText(/2 轮/)).toHaveLength(2);
  await userEvent.click(screen.getByRole("button", { name: "加载更多" }));
  expect(await screen.findByRole("link", { name: "任务 cccccccc" })).toBeInTheDocument();
  expect(calls.some((c) => c.url.includes("cursor=2026-10-14T05%3A00%3A00"))).toBe(true);
});

test("deleting asks for a second click", async () => {
  const calls = mockFetch({
    "/api/tasks": { items: [item("aaaaaaaa")], next_cursor: null },
    "DELETE /api/tasks/aaaaaaaa": new Response(null, { status: 204 }),
  });
  renderWithProviders(<HistoryPage />);
  await userEvent.click(await screen.findByRole("button", { name: "删除任务 aaaaaaaa" }));
  expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "确认删除任务 aaaaaaaa" }));
  expect(calls.some((c) => c.init?.method === "DELETE")).toBe(true);
});
