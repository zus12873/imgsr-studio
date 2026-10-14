type Handler = (init: RequestInit | undefined, url: string) => unknown;

export interface FetchCall {
  url: string;
  init?: RequestInit;
}

export function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Stub global fetch. Keys are "METHOD /path" (method defaults to GET); query strings are ignored. */
export function mockFetch(routes: Record<string, unknown>): FetchCall[] {
  const calls: FetchCall[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push({ url, init });
    const method = (init?.method ?? "GET").toUpperCase();
    const key = Object.keys(routes).find((k) => {
      const [m, p] = k.includes(" ") ? k.split(" ") : ["GET", k];
      return m === method && url.split("?")[0] === p;
    });
    if (key === undefined) return json(404, { detail: `not mocked: ${method} ${url}` });
    const value = routes[key];
    const out = typeof value === "function" ? await (value as Handler)(init, url) : value;
    return out instanceof Response ? out : json(200, out);
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}
