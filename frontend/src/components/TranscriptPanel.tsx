import { useState } from "react";
import { TransformComponent, TransformWrapper } from "react-zoom-pan-pinch";
import { fileUrl } from "../api/client";
import type { Task } from "../api/types";

export function TranscriptPanel({
  task,
  onConfirm,
  onRetry,
  pending = false,
}: {
  task: Task;
  onConfirm: (text: string) => void;
  onRetry: () => void;
  pending?: boolean;
}) {
  const [text, setText] = useState(task.confirmed_text ?? task.transcript_raw ?? "");
  const [fontSize, setFontSize] = useState(16);
  const failed = task.status === "transcribe_failed";
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4">
      <h2 className="text-lg font-semibold">确认原文</h2>
      <p className="mt-1 text-sm text-amber-700">
        模型可能把看不清的字编成通顺的错词，请对照左侧原图逐句核对。留空确认则生成时不带原文提示。
      </p>
      {failed && (
        <div className="mt-3 flex flex-wrap items-center gap-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">
          <span>转写失败：{task.error ?? "未知错误"}。可以重试，或直接在右侧手动输入原文。</span>
          <button type="button" className="btn-secondary" disabled={pending} onClick={onRetry}>
            重试转写
          </button>
        </div>
      )}
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
          <TransformWrapper maxScale={8}>
            <TransformComponent wrapperClass="!w-full" contentClass="!w-full">
              <img src={fileUrl(task.id, "source")} alt="原图" className="block w-full" />
            </TransformComponent>
          </TransformWrapper>
        </div>
        <div className="flex flex-col">
          <div className="mb-2 flex items-center gap-2 text-sm text-slate-600">
            <span>字号</span>
            <button type="button" aria-label="缩小字号" className="btn-secondary" onClick={() => setFontSize((s) => Math.max(12, s - 2))}>
              A-
            </button>
            <button type="button" aria-label="放大字号" className="btn-secondary" onClick={() => setFontSize((s) => Math.min(28, s + 2))}>
              A+
            </button>
          </div>
          <textarea
            aria-label="原文"
            value={text}
            onChange={(e) => setText(e.target.value)}
            style={{ fontSize: `${fontSize}px` }}
            className="min-h-80 flex-1 rounded-lg border border-slate-300 p-3 leading-relaxed"
          />
          <button type="button" className="btn-primary mt-3 self-end" disabled={pending} onClick={() => onConfirm(text)}>
            确认原文
          </button>
        </div>
      </div>
    </section>
  );
}
