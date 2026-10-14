import type { Round, SuggestionAction } from "../api/types";

const ACTION_LABEL: Record<SuggestionAction, string> = {
  accept: "采用本轮",
  retry_with_hint: "带完整原文重跑",
  tile_refine: "切块精修（预放大 2 倍）",
  manual_check: "人工核对",
};

export function ReviewPanel({
  round,
  onExecute,
  onAccept,
  onRetryReview,
  pending = false,
}: {
  round: Round;
  onExecute: (index: number) => void;
  onAccept: () => void;
  onRetryReview: () => void;
  pending?: boolean;
}) {
  const review = round.review;
  if (!review) return <p className="text-sm text-slate-500">正在审查结果文字…</p>;
  return (
    <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
      {review.error && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">
          <span>审查失败：{review.error}</span>
          <button type="button" className="btn-secondary" disabled={pending} onClick={onRetryReview}>
            重试审查
          </button>
        </div>
      )}
      <div>
        <h3 className="font-semibold">差异（{review.diffs.length}）</h3>
        {review.diffs.length === 0 ? (
          <p className="text-sm text-slate-500">
            {review.error ? "—" : "结果转写与确认原文一致。形近字（如“耍/要”）仍建议放大抽查。"}
          </p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {review.diffs.map((d, i) => (
              <li key={i} className="rounded bg-slate-50 px-2 py-1">
                <span className="text-slate-500">应为</span> <mark className="bg-emerald-100">{d.expected || "（无）"}</mark>{" "}
                <span className="text-slate-500">→ 实为</span> <mark className="bg-rose-100">{d.found || "（缺失）"}</mark>
                <div className="text-xs text-slate-500">{d.sentence}</div>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h3 className="font-semibold">建议</h3>
        <ul className="mt-1 space-y-2">
          {review.suggestions.map((s, i) => (
            <li key={i} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 p-2 text-sm">
              <div>
                <div className="font-medium">{ACTION_LABEL[s.action]}</div>
                <div className="text-slate-600">{s.reason}</div>
              </div>
              {s.action === "accept" && (
                <button type="button" className="btn-primary" disabled={pending} onClick={onAccept}>
                  设为最终版
                </button>
              )}
              {(s.action === "retry_with_hint" || s.action === "tile_refine") && (
                <button type="button" className="btn-primary" disabled={pending} onClick={() => onExecute(i)}>
                  执行
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
