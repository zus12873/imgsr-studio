import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeTask } from "../test/fixtures";
import { TranscriptPanel } from "./TranscriptPanel";

test("editing and confirming passes the edited text", async () => {
  const onConfirm = vi.fn();
  render(
    <TranscriptPanel task={makeTask({ status: "awaiting_confirm", confirmed_text: null, transcript_raw: "第一段。" })} onConfirm={onConfirm} onRetry={vi.fn()} />,
  );
  const box = screen.getByLabelText("原文");
  expect(box).toHaveValue("第一段。");
  await userEvent.type(box, "第二段。");
  await userEvent.click(screen.getByRole("button", { name: "确认原文" }));
  expect(onConfirm).toHaveBeenCalledWith("第一段。第二段。");
  expect(screen.getByText(/编成通顺的错词/)).toBeInTheDocument();
  expect(screen.getByAltText("原图")).toHaveAttribute("src", "/api/files/t1/source");
});

test("a failed transcription offers retry and manual entry", async () => {
  const onRetry = vi.fn();
  render(
    <TranscriptPanel task={makeTask({ status: "transcribe_failed", transcript_raw: null, confirmed_text: null, error: "上游超时" })} onConfirm={vi.fn()} onRetry={onRetry} />,
  );
  expect(screen.getByText(/转写失败：上游超时/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "重试转写" }));
  expect(onRetry).toHaveBeenCalled();
  expect(screen.getByLabelText("原文")).toHaveValue("");
});

test("font size controls change the editor font", async () => {
  render(<TranscriptPanel task={makeTask({ status: "awaiting_confirm" })} onConfirm={vi.fn()} onRetry={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "放大字号" }));
  expect(screen.getByLabelText("原文")).toHaveStyle({ fontSize: "18px" });
});

test("pending disables confirmation", () => {
  render(<TranscriptPanel task={makeTask({ status: "awaiting_confirm" })} onConfirm={vi.fn()} onRetry={vi.fn()} pending />);
  expect(screen.getByRole("button", { name: "确认原文" })).toBeDisabled();
});
