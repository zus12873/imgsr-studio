import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mockFetch } from "../test/fetch";
import { makeRound, makeTask } from "../test/fixtures";
import { renderWithProviders } from "../test/utils";
import GuestPage from "./GuestPage";
import TaskPage from "./TaskPage";

const renderTask = () => renderWithProviders(<TaskPage />, { route: "/tasks/t1", path: "/tasks/:id" });

const withDiff = makeRound({
  id: 7,
  review: {
    model: "gpt-6-sol",
    transcript: "x",
    diffs: [{ expected: "耍", found: "要", sentence: "玩耍" }],
    suggestions: [{ action: "manual_check", reason: "自动修正手段已用尽，请人工核对剩余差异", diff_ids: [0], params: {} }],
  },
});

test("a round with diffs can still be set as final", async () => {
  mockFetch({ "/api/tasks/t1": makeTask({ rounds: [withDiff] }) });
  renderTask();
  await screen.findByAltText("第 1 轮");
  expect(screen.queryByRole("button", { name: /最终版|定稿/ })).toBeInTheDocument();
});

test("a round without confirmed text can be set as final", async () => {
  const r = makeRound({
    id: 7,
    use_text_hint: false,
    review: { model: null, transcript: "", diffs: [], suggestions: [{ action: "manual_check", reason: "没有确认原文", diff_ids: [], params: {} }] },
  });
  mockFetch({ "/api/tasks/t1": makeTask({ confirmed_text: "", rounds: [r] }) });
  renderTask();
  await screen.findByAltText("第 1 轮");
  expect(screen.queryByRole("button", { name: /最终版|定稿/ })).toBeInTheDocument();
});

test("executing a suggestion after selecting a round shows the new round", async () => {
  const r1 = makeRound({
    id: 7,
    review: {
      model: "gpt-6-sol",
      transcript: "x",
      diffs: [{ expected: "亮", found: "光", sentence: "亮光" }],
      suggestions: [{ action: "retry_with_hint", reason: "r", diff_ids: [0], params: {} }],
    },
  });
  mockFetch({
    "/api/tasks/t1": makeTask({ rounds: [r1] }),
    "POST /api/tasks/t1/rounds": makeTask({ status: "generating", busy: true, rounds: [r1, makeRound({ id: 8, seq: 2, status: "queued", review: null })] }),
  });
  renderTask();
  await userEvent.click(await screen.findByRole("tab", { name: /R1/ }));
  await userEvent.click(screen.getByRole("button", { name: "执行" }));
  expect(await screen.findByText("正在生成（单轮约 1–3 分钟）…")).toBeInTheDocument();
});

test("a failed extra round keeps what the user typed", async () => {
  mockFetch({
    "/api/tasks/t1": makeTask({ rounds: [makeRound({ id: 7 })] }),
    "POST /api/tasks/t1/rounds": async () => {
      await new Promise((r) => setTimeout(r, 50));
      return json(409, { detail: "你已有一个生成任务在进行中" });
    },
  });
  renderTask();
  await userEvent.click(await screen.findByText("再来一轮"));
  await userEvent.click(screen.getByText("高级选项"));
  await userEvent.type(screen.getByLabelText("提示词"), "我的长提示词");
  await userEvent.click(screen.getByRole("button", { name: "生成新一轮" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("你已有一个生成任务在进行中");
  expect(screen.getByLabelText("提示词")).toHaveValue("我的长提示词");
});

test("a failed mutation refreshes the task so polling can resume", async () => {
  let gets = 0;
  mockFetch({
    "/api/tasks/t1": () => {
      gets += 1;
      return makeTask({ rounds: [makeRound({ id: 7 })] });
    },
    "POST /api/tasks/t1/final": json(409, { detail: "任务正在处理中" }),
  });
  renderTask();
  await userEvent.click(await screen.findByRole("button", { name: "设为最终版" }));
  await screen.findByRole("alert");
  await waitFor(() => expect(gets).toBeGreaterThan(1), { timeout: 500 });
});

test("a refunded guest failure re-enables uploading", async () => {
  let remaining = 0;
  mockFetch({
    "/api/guest/quota": () => ({ limit: 3, remaining, global_remaining: 90 }),
    "/api/guest/tasks/g1": () => {
      remaining = 1; // server refunded the failed round
      return {
        id: "g1", status: "round_failed", source_w: 4, source_h: 3, created_at: "2026-10-14T06:00:00",
        expires_at: "2026-10-15T06:00:00", round: makeRound({ status: "failed", error: "上游繁忙", review: null }),
      };
    },
  });
  renderWithProviders(<GuestPage />, { route: "/guest?task=g1", path: "/guest" });
  await userEvent.click(await screen.findByRole("button", { name: "重新上传" }));
  await waitFor(() => expect(screen.getByRole("button", { name: /拖入、粘贴或点击/ })).toHaveAttribute("aria-disabled", "false"), { timeout: 500 });
});

test("an unknown guest task offers a way back to uploading", async () => {
  mockFetch({ "/api/guest/quota": { limit: 3, remaining: 3, global_remaining: 90 }, "/api/guest/tasks/zz": json(404, { detail: "任务不存在" }) });
  renderWithProviders(<GuestPage />, { route: "/guest?task=zz", path: "/guest" });
  expect(await screen.findByRole("alert")).toHaveTextContent("任务不存在");
  expect(screen.queryByTestId("file-input") ?? screen.queryByRole("button", { name: /重新上传|再处理/ })).not.toBeNull();
});

test("double-clicking start sends one request", async () => {
  let posts = 0;
  mockFetch({
    "/api/tasks/t1": makeTask({ status: "ready" }),
    "POST /api/tasks/t1/rounds": async () => {
      posts += 1;
      await new Promise((r) => setTimeout(r, 50));
      return makeTask({ status: "generating", busy: true, rounds: [makeRound({ status: "queued", review: null })] });
    },
  });
  renderTask();
  await userEvent.dblClick(await screen.findByRole("button", { name: "开始生成" }));
  await screen.findByText("正在生成（单轮约 1–3 分钟）…");
  expect(posts).toBe(1);
});

test("a review that compared nothing does not claim a match", async () => {
  const r = makeRound({
    id: 7, use_text_hint: false,
    review: { model: null, transcript: "", diffs: [], suggestions: [{ action: "manual_check", reason: "没有确认原文，无法自动比对，请人工放大核对", diff_ids: [], params: {} }] },
  });
  mockFetch({ "/api/tasks/t1": makeTask({ confirmed_text: "", rounds: [r] }) });
  renderWithProviders(<TaskPage />, { route: "/tasks/t1", path: "/tasks/:id" });
  await screen.findByAltText("第 1 轮");
  expect(screen.queryByText(/结果转写与确认原文一致/)).toBeNull();
  expect(screen.queryByText("差异 0")).toBeNull();
});

test("the compare viewer can compare two rounds", async () => {
  const r1 = makeRound({ id: 7, seq: 1 });
  const r2 = makeRound({ id: 8, seq: 2 });
  mockFetch({ "/api/tasks/t1": makeTask({ rounds: [r1, r2] }) });
  renderTask();
  expect(await screen.findByAltText("第 2 轮")).toHaveAttribute("src", "/api/files/t1/result-2");
  expect(screen.getByAltText("原图")).toHaveAttribute("src", "/api/files/t1/source");
  await userEvent.selectOptions(screen.getByLabelText("对比基准"), "1");
  expect(screen.getByAltText("第 1 轮")).toHaveAttribute("src", "/api/files/t1/result-1");
  expect(screen.queryByAltText("原图")).toBeNull();
});

test("diffs can be clicked to locate them and manual-check diffs are flagged", async () => {
  mockFetch({ "/api/tasks/t1": makeTask({ rounds: [withDiff] }) });
  renderTask();
  const diff = await screen.findByRole("button", { name: /应为 耍/ });
  expect(diff).toHaveTextContent("需人工核对");
  await userEvent.click(diff);
  expect(await screen.findByText(/请在对比查看器中放大查找/)).toHaveTextContent("玩耍");
});
