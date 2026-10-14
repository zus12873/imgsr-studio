import type { TaskStatus } from "../api/types";
import { STATUS_LABEL } from "../lib/status";

const TONE: Record<TaskStatus, string> = {
  uploaded: "bg-slate-100 text-slate-700",
  transcribing: "bg-sky-100 text-sky-800",
  awaiting_confirm: "bg-amber-100 text-amber-800",
  transcribe_failed: "bg-rose-100 text-rose-800",
  ready: "bg-slate-100 text-slate-700",
  generating: "bg-sky-100 text-sky-800",
  reviewing: "bg-sky-100 text-sky-800",
  reviewed: "bg-violet-100 text-violet-800",
  round_failed: "bg-rose-100 text-rose-800",
  done: "bg-emerald-100 text-emerald-800",
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TONE[status]}`}>{STATUS_LABEL[status]}</span>;
}
