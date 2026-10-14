import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { fileUrl } from "../api/client";
import {
  useConfirmText,
  useCreateRound,
  useDeleteTask,
  useRetryRound,
  useRetryTranscribe,
  useSetFinal,
  useTask,
} from "../api/hooks";
import type { Round, Task } from "../api/types";
import { CompareViewer } from "../components/CompareViewer";
import { ErrorNote } from "../components/ErrorNote";
import { ReviewPanel } from "../components/ReviewPanel";
import { RoundForm } from "../components/RoundForm";
import { RoundStrip } from "../components/RoundStrip";
import { StatusBadge } from "../components/StatusBadge";
import { TranscriptPanel } from "../components/TranscriptPanel";
import { Working } from "../components/Working";
import { formatSize, formatTime } from "../lib/format";

export default function TaskPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const task = useTask(id);
  const confirm = useConfirmText(id);
  const retryTranscribe = useRetryTranscribe(id);
  const createRound = useCreateRound(id);
  const retryRound = useRetryRound(id);
  const setFinal = useSetFinal(id);
  const remove = useDeleteTask();
  const [selected, setSelected] = useState<number | null>(null);
  const [editText, setEditText] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  if (task.isPending) return <p className="text-slate-500">加载中…</p>;
  if (task.error || !task.data) return <ErrorNote error={task.error} />;
  const t = task.data;
  const mutations = [confirm, retryTranscribe, createRound, retryRound, setFinal, remove];
  const mutationError = mutations.find((m) => m.error)?.error;
  const pending = t.busy || mutations.some((m) => m.isPending);
  const transcribing = t.status === "uploaded" || t.status === "transcribing";
  const showTranscript = t.status === "awaiting_confirm" || t.status === "transcribe_failed" || editText;
  const current = t.rounds.find((r) => r.seq === selected) ?? t.rounds[t.rounds.length - 1];

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold">任务 {t.id.slice(0, 8)}</h1>
        <StatusBadge status={t.status} />
        <span className="text-sm text-slate-500">
          {formatSize(t.source_w, t.source_h)} · 创建于 {formatTime(t.created_at)} · 保留至 {formatTime(t.expires_at)}
        </span>
        <div className="ml-auto flex gap-2">
          {!showTranscript && !transcribing && !t.busy && (
            <button type="button" className="btn-secondary" onClick={() => setEditText(true)}>
              修改原文
            </button>
          )}
          <button
            type="button"
            className="btn-danger"
            disabled={remove.isPending}
            onClick={() => {
              if (!confirmDelete) {
                setConfirmDelete(true);
                return;
              }
              remove.mutate(t.id, { onSuccess: () => navigate("/history") });
            }}
          >
            {confirmDelete ? "确认删除" : "删除"}
          </button>
        </div>
      </header>

      {mutationError && <ErrorNote error={mutationError} />}
      {transcribing && <Working text="正在识别原文（约 1 分钟）…" />}
      {showTranscript && (
        <TranscriptPanel
          key={`${t.status}-${t.transcript_raw ?? ""}`}
          task={t}
          pending={pending}
          onRetry={() => retryTranscribe.mutate()}
          onConfirm={(text) => confirm.mutate(text, { onSuccess: () => setEditText(false) })}
        />
      )}
      {t.rounds.length === 0 && t.status === "ready" && (
        <RoundForm hasText={Boolean(t.confirmed_text)} pending={pending} onSubmit={(req) => createRound.mutate(req)} />
      )}
      {current && (
        <>
          <RoundStrip
            taskId={t.id}
            rounds={t.rounds}
            selected={current.seq}
            finalRoundId={t.final_round_id}
            onSelect={setSelected}
          />
          <RoundDetail
            task={t}
            round={current}
            pending={pending}
            onRetry={() => retryRound.mutate(current.seq)}
            onExecute={(index) =>
              createRound.mutate({ suggestion: { round_id: current.id, index } }, { onSuccess: () => setSelected(null) })
            }
            onAccept={() => setFinal.mutate(current.id)}
          />
          {/* Stays mounted while a request is pending so a rejected request keeps what was typed. */}
          <details className="rounded-xl border border-slate-200 bg-white p-3">
            <summary className="cursor-pointer text-sm font-medium">再来一轮</summary>
            <div className="mt-3">
              <RoundForm
                hasText={Boolean(t.confirmed_text)}
                submitLabel="生成新一轮"
                pending={pending}
                onSubmit={(req) => createRound.mutate(req, { onSuccess: () => setSelected(null) })}
              />
            </div>
          </details>
        </>
      )}
    </div>
  );
}

function RoundDetail({
  task,
  round,
  pending,
  onRetry,
  onExecute,
  onAccept,
}: {
  task: Task;
  round: Round;
  pending: boolean;
  onRetry: () => void;
  onExecute: (index: number) => void;
  onAccept: () => void;
}) {
  const [baseSeq, setBaseSeq] = useState<number | null>(null);
  if (round.status === "queued" || round.status === "running") {
    return <Working text="正在生成（单轮约 1–3 分钟）…" />;
  }
  if (round.status === "failed") {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">
        <span>第 {round.seq} 轮失败：{round.error ?? "未知错误"}</span>
        <button type="button" className="btn-secondary" disabled={pending} onClick={onRetry}>
          重试
        </button>
      </div>
    );
  }
  const notes = round.strategy.plan?.notes ?? [];
  const others = task.rounds.filter((r) => r.status === "succeeded" && r.seq !== round.seq);
  const base = others.find((r) => r.seq === baseSeq);
  const left = base
    ? { src: fileUrl(task.id, `result-${base.seq}`), label: `第 ${base.seq} 轮` }
    : { src: fileUrl(task.id, "source"), label: "原图" };
  const isFinal = round.id === task.final_round_id;
  return (
    <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm text-slate-600">
          对比基准
          <select
            aria-label="对比基准"
            className="input w-auto"
            value={base ? String(base.seq) : ""}
            onChange={(e) => setBaseSeq(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">原图</option>
            {others.map((r) => (
              <option key={r.id} value={r.seq}>
                第 {r.seq} 轮
              </option>
            ))}
          </select>
        </label>
        <CompareViewer left={left} right={{ src: fileUrl(task.id, `result-${round.seq}`), label: `第 ${round.seq} 轮` }} />
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <button type="button" className="btn-primary" disabled={pending || isFinal} onClick={onAccept}>
            {isFinal ? "当前定稿" : "设为最终版"}
          </button>
          <a className="btn-secondary" href={fileUrl(task.id, `download-${round.seq}`, true)}>
            下载
          </a>
          <a className="btn-secondary" href={fileUrl(task.id, `result-${round.seq}`, true)}>
            原生分辨率
          </a>
          <span className="text-slate-500">
            {formatSize(round.download_w, round.download_h)} · 用时 {round.elapsed_s ?? "—"} 秒 · {round.image_model}
          </span>
        </div>
        {notes.length > 0 && (
          <ul className="list-disc pl-5 text-xs text-amber-700">
            {notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </div>
      <ReviewPanel round={round} pending={pending} onExecute={onExecute} onAccept={onAccept} onRetryReview={onRetry} />
    </div>
  );
}
