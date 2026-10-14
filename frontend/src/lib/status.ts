import type { TaskStatus } from "../api/types";

export const STATUS_LABEL: Record<TaskStatus, string> = {
  uploaded: "已上传",
  transcribing: "转写中",
  awaiting_confirm: "待确认原文",
  transcribe_failed: "转写失败",
  ready: "待生成",
  generating: "生成中",
  reviewing: "审查中",
  reviewed: "已审查",
  round_failed: "生成失败",
  done: "已定稿",
};

const WORKING: TaskStatus[] = ["uploaded", "transcribing", "generating", "reviewing"];

export function isWorking(task: { status: TaskStatus; busy?: boolean }): boolean {
  return task.busy === true || WORKING.includes(task.status);
}

/** Poll every 2 s while the backend is working on the task; stop otherwise. */
export function pollInterval(task: { status: TaskStatus; busy?: boolean } | undefined): number | false {
  return task && isWorking(task) ? 2000 : false;
}
