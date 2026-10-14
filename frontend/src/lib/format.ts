const ZONE = /(Z|[+-]\d\d:?\d\d)$/i;

/** Backend timestamps are naive UTC; show them in Beijing time. */
export function formatTime(iso: string): string {
  const date = new Date(ZONE.test(iso) ? iso : `${iso}Z`);
  return date.toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatSize(w: number | null | undefined, h: number | null | undefined): string {
  return w && h ? `${w}×${h}` : "—";
}
