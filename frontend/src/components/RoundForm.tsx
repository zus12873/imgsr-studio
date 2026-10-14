import { useState } from "react";
import type { RoundRequest } from "../api/types";

type StrategyMode = "auto" | "whole" | "tiles";

export function RoundForm({
  hasText,
  onSubmit,
  pending = false,
  submitLabel = "开始生成",
}: {
  hasText: boolean;
  onSubmit: (request: RoundRequest) => void;
  pending?: boolean;
  submitLabel?: string;
}) {
  const [prompt, setPrompt] = useState("");
  const [strategy, setStrategy] = useState<StrategyMode>("auto");
  const [preupscale, setPreupscale] = useState(false);
  const [useHint, setUseHint] = useState(hasText);
  return (
    <form
      className="space-y-3 rounded-xl border border-slate-200 bg-white p-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          prompt: prompt.trim() || null,
          strategy,
          preupscale: preupscale ? 2 : 1,
          use_text_hint: hasText && useHint,
        });
      }}
    >
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={hasText && useHint} disabled={!hasText} onChange={(e) => setUseHint(e.target.checked)} />
        带原文提示{!hasText && "（未确认原文）"}
      </label>
      <details>
        <summary className="cursor-pointer text-sm text-slate-600">高级选项</summary>
        <div className="mt-2 space-y-2">
          <label className="block text-sm">
            提示词（留空使用默认）
            <textarea
              aria-label="提示词"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              className="mt-1 h-28 w-full rounded-lg border border-slate-300 p-2 text-sm"
            />
          </label>
          <label className="block text-sm">
            切块策略
            <select
              aria-label="切块策略"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as StrategyMode)}
              className="input mt-1 w-auto"
            >
              <option value="auto">自动</option>
              <option value="whole">整图</option>
              <option value="tiles">强制切块</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" aria-label="预放大 2 倍" checked={preupscale} onChange={(e) => setPreupscale(e.target.checked)} />
            预放大 2 倍（小字更准，块数约 ×4，可能超过单轮 16 块上限）
          </label>
        </div>
      </details>
      <button type="submit" className="btn-primary" disabled={pending}>
        {submitLabel}
      </button>
    </form>
  );
}
