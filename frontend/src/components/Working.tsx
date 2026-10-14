export function Working({ text }: { text: string }) {
  return (
    <div role="status" className="flex items-center gap-3 rounded-lg bg-sky-50 px-3 py-3 text-sm text-sky-800">
      <span aria-hidden className="h-4 w-4 animate-spin rounded-full border-2 border-sky-300 border-t-sky-700" />
      {text}
    </div>
  );
}
