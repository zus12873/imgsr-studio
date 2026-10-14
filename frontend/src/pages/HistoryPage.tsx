import { useState } from "react";
import { Link } from "react-router";
import { fileUrl } from "../api/client";
import { useDeleteTask, useTasks } from "../api/hooks";
import { ErrorNote } from "../components/ErrorNote";
import { StatusBadge } from "../components/StatusBadge";
import { formatSize, formatTime } from "../lib/format";

export default function HistoryPage() {
  const tasks = useTasks(20);
  const remove = useDeleteTask();
  const [confirming, setConfirming] = useState<string | null>(null);
  const items = tasks.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">历史</h1>
      {tasks.error && <ErrorNote error={tasks.error} />}
      {remove.error && <ErrorNote error={remove.error} />}
      {items.length === 0 && !tasks.isPending ? (
        <p className="text-sm text-slate-500">暂无任务。</p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
          {items.map((t) => {
            const short = t.id.slice(0, 8);
            const armed = confirming === t.id;
            return (
              <li key={t.id} className="flex flex-wrap items-center gap-3 p-3">
                <img src={fileUrl(t.id, "thumb")} alt="" className="h-14 w-20 rounded object-cover" />
                <div className="min-w-0 flex-1">
                  <Link to={`/tasks/${t.id}`} className="font-medium text-indigo-700">
                    任务 {short}
                  </Link>
                  <div className="text-xs text-slate-500">
                    {formatSize(t.source_w, t.source_h)} · {t.rounds} 轮 · {formatTime(t.created_at)}
                    {t.final_round_id ? " · 已定稿" : ""}
                  </div>
                </div>
                <StatusBadge status={t.status} />
                <button
                  type="button"
                  className="btn-danger"
                  aria-label={`${armed ? "确认删除" : "删除"}任务 ${short}`}
                  disabled={remove.isPending}
                  onClick={() => {
                    if (!armed) {
                      setConfirming(t.id);
                      return;
                    }
                    remove.mutate(t.id, { onSuccess: () => setConfirming(null) });
                  }}
                >
                  {armed ? "确认删除" : "删除"}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {tasks.hasNextPage && (
        <button type="button" className="btn-secondary" disabled={tasks.isFetchingNextPage} onClick={() => void tasks.fetchNextPage()}>
          加载更多
        </button>
      )}
    </div>
  );
}
