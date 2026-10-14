export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface RequestOptions {
  method?: string;
  json?: unknown;
  form?: FormData;
}

function errorMessage(status: number, data: unknown): string {
  const detail = (data as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "请求参数有误";
  return `请求失败（${status}）`;
}

/** The only way the app talks to the backend: CSRF header, same-origin cookies, Chinese errors. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "imgsr" };
  let body: BodyInit | undefined;
  if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  } else if (options.form) {
    body = options.form;
  }
  let response: Response;
  try {
    response = await fetch(path, {
      method: options.method ?? (body === undefined ? "GET" : "POST"),
      headers,
      body,
      credentials: "same-origin",
    });
  } catch {
    throw new ApiError(0, "网络连接失败，请稍后重试");
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    data = undefined;
  }
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, data));
  return data as T;
}

export function fileUrl(taskId: string, name: string, download = false): string {
  return `/api/files/${taskId}/${name}${download ? "?download=1" : ""}`;
}
