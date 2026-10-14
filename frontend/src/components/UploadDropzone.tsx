import { useEffect, useRef, useState } from "react";

const ACCEPT = "image/png,image/jpeg,image/webp";

export function UploadDropzone({
  onFile,
  disabled = false,
  hint,
}: {
  onFile: (file: File) => void;
  disabled?: boolean;
  hint?: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  useEffect(() => {
    if (disabled) return;
    const onPaste = (event: Event) => {
      const files = (event as ClipboardEvent).clipboardData?.files;
      const file = Array.from(files ?? []).find((f) => f.type.startsWith("image/"));
      if (file) onFile(file);
    };
    window.addEventListener("paste", onPaste);
    return () => window.removeEventListener("paste", onPaste);
  }, [disabled, onFile]);

  return (
    <div
      role="button"
      tabIndex={0}
      aria-disabled={disabled}
      onClick={() => !disabled && input.current?.click()}
      onKeyDown={(e) => {
        if (!disabled && (e.key === "Enter" || e.key === " ")) input.current?.click();
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const file = e.dataTransfer.files[0];
        if (file && !disabled) onFile(file);
      }}
      className={`flex h-48 flex-col items-center justify-center rounded-xl border-2 border-dashed px-4 text-center ${
        over ? "border-indigo-500 bg-indigo-50" : "border-slate-300 bg-white"
      } ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer hover:border-indigo-400"}`}
    >
      <p className="text-base font-medium text-slate-700">拖入、粘贴或点击选择截图</p>
      <p className="mt-1 text-sm text-slate-500">{hint ?? "支持 PNG / JPG / WebP，单张不超过 15 MB"}</p>
      <input
        ref={input}
        data-testid="file-input"
        type="file"
        accept={ACCEPT}
        className="hidden"
        disabled={disabled}
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onFile(file);
          e.target.value = "";
        }}
      />
    </div>
  );
}
