import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mockFetch } from "../test/fetch";
import { makeTask } from "../test/fixtures";
import { renderWithProviders } from "../test/utils";
import WorkbenchPage from "./WorkbenchPage";

const empty = { items: [], next_cursor: null };

test("uploading a screenshot opens its task page", async () => {
  const calls = mockFetch({
    "/api/tasks": empty,
    "POST /api/tasks": makeTask({ id: "new1", status: "uploaded" }),
  });
  renderWithProviders(<WorkbenchPage />);
  await userEvent.upload(screen.getByTestId("file-input"), new File(["x"], "a.png", { type: "image/png" }));
  expect(await screen.findByTestId("location")).toHaveTextContent("/tasks/new1");
  const post = calls.find((c) => c.init?.method === "POST");
  expect((post?.init?.body as FormData).get("file")).toBeInstanceOf(File);
});

test("upload errors are shown", async () => {
  mockFetch({ "/api/tasks": empty, "POST /api/tasks": json(400, { detail: "只支持 PNG、JPG、WebP 图片" }) });
  renderWithProviders(<WorkbenchPage />);
  await userEvent.upload(screen.getByTestId("file-input"), new File(["x"], "a.png", { type: "image/png" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("只支持 PNG、JPG、WebP 图片");
});

test("recent tasks link to their pages", async () => {
  mockFetch({
    "/api/tasks": {
      items: [{ id: "abcdef12", status: "done", source_w: 4, source_h: 3, created_at: "2026-10-14T06:00:00", final_round_id: 1, rounds: 1 }],
      next_cursor: null,
    },
  });
  renderWithProviders(<WorkbenchPage />);
  const link = await screen.findByRole("link", { name: /任务 abcdef12/ });
  expect(link).toHaveAttribute("href", "/tasks/abcdef12");
  expect(screen.getByText("已定稿")).toBeInTheDocument();
});
