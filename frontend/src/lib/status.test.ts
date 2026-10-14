import { STATUS_LABEL, pollInterval } from "./status";

test("every status has a Chinese label", () => {
  expect(STATUS_LABEL.awaiting_confirm).toBe("待确认原文");
  expect(STATUS_LABEL.done).toBe("已定稿");
});

test.each([
  [undefined, false],
  [{ status: "generating" }, 2000],
  [{ status: "transcribing" }, 2000],
  [{ status: "reviewed", busy: false }, false],
  [{ status: "reviewed", busy: true }, 2000],
  [{ status: "done" }, false],
  [{ status: "round_failed" }, false],
])("pollInterval(%j) = %s", (task, expected) => {
  expect(pollInterval(task as never)).toBe(expected);
});
