import { json, mockFetch } from "../test/fetch";
import { ApiError, api, fileUrl } from "./client";

function headersOf(init: RequestInit | undefined): Record<string, string> {
  return (init?.headers ?? {}) as Record<string, string>;
}

test("JSON requests carry the CSRF header and a JSON body", async () => {
  const calls = mockFetch({ "POST /api/auth/login": { id: 1 } });
  await expect(api("/api/auth/login", { json: { username: "a" } })).resolves.toEqual({ id: 1 });
  expect(calls[0].init?.method).toBe("POST");
  expect(headersOf(calls[0].init)["X-Requested-With"]).toBe("imgsr");
  expect(headersOf(calls[0].init)["Content-Type"]).toBe("application/json");
  expect(calls[0].init?.body).toBe(JSON.stringify({ username: "a" }));
  expect(calls[0].init?.credentials).toBe("same-origin");
});

test("multipart requests let the browser set the content type", async () => {
  const calls = mockFetch({ "POST /api/tasks": { id: "t1" } });
  const form = new FormData();
  form.append("file", new File(["x"], "a.png", { type: "image/png" }));
  await api("/api/tasks", { form });
  expect(headersOf(calls[0].init)["Content-Type"]).toBeUndefined();
  expect(calls[0].init?.body).toBe(form);
});

test("GET is the default method", async () => {
  const calls = mockFetch({ "/api/me": { id: 1 } });
  await api("/api/me");
  expect(calls[0].init?.method).toBe("GET");
});

test("string detail becomes the error message", async () => {
  mockFetch({ "/api/me": json(401, { detail: "请先登录" }) });
  await expect(api("/api/me")).rejects.toMatchObject({ status: 401, message: "请先登录" });
});

test("validation detail lists get a readable message", async () => {
  mockFetch({ "POST /api/x": json(422, { detail: [{ loc: ["body"], msg: "bad" }] }) });
  await expect(api("/api/x", { json: {} })).rejects.toMatchObject({ status: 422, message: "请求参数有误" });
});

test("HTML error pages do not crash JSON parsing", async () => {
  mockFetch({ "/api/me": new Response("<html>502 Bad Gateway</html>", { status: 502 }) });
  const error = await api("/api/me").catch((e: unknown) => e);
  expect(error).toBeInstanceOf(ApiError);
  expect(error).toMatchObject({ status: 502, message: "请求失败（502）" });
});

test("network failures become status 0", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
  await expect(api("/api/me")).rejects.toMatchObject({ status: 0, message: "网络连接失败，请稍后重试" });
});

test("204 resolves to undefined", async () => {
  mockFetch({ "DELETE /api/tasks/t1": new Response(null, { status: 204 }) });
  await expect(api("/api/tasks/t1", { method: "DELETE" })).resolves.toBeUndefined();
});

test("fileUrl", () => {
  expect(fileUrl("abc", "source")).toBe("/api/files/abc/source");
  expect(fileUrl("abc", "download-2", true)).toBe("/api/files/abc/download-2?download=1");
});
