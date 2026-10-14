import { formatSize, formatTime } from "./format";

test("naive backend timestamps are UTC and shown in Beijing time", () => {
  expect(formatTime("2026-10-14T06:30:00.123456")).toContain("14:30");
});

test("explicit offsets are respected", () => {
  expect(formatTime("2026-10-14T06:30:00Z")).toContain("14:30");
  expect(formatTime("2026-10-14T06:30:00+08:00")).toContain("06:30");
});

test("formatSize", () => {
  expect(formatSize(1106, 1428)).toBe("1106×1428");
  expect(formatSize(null, 5)).toBe("—");
});
