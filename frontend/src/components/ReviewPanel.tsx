import { useState } from "react";
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
  const [copied, setCopied] = useState<string | null>(null);
  const review = round.review;
  if (!review) return <p className="text-sm text-slate-500">正在审查结果文字…</p>;
  // model === null without an error: nothing was compared (no confirmed text).
  const notCompared = review.model === null && !review.error;
  const flagged = new Set(review.suggestions.filter((s) => s.action === "manual_check").flatMap((s) => s.diff_ids));
  const locate = (sentence: string) => {
    void navigator.clipboard?.writeText(sentence).catch(() => undefined);
    setCopied(sentence);
  };
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
        <h3 className="font-semibold">{notCompared ? "未比对（没有确认原文）" : `差异（${review.diffs.length}）`}</h3>
        {review.diffs.length === 0 ? (
          <p className="text-sm text-slate-500">
            {review.error
              ? "—"
              : notCompared
                ? "没有确认原文，结果未经自动比对，请人工放大核对。"
                : "结果转写与确认原文一致。形近字（如“耍/要”）仍建议放大抽查。"}
          </p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {review.diffs.map((d, i) => (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => locate(d.sentence)}
                  className={`w-full rounded px-2 py-1 text-left ${flagged.has(i) ? "bg-amber-50 ring-1 ring-amber-400" : "bg-slate-50 hover:bg-slate-100"}`}
                >
                  <span className="text-slate-500">应为</span> <mark className="bg-emerald-100">{d.expected || "（无）"}</mark>{" "}
                  <span className="text-slate-500">→ 实为</span> <mark className="bg-rose-100">{d.found || "（缺失）"}</mark>
                  {flagged.has(i) && <span className="ml-2 text-xs font-medium text-amber-700">需人工核对</span>}
                  <div className="text-xs text-slate-500">{d.sentence}</div>
                </button>
              </li>
            ))}
          </ul>
        )}
        {copied && (
          <p role="status" className="mt-1 text-xs text-indigo-700">
            已复制「{copied}」，请在对比查看器中放大查找。
          </p>
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
                  采用本轮并定稿
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
