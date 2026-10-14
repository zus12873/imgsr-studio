import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mockFetch } from "../test/fetch";
import { makeRound, makeTask } from "../test/fixtures";
import { renderWithProviders } from "../test/utils";
import TaskPage from "./TaskPage";

function renderTask() {
  return renderWithProviders(<TaskPage />, { route: "/tasks/t1", path: "/tasks/:id" });
}

const bodyOf = (calls: { url: string; init?: RequestInit }[], url: string) =>
  JSON.parse(calls.find((c) => c.url === url)?.init?.body as string);

test("transcribing shows progress", async () => {
  mockFetch({ "/api/tasks/t1": makeTask({ status: "transcribing", transcript_raw: null, confirmed_text: null, busy: true }) });
  renderTask();
  expect(await screen.findByText("正在识别原文（约 1 分钟）…")).toBeInTheDocument();
});

test("confirming the transcript sends it", async () => {
  const calls = mockFetch({
    "/api/tasks/t1": makeTask({ status: "awaiting_confirm", confirmed_text: null, transcript_raw: "第一段。" }),
    "PUT /api/tasks/t1/text": makeTask({ status: "ready", confirmed_text: "第一段。" }),
  });
  renderTask();
  await userEvent.click(await screen.findByRole("button", { name: "确认原文" }));
  expect(bodyOf(calls, "/api/tasks/t1/text")).toEqual({ confirmed_text: "第一段。" });
  expect(await screen.findByRole("button", { name: "开始生成" })).toBeInTheDocument();
});

test("starting the first round posts the form", async () => {
  const calls = mockFetch({
    "/api/tasks/t1": makeTask({ status: "ready" }),
    "POST /api/tasks/t1/rounds": makeTask({ status: "generating", busy: true, rounds: [makeRound({ status: "queued", review: null })] }),
  });
  renderTask();
  await userEvent.click(await screen.findByRole("button", { name: "开始生成" }));
  expect(bodyOf(calls, "/api/tasks/t1/rounds")).toEqual({ prompt: null, strategy: "auto", preupscale: 1, use_text_hint: true });
  expect(await screen.findByText("正在生成（单轮约 1–3 分钟）…")).toBeInTheDocument();
});

test("a reviewed round shows comparison, downloads and executable suggestions", async () => {
  const round = makeRound({
    id: 7,
    review: {
      model: "gpt-6-sol",
      transcript: "x",
      diffs: [{ expected: "亮", found: "光", sentence: "发出亮光呢！" }],
      suggestions: [{ action: "retry_with_hint", reason: "带上完整原文重跑", diff_ids: [0], params: {} }],
    },
    strategy: { mode: "auto", preupscale: 1, plan: { mode: "tiles", tiles: [], notes: ["区域 (0, 0) 超过像素上限，该块会被模型缩小"] }, scale: 1 },
  });
  const calls = mockFetch({
    "/api/tasks/t1": makeTask({ rounds: [round] }),
    "POST /api/tasks/t1/rounds": makeTask({ status: "generating", busy: true, rounds: [round, makeRound({ id: 8, seq: 2, status: "queued", review: null })] }),
  });
  renderTask();
  expect(await screen.findByAltText("第 1 轮")).toHaveAttribute("src", "/api/files/t1/result-1");
  expect(screen.getByRole("link", { name: "下载" })).toHaveAttribute("href", "/api/files/t1/download-1?download=1");
  expect(screen.getByRole("link", { name: "原生分辨率" })).toHaveAttribute("href", "/api/files/t1/result-1?download=1");
  expect(screen.getByText(/该块会被模型缩小/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "执行" }));
  expect(bodyOf(calls, "/api/tasks/t1/rounds")).toEqual({ suggestion: { round_id: 7, index: 0 } });
});

test("accepting sets the final round", async () => {
  const calls = mockFetch({
    "/api/tasks/t1": makeTask({ rounds: [makeRound({ id: 7 })] }),
    "POST /api/tasks/t1/final": makeTask({ status: "done", final_round_id: 7, rounds: [makeRound({ id: 7 })] }),
  });
  renderTask();
  await userEvent.click(await screen.findByRole("button", { name: "设为最终版" }));
  expect(bodyOf(calls, "/api/tasks/t1/final")).toEqual({ round_id: 7 });
  expect(await screen.findByText("已定稿")).toBeInTheDocument();
});

test("a failed round can be retried", async () => {
  const calls = mockFetch({
    "/api/tasks/t1": makeTask({ status: "round_failed", rounds: [makeRound({ status: "failed", error: "上游繁忙：x", review: null })] }),
    "POST /api/tasks/t1/rounds/1/retry": makeTask({ status: "generating", busy: true, rounds: [makeRound({ status: "queued", review: null })] }),
  });
  renderTask();
  expect(await screen.findByText(/上游繁忙：x/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(calls.some((c) => c.url === "/api/tasks/t1/rounds/1/retry")).toBe(true);
});

test("quota errors are shown", async () => {
  mockFetch({
    "/api/tasks/t1": makeTask({ status: "ready" }),
    "POST /api/tasks/t1/rounds": json(429, { detail: "今日生成次数已用完，明天再来或联系管理员调整额度" }),
  });
  renderTask();
  await userEvent.click(await screen.findByRole("button", { name: "开始生成" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("今日生成次数已用完");
});

test("deleting needs a second click and returns to history", async () => {
  const calls = mockFetch({
    "/api/tasks/t1": makeTask({ status: "ready" }),
    "DELETE /api/tasks/t1": new Response(null, { status: 204 }),
  });
  renderTask();
  await userEvent.click(await screen.findByRole("button", { name: "删除" }));
  expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "确认删除" }));
  expect(await screen.findByTestId("location")).toHaveTextContent("/history");
});

test("a missing task shows the server message", async () => {
  mockFetch({ "/api/tasks/t1": json(404, { detail: "任务不存在" }) });
  renderTask();
  expect(await screen.findByRole("alert")).toHaveTextContent("任务不存在");
});
