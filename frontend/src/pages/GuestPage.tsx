import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { fileUrl } from "../api/client";
import { useGuestQuota, useGuestTask, useGuestUpload } from "../api/hooks";
import type { GuestTask } from "../api/types";
import { CompareViewer } from "../components/CompareViewer";
import { ErrorNote } from "../components/ErrorNote";
import { UploadDropzone } from "../components/UploadDropzone";
import { Working } from "../components/Working";

export default function GuestPage() {
  const [params, setParams] = useSearchParams();
  const taskId = params.get("task");
  const quota = useGuestQuota();
  const upload = useGuestUpload();
  const task = useGuestTask(taskId);
  const [prompt, setPrompt] = useState("");
  const remaining = quota.data?.remaining;
  return (
    <div className="mx-auto max-w-5xl space-y-4 p-4">
      <header className="space-y-1">
        <h1 className="text-xl font-semibold">截图文字清晰化 · 临时使用</h1>
        <p className="text-sm text-slate-600">
          无需登录；每个网络每天 {quota.data?.limit ?? 3} 次，今日剩余 {remaining ?? "…"} 次；结果保留 24 小时。
          <Link to="/login" className="ml-2 text-indigo-600">
            登录
          </Link>
        </p>
      </header>
      {upload.error && <ErrorNote error={upload.error} />}
      {!taskId && (
        <>
          <UploadDropzone
            disabled={upload.isPending || remaining === 0}
            hint={remaining === 0 ? "今日次数已用完，登录后可继续使用" : undefined}
            onFile={(file) => upload.mutate({ file, prompt }, { onSuccess: (t) => setParams({ task: t.id }) })}
          />
          {upload.isPending && <Working text="上传中…" />}
          <details className="rounded-xl border border-slate-200 bg-white p-3">
            <summary className="cursor-pointer text-sm">自定义提示词（可选）</summary>
            <textarea
              aria-label="提示词"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              className="mt-2 h-24 w-full rounded-lg border border-slate-300 p-2 text-sm"
            />
          </details>
        </>
      )}
      {taskId && task.error && <ErrorNote error={task.error} />}
      {taskId && task.data && <GuestResult task={task.data} onReset={() => setParams({})} />}
    </div>
  );
}

function GuestResult({ task, onReset }: { task: GuestTask; onReset: () => void }) {
  if (task.status === "round_failed") {
    return (
      <div className="flex flex-wrap items-center gap-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">
        <span>处理失败：{task.round?.error ?? "未知错误"}（本次不计入次数）</span>
        <button type="button" className="btn-secondary" onClick={onReset}>
          重新上传
        </button>
      </div>
    );
  }
  if (task.status !== "done" || !task.round) return <Working text="正在生成（约 1–3 分钟）…" />;
  const seq = task.round.seq;
  return (
    <div className="space-y-3">
      <CompareViewer
        left={{ src: fileUrl(task.id, "source"), label: "原图" }}
        right={{ src: fileUrl(task.id, `result-${seq}`), label: "清晰版" }}
      />
      <div className="flex flex-wrap gap-3">
        <a className="btn-primary" href={fileUrl(task.id, `download-${seq}`, true)}>
          下载
        </a>
        <button type="button" className="btn-secondary" onClick={onReset}>
          再处理一张
        </button>
      </div>
      <p className="text-xs text-slate-500">生成式重绘可能写错个别字，请放大核对后再使用。</p>
    </div>
  );
}
