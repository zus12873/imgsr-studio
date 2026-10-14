import { Link, useNavigate } from "react-router";
import { fileUrl } from "../api/client";
import { useTasks, useUpload } from "../api/hooks";
import { ErrorNote } from "../components/ErrorNote";
import { StatusBadge } from "../components/StatusBadge";
import { UploadDropzone } from "../components/UploadDropzone";
import { Working } from "../components/Working";
import { formatTime } from "../lib/format";

export default function WorkbenchPage() {
  const upload = useUpload();
  const navigate = useNavigate();
  const tasks = useTasks(6);
  const recent = tasks.data?.pages[0]?.items ?? [];
  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">工作台</h1>
      <UploadDropzone
        disabled={upload.isPending}
        onFile={(file) => upload.mutate(file, { onSuccess: (task) => navigate(`/tasks/${task.id}`) })}
      />
      {upload.isPending && <Working text="上传中…" />}
      {upload.error && <ErrorNote error={upload.error} />}
      <section>
        <h2 className="mb-2 font-semibold">最近任务</h2>
        {recent.length === 0 ? (
          <p className="text-sm text-slate-500">还没有任务，先上传一张截图。</p>
        ) : (
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {recent.map((t) => (
              <li key={t.id}>
                <Link
                  to={`/tasks/${t.id}`}
                  aria-label={`任务 ${t.id.slice(0, 8)}`}
                  className="block overflow-hidden rounded-lg border border-slate-200 bg-white hover:border-indigo-400"
                >
                  <img src={fileUrl(t.id, "thumb")} alt="" className="h-28 w-full object-cover" />
                  <div className="flex items-center justify-between gap-2 px-2 py-1 text-xs">
                    <StatusBadge status={t.status} />
                    <span className="text-slate-500">{formatTime(t.created_at)}</span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
