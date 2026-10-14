import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeRound } from "../test/fixtures";
import { ReviewPanel } from "./ReviewPanel";
import { RoundForm } from "./RoundForm";
import { RoundStrip } from "./RoundStrip";

const reviewWithDiff = {
  model: "gpt-6-sol",
  transcript: "x",
  diffs: [{ expected: "亮", found: "光", sentence: "晚上还会发出亮光呢！" }],
  suggestions: [
    { action: "retry_with_hint" as const, reason: "带上完整原文重跑", diff_ids: [0], params: { use_text_hint: true } },
    { action: "manual_check" as const, reason: "请人工放大核对", diff_ids: [0], params: {} },
  ],
};

test("round strip shows status, final mark and diff counts", async () => {
  const onSelect = vi.fn();
  render(
    <RoundStrip
      taskId="t1"
      rounds={[makeRound(), makeRound({ id: 2, seq: 2, status: "failed", review: null })]}
      selected={1}
      finalRoundId={1}
      onSelect={onSelect}
    />,
  );
  expect(screen.getByRole("tab", { name: /R1 · 完成 · 定稿/ })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("差异 0")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: /R2 · 失败/ }));
  expect(onSelect).toHaveBeenCalledWith(2);
});

test("review panel lists diffs and executes suggestions by index", async () => {
  const onExecute = vi.fn();
  render(<ReviewPanel round={makeRound({ review: reviewWithDiff })} onExecute={onExecute} onAccept={vi.fn()} onRetryReview={vi.fn()} />);
  expect(screen.getByText("差异（1）")).toBeInTheDocument();
  expect(screen.getByText("晚上还会发出亮光呢！")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "执行" })).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "执行" }));
  expect(onExecute).toHaveBeenCalledWith(0);
  expect(screen.getByText("请人工放大核对")).toBeInTheDocument();
});

test("accept suggestion sets the final round", async () => {
  const onAccept = vi.fn();
  render(<ReviewPanel round={makeRound()} onExecute={vi.fn()} onAccept={onAccept} onRetryReview={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "采用本轮并定稿" }));
  expect(onAccept).toHaveBeenCalled();
});

test("review errors offer a retry", async () => {
  const onRetryReview = vi.fn();
  const round = makeRound({ review: { model: null, transcript: "", diffs: [], suggestions: [], error: "服务重启" } });
  render(<ReviewPanel round={round} onExecute={vi.fn()} onAccept={vi.fn()} onRetryReview={onRetryReview} />);
  expect(screen.getByText(/审查失败：服务重启/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "重试审查" }));
  expect(onRetryReview).toHaveBeenCalled();
});

test("a pending review panel disables its buttons", () => {
  render(<ReviewPanel round={makeRound({ review: reviewWithDiff })} onExecute={vi.fn()} onAccept={vi.fn()} onRetryReview={vi.fn()} pending />);
  expect(screen.getByRole("button", { name: "执行" })).toBeDisabled();
});

test("a missing review shows progress", () => {
  render(<ReviewPanel round={makeRound({ review: null })} onExecute={vi.fn()} onAccept={vi.fn()} onRetryReview={vi.fn()} />);
  expect(screen.getByText("正在审查结果文字…")).toBeInTheDocument();
});

test("round form submits defaults and advanced options", async () => {
  const onSubmit = vi.fn();
  render(<RoundForm hasText onSubmit={onSubmit} />);
  await userEvent.click(screen.getByRole("button", { name: "开始生成" }));
  expect(onSubmit).toHaveBeenLastCalledWith({ prompt: null, strategy: "auto", preupscale: 1, use_text_hint: true });
  await userEvent.type(screen.getByLabelText("提示词"), "保持原样");
  await userEvent.selectOptions(screen.getByLabelText("切块策略"), "tiles");
  await userEvent.click(screen.getByLabelText("预放大 2 倍"));
  await userEvent.click(screen.getByRole("button", { name: "开始生成" }));
  expect(onSubmit).toHaveBeenLastCalledWith({ prompt: "保持原样", strategy: "tiles", preupscale: 2, use_text_hint: true });
});

test("without confirmed text the hint option is off and locked", () => {
  render(<RoundForm hasText={false} onSubmit={vi.fn()} />);
  expect(screen.getByLabelText(/带原文提示/)).not.toBeChecked();
  expect(screen.getByLabelText(/带原文提示/)).toBeDisabled();
});

test("a pending round form cannot be submitted twice", () => {
  render(<RoundForm hasText onSubmit={vi.fn()} pending />);
  expect(screen.getByRole("button", { name: "开始生成" })).toBeDisabled();
});
