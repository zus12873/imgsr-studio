import { fileUrl } from "../api/client";
import type { Round, RoundStatus } from "../api/types";

const ROUND_LABEL: Record<RoundStatus, string> = {
  queued: "排队中",
  running: "生成中",
  succeeded: "完成",
  failed: "失败",
};

export function RoundStrip({
  taskId,
  rounds,
  selected,
  finalRoundId,
  onSelect,
}: {
  taskId: string;
  rounds: Round[];
  selected: number;
  finalRoundId: number | null;
  onSelect: (seq: number) => void;
}) {
  return (
    <div role="tablist" aria-label="生成轮次" className="flex gap-2 overflow-x-auto pb-1">
      {rounds.map((r) => {
        const active = r.seq === selected;
        return (
          <button
            key={r.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onSelect(r.seq)}
            className={`w-28 shrink-0 rounded-lg border p-1 text-left ${active ? "border-indigo-500 bg-indigo-50" : "border-slate-200 bg-white"}`}
          >
            <div className="h-16 overflow-hidden rounded bg-slate-100">
              {r.status === "succeeded" && (
                <img src={fileUrl(taskId, `result-${r.seq}`)} alt="" className="h-full w-full object-cover" />
              )}
            </div>
            <div className="mt-1 text-xs">
              R{r.seq} · {ROUND_LABEL[r.status]}
              {r.id === finalRoundId ? " · 定稿" : ""}
            </div>
            {r.status === "succeeded" && r.review && (
              <div className="text-xs text-slate-500">{r.review.error ? "审查失败" : `差异 ${r.review.diffs.length}`}</div>
            )}
          </button>
        );
      })}
    </div>
  );
}
