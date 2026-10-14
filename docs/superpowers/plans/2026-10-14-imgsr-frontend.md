# imgsr-studio 前端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现工具站的浏览器端：登录、工作台上传、任务页（原文确认 → 生成 → 审查差异与建议 → 多轮对比 → 定稿下载）、历史、游客临时页、管理页；由 FastAPI 直接托管打包后的 SPA。

**Architecture:** `frontend/` 下的 React + TypeScript + Vite 单页应用。所有请求经 `src/api/client.ts` 的 `api()`（统一带 `X-Requested-With: imgsr`、解析中文错误），数据层用 TanStack Query（任务处理中每 2 s 轮询），路由用 React Router。后端新增 `STATIC_DIR` 设置：存在 `index.html` 时托管 `/assets` 与 SPA 回退路由。

**Tech Stack:** React 19、TypeScript 5、Vite 7、React Router 7、TanStack Query 5、Tailwind CSS 4（`@tailwindcss/vite`）、react-zoom-pan-pinch 3；Vitest 3 + Testing Library + jsdom；Playwright（E2E，后端用假上游）。

**Spec:** `docs/superpowers/specs/2026-10-14-imgsr-studio-design.md`（§7 前端页面；§6.2 接口；§8 CSRF/会话）。后端接口以已合并的 `main` 为准（`src/imgsr/api/schemas.py` 等）。

**本计划范围：** spec §7 全部页面 + SPA 托管 + 浏览器 E2E。**不含**：Docker/部署/DNS/反代（计划 3）。

## Global Constraints

- Node ≥ 22（本机 25.8），包管理用 npm；依赖主版本固定为：`react@^19 react-dom@^19 react-router@^7 @tanstack/react-query@^5 react-zoom-pan-pinch@^3`，开发依赖 `typescript@^5 vite@^7 @vitejs/plugin-react@^5 tailwindcss@^4 @tailwindcss/vite@^4 vitest@^3 jsdom@^26 @testing-library/react@^16 @testing-library/dom@^10 @testing-library/user-event@^14 @testing-library/jest-dom@^6 @types/react@^19 @types/react-dom@^19 @types/node@^22 @playwright/test@^1`。若 npm 报 ERESOLVE，改用能共存的最新主版本并在执行记录写明。
- 界面文字全部中文；不在前端出现任何密钥。
- 所有后端请求只通过 `api()`；它负责 `X-Requested-With: imgsr`、`credentials: "same-origin"`、错误解析（`detail` 字符串 → 原样；422 列表 → `请求参数有误`；非 JSON → `请求失败（状态码）`；网络异常 → 状态 0 `网络连接失败，请稍后重试`）。
- 后端时间戳是无时区的 UTC，显示一律按 `Asia/Shanghai`。
- 只在任务处于 `uploaded/transcribing/generating/reviewing` 或 `busy=true` 时每 2 s 轮询，其余状态停止轮询。
- 删除等不可逆操作用页内“两次点击确认”，不使用浏览器 `confirm()/prompt()` 对话框。
- 手机宽度可用：图片一律 `w-full` 自适应，不出现横向滚动；双栏布局在窄屏折叠成单栏。
- 单元测试只用 mock 的 `fetch`，不访问网络；E2E 只连本地假上游服务（`scripts/e2e_server.py`），不产生费用。
- 前端命令在 `frontend/` 下执行；后端命令在仓库根执行（`uv run …`）。
- 每个 Task 完成后提交：只 `git add` 列出的具体文件（含 `frontend/package-lock.json` 等），提交信息末尾带 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
- 规划阶段裁决：spec §7 原文确认区“同步缩放”解释为——左侧原图可缩放/平移，右侧原文可调字号（文本无法与图片做像素级同步）；真正的同步缩放用于对比查看器的“并排”模式。

## Review Focus

1. **会话中途过期**（轮询或操作返回 401）→ 期望看到“登录已过期，请重新登录”与登录链接，而不是生硬的“请先登录”。（Task 5 `ErrorNote` 测试）
2. **反代返回 HTML 错误页 / 断网** → 期望显示可读的中文错误，不因 JSON 解析崩溃。（Task 3 client 测试）
3. **连点“开始生成”“执行”** → 期望请求进行中按钮禁用，不发出第二个请求。（Task 8 测试）
4. **游客在生成中刷新页面** → 期望凭 `?task=` 与 Cookie 继续显示进度/结果，而不是回到空白上传页。（Task 10 测试）
5. **手机宽度访问游客页** → 期望无横向滚动、可上传。（Task 12 E2E 视口检查）

---

## File Structure

```
src/imgsr/config.py               + static_dir
src/imgsr/api/app.py              + SPA 托管（/assets + 回退路由）
tests/api/test_spa.py
scripts/e2e_server.py             假上游 + 预置管理员，供 Playwright 使用
frontend/
├─ package.json / package-lock.json / tsconfig.json / vite.config.ts / index.html / playwright.config.ts
├─ e2e/smoke.spec.ts
└─ src/
   ├─ main.tsx / App.tsx / index.css
   ├─ api/      types.ts（后端返回结构）· client.ts（api/ApiError/fileUrl）· hooks.ts（Query/Mutation）
   ├─ lib/      format.ts（时间/尺寸）· status.ts（状态文案、是否轮询）
   ├─ test/     setup.ts · utils.tsx（renderWithProviders/renderApp）· fetch.ts（mockFetch/json）· fixtures.ts
   ├─ components/ StatusBadge · ErrorNote · Working · UploadDropzone · CompareViewer · TranscriptPanel
   │              · RoundStrip · ReviewPanel · RoundForm · AppShell · RequireAuth
   └─ pages/    LoginPage · WorkbenchPage · TaskPage · HistoryPage · GuestPage · AdminPage · NotFound
```

---

### Task 1: 后端托管 SPA

**Files:**
- Modify: `src/imgsr/config.py`（`Settings` 增加 `static_dir`）
- Modify: `src/imgsr/api/app.py`（`create_app` 末尾挂载静态资源与回退路由）
- Create: `tests/api/test_spa.py`

**Interfaces:**
- Produces: `Settings.static_dir: Path = Path("frontend/dist")`（环境变量 `STATIC_DIR`）；当 `static_dir/index.html` 存在时：`GET /assets/*` 返回打包资源；其余非 `/api/` 的 GET 若对应 `static_dir` 内真实文件则返回该文件，否则返回 `index.html`（`Cache-Control: no-cache`）；`/api/*` 未匹配仍为 404 JSON。

- [x] **Step 1: 写失败测试 `tests/api/test_spa.py`**

```python
import pytest


@pytest.fixture
def static_dir(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<div id=root>spa-shell</div>")
    (root / "assets" / "app.js").write_text("console.log('app')")
    (root / "favicon.svg").write_text("<svg/>")
    return root


def test_serves_index_and_client_routes(make_api, static_dir):
    api = make_api(static_dir=static_dir)
    for path in ("/", "/tasks/abc", "/guest"):
        r = api.client.get(path)
        assert r.status_code == 200 and "spa-shell" in r.text
        assert r.headers["cache-control"] == "no-cache"


def test_serves_assets_and_root_files(make_api, static_dir):
    api = make_api(static_dir=static_dir)
    assert "console.log" in api.client.get("/assets/app.js").text
    assert api.client.get("/favicon.svg").text == "<svg/>"


def test_unknown_api_paths_stay_json_404(make_api, static_dir):
    api = make_api(static_dir=static_dir)
    r = api.client.get("/api/nope")
    assert r.status_code == 404 and r.json()["detail"] == "Not Found"


def test_path_traversal_returns_index_not_file(make_api, static_dir):
    (static_dir.parent / "secret.txt").write_text("top-secret")
    api = make_api(static_dir=static_dir)
    assert "top-secret" not in api.client.get("/..%2Fsecret.txt").text


def test_no_static_dir_means_no_spa(make_api, tmp_path):
    api = make_api(static_dir=tmp_path / "missing")
    assert api.client.get("/").status_code == 404
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/api/test_spa.py -q`
Expected: FAIL（`static_dir` 不是 Settings 字段时被忽略 / `/` 返回 404）

- [x] **Step 3: 修改 `src/imgsr/config.py`**

在 `min_free_bytes: int = 1_000_000_000` 下一行加入：

```python
    static_dir: Path = Path("frontend/dist")
```

- [x] **Step 4: 修改 `src/imgsr/api/app.py`**

在文件顶部 import 区加入：

```python
from fastapi import HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
```

（与已有的 `from fastapi import FastAPI, Request`、`from fastapi.responses import JSONResponse` 合并成一行各一条。）把 `create_app` 末尾的：

```python
    for module in ROUTERS:
        app.include_router(module.router)
    return app
```

替换为：

```python
    for module in ROUTERS:
        app.include_router(module.router)
    _mount_spa(app, base.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir) -> None:  # noqa: ANN001
    """Serve the built frontend: /assets plus an index.html fallback for client routes."""
    index = static_dir / "index.html"
    if not index.is_file():
        return
    root = static_dir.resolve()
    app.mount("/assets", StaticFiles(directory=static_dir / "assets", check_dir=False), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
```

- [x] **Step 5: 运行，确认通过**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: 全部 passed（原 191 + 新 5）

- [x] **Step 6: Commit**

```bash
git add src/imgsr/config.py src/imgsr/api/app.py tests/api/test_spa.py
git commit -m "feat: serve the built SPA from FastAPI" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 前端脚手架与基础工具

**Files:**
- Create: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/vite.config.ts`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`（占位，Task 5 替换）, `frontend/src/index.css`, `frontend/src/vite-env.d.ts`, `frontend/src/test/setup.ts`, `frontend/src/lib/format.ts`, `frontend/src/lib/format.test.ts`

**Interfaces:**
- Produces: `formatTime(iso: string): string`（无时区按 UTC 解析，按北京时间显示 `YYYY/MM/DD HH:mm`）；`formatSize(w, h): string`（`1106×1428` 或 `—`）；CSS 组件类 `.btn-primary .btn-secondary .btn-danger .input`。

- [x] **Step 1: 写配置文件**

`frontend/package.json`:

```json
{
  "name": "imgsr-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "e2e": "playwright test"
  }
}
```

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "Bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "isolatedModules": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["vitest/globals", "node"]
  },
  "include": ["src", "e2e", "vite.config.ts", "playwright.config.ts"]
}
```

`frontend/vite.config.ts`:

```ts
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:18090" } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
```

`frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>imgsr · 截图文字清晰化</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [x] **Step 2: 安装依赖**

```bash
cd frontend
npm install react@^19 react-dom@^19 react-router@^7 @tanstack/react-query@^5 react-zoom-pan-pinch@^3
npm install -D typescript@^5 vite@^7 @vitejs/plugin-react@^5 tailwindcss@^4 @tailwindcss/vite@^4 vitest@^3 jsdom@^26 @testing-library/react@^16 @testing-library/dom@^10 @testing-library/user-event@^14 @testing-library/jest-dom@^6 @types/react@^19 @types/react-dom@^19 @types/node@^22 @playwright/test@^1
```

Expected: 生成 `package-lock.json` 与 `node_modules/`（已被 .gitignore 忽略），无 ERESOLVE。

- [x] **Step 3: 写入口与样式**

`frontend/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />
```

`frontend/src/index.css`:

```css
@import "tailwindcss";

@layer components {
  .btn-primary {
    @apply inline-flex items-center justify-center rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50;
  }
  .btn-secondary {
    @apply inline-flex items-center justify-center rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50;
  }
  .btn-danger {
    @apply inline-flex items-center justify-center rounded-lg border border-rose-300 bg-white px-3 py-1.5 text-sm text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50;
  }
  .input {
    @apply w-full rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:border-indigo-500 focus:outline-none;
  }
}

body {
  font-family: system-ui, -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
}
```

`frontend/src/App.tsx`（占位）:

```tsx
export default function App() {
  return <p>imgsr</p>;
}
```

`frontend/src/main.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
```

`frontend/src/test/setup.ts`:

```ts
import "@testing-library/jest-dom/vitest";

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!("ResizeObserver" in globalThis)) {
  (globalThis as { ResizeObserver?: unknown }).ResizeObserver = ResizeObserverStub;
}

afterEach(() => {
  vi.unstubAllGlobals();
});
```

- [x] **Step 4: 写失败测试 `frontend/src/lib/format.test.ts`**

```ts
import { formatSize, formatTime } from "./format";

test("naive backend timestamps are UTC and shown in Beijing time", () => {
  expect(formatTime("2026-10-14T06:30:00.123456")).toContain("14:30");
});

test("explicit offsets are respected", () => {
  expect(formatTime("2026-10-14T06:30:00Z")).toContain("14:30");
  expect(formatTime("2026-10-14T06:30:00+08:00")).toContain("06:30");
});

test("formatSize", () => {
  expect(formatSize(1106, 1428)).toBe("1106×1428");
  expect(formatSize(null, 5)).toBe("—");
});
```

- [x] **Step 5: 运行，确认失败**

Run: `cd frontend && npx vitest run src/lib/format.test.ts`
Expected: FAIL（`Failed to resolve import "./format"`）

- [x] **Step 6: 实现 `frontend/src/lib/format.ts`**

```ts
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
```

- [x] **Step 7: 运行，确认通过，并验证构建**

Run: `cd frontend && npx vitest run && npm run build`
Expected: `3 passed`；`vite build` 输出 `dist/index.html` 与 `dist/assets/*`

- [x] **Step 8: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/tsconfig.json frontend/vite.config.ts frontend/index.html frontend/src/main.tsx frontend/src/App.tsx frontend/src/index.css frontend/src/vite-env.d.ts frontend/src/test/setup.ts frontend/src/lib/format.ts frontend/src/lib/format.test.ts
git commit -m "feat: frontend scaffold with Vite, React, Tailwind and Vitest" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: API 客户端与类型

**Files:**
- Create: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/api/client.test.ts`, `frontend/src/test/fetch.ts`

**Interfaces:**
- Produces:
  - 类型：`TaskStatus`、`Diff`、`SuggestionAction`、`Suggestion`、`Review`、`TilePlanJson`、`Strategy`、`RoundStatus`、`Round`、`Task`、`TaskSummary`、`TaskPage`、`GuestTask`、`Quota`、`Me`、`AdminUser`、`SettingsView`、`RoundRequest`（字段与后端 `schemas.py`、`routes_admin.py` 一致）
  - `class ApiError extends Error { status: number }`；`api<T>(path, { method?, json?, form? }) => Promise<T>`；`fileUrl(taskId, name, download = false)`
  - 测试工具：`mockFetch(routes) => calls[]`（键为 `"METHOD /path"`，省略方法即 GET；值为对象/Response/函数）、`json(status, body) => Response`

- [x] **Step 1: 写测试工具 `frontend/src/test/fetch.ts`**

```ts
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
```

- [x] **Step 2: 写失败测试 `frontend/src/api/client.test.ts`**

```ts
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
```

- [x] **Step 3: 运行，确认失败**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL（`Failed to resolve import "./client"`）

- [x] **Step 4: 实现 `frontend/src/api/types.ts`**

```ts
export type TaskStatus =
  | "uploaded"
  | "transcribing"
  | "awaiting_confirm"
  | "transcribe_failed"
  | "ready"
  | "generating"
  | "reviewing"
  | "reviewed"
  | "round_failed"
  | "done";

export interface Diff {
  expected: string;
  found: string;
  sentence: string;
}

export type SuggestionAction = "accept" | "retry_with_hint" | "tile_refine" | "manual_check";

export interface Suggestion {
  action: SuggestionAction;
  reason: string;
  diff_ids: number[];
  params: Record<string, unknown>;
}

export interface Review {
  model: string | null;
  transcript: string;
  diffs: Diff[];
  suggestions: Suggestion[];
  error?: string;
}

export interface TilePlanJson {
  mode: "whole" | "tiles";
  tiles: { box: number[]; keep: number[] }[];
  notes: string[];
}

export interface Strategy {
  mode: "auto" | "whole" | "tiles";
  preupscale: 1 | 2;
  plan?: TilePlanJson;
  scale?: number;
}

export type RoundStatus = "queued" | "running" | "succeeded" | "failed";

export interface Round {
  id: number;
  seq: number;
  status: RoundStatus;
  image_model: string;
  prompt: string;
  strategy: Strategy;
  use_text_hint: boolean;
  result_w: number | null;
  result_h: number | null;
  download_w: number | null;
  download_h: number | null;
  elapsed_s: number | null;
  error: string | null;
  review: Review | null;
  created_at: string;
}

export interface Task {
  id: string;
  status: TaskStatus;
  source_w: number;
  source_h: number;
  transcript_raw: string | null;
  confirmed_text: string | null;
  final_round_id: number | null;
  error: string | null;
  created_at: string;
  expires_at: string;
  rounds: Round[];
  busy: boolean;
}

export interface TaskSummary {
  id: string;
  status: TaskStatus;
  source_w: number;
  source_h: number;
  created_at: string;
  final_round_id: number | null;
  rounds: number;
}

export interface TaskPage {
  items: TaskSummary[];
  next_cursor: string | null;
}

export interface GuestTask {
  id: string;
  status: TaskStatus;
  source_w: number;
  source_h: number;
  created_at: string;
  expires_at: string;
  round: Round | null;
}

export interface Quota {
  limit: number;
  remaining: number;
  global_remaining: number;
}

export interface Me {
  id: number;
  username: string;
  role: "admin" | "user";
  daily_quota: number;
  used_today: number;
}

export interface AdminUser {
  id: number;
  username: string;
  role: "admin" | "user";
  daily_quota: number;
  disabled: boolean;
  created_at: string;
  used_today: number;
}

export interface SettingsView {
  effective: Record<string, string | number>;
  overrides: Record<string, string | number>;
  restart_required: string[];
}

export interface RoundRequest {
  prompt?: string | null;
  strategy?: "auto" | "whole" | "tiles";
  preupscale?: 1 | 2;
  use_text_hint?: boolean;
  suggestion?: { round_id: number; index: number };
}
```

- [x] **Step 5: 实现 `frontend/src/api/client.ts`**

```ts
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
```

- [x] **Step 6: 运行，确认通过**

Run: `cd frontend && npx vitest run && npm run typecheck`
Expected: 全部 passed；tsc 无错误

- [x] **Step 7: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/api/client.test.ts frontend/src/test/fetch.ts
git commit -m "feat: frontend API client and response types" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 状态工具与数据钩子

**Files:**
- Create: `frontend/src/lib/status.ts`, `frontend/src/lib/status.test.ts`, `frontend/src/api/hooks.ts`, `frontend/src/api/hooks.test.tsx`, `frontend/src/test/fixtures.ts`

**Interfaces:**
- Consumes: `api`, 类型（Task 3）
- Produces:
  - `STATUS_LABEL: Record<TaskStatus, string>`、`isWorking(t)`、`pollInterval(t | undefined): number | false`
  - `qk`（查询键）、`useMe`、`useLogin`、`useLogout`、`useTask(id)`、`useTasks(limit)`、`useUpload`、`useDeleteTask`、`useConfirmText(id)`、`useRetryTranscribe(id)`、`useCreateRound(id)`、`useRetryRound(id)`、`useSetFinal(id)`、`useGuestQuota`、`useGuestTask(id | null)`、`useGuestUpload`、`useAdminUsers`、`useCreateUser`、`usePatchUser`、`useAdminSettings`、`usePatchSettings`
  - 所有任务类 mutation 成功后把返回的 Task 写入 `qk.task(id)` 缓存，并使 `qk.tasks`、`qk.me` 失效
  - `makeTask(over)`、`makeRound(over)` 测试夹具（默认 `id: "t1"`）

- [x] **Step 1: 写夹具 `frontend/src/test/fixtures.ts`**

```ts
import type { Round, Task } from "../api/types";

export function makeRound(over: Partial<Round> = {}): Round {
  return {
    id: 1,
    seq: 1,
    status: "succeeded",
    image_model: "gpt-image-2.5",
    prompt: "base prompt",
    strategy: { mode: "auto", preupscale: 1, plan: { mode: "whole", tiles: [], notes: [] }, scale: 1 },
    use_text_hint: true,
    result_w: 800,
    result_h: 600,
    download_w: 800,
    download_h: 600,
    elapsed_s: 30,
    error: null,
    review: {
      model: "gpt-6-sol",
      transcript: "原文。",
      diffs: [],
      suggestions: [{ action: "accept", reason: "结果转写与确认原文一致", diff_ids: [], params: {} }],
    },
    created_at: "2026-10-14T06:00:00",
    ...over,
  };
}

export function makeTask(over: Partial<Task> = {}): Task {
  return {
    id: "t1",
    status: "reviewed",
    source_w: 400,
    source_h: 300,
    transcript_raw: "原文。",
    confirmed_text: "原文。",
    final_round_id: null,
    error: null,
    created_at: "2026-10-14T06:00:00",
    expires_at: "2026-11-13T06:00:00",
    rounds: [],
    busy: false,
    ...over,
  };
}
```

- [x] **Step 2: 写失败测试**

`frontend/src/lib/status.test.ts`:

```ts
import { STATUS_LABEL, pollInterval } from "./status";

test("every status has a Chinese label", () => {
  expect(STATUS_LABEL.awaiting_confirm).toBe("待确认原文");
  expect(STATUS_LABEL.done).toBe("已定稿");
});

test.each([
  [undefined, false],
  [{ status: "generating" }, 2000],
  [{ status: "transcribing" }, 2000],
  [{ status: "reviewed", busy: false }, false],
  [{ status: "reviewed", busy: true }, 2000],
  [{ status: "done" }, false],
  [{ status: "round_failed" }, false],
])("pollInterval(%j) = %s", (task, expected) => {
  expect(pollInterval(task as never)).toBe(expected);
});
```

`frontend/src/api/hooks.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { mockFetch } from "../test/fetch";
import { makeTask } from "../test/fixtures";
import { qk, useConfirmText, useCreateRound } from "./hooks";

function setup() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

test("task mutations write the returned task into the cache", async () => {
  const task = makeTask({ status: "ready" });
  const calls = mockFetch({ "PUT /api/tasks/t1/text": task });
  const { client, wrapper } = setup();
  const { result } = renderHook(() => useConfirmText("t1"), { wrapper });
  result.current.mutate("原文。");
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(client.getQueryData(qk.task("t1"))).toEqual(task);
  expect(JSON.parse(calls[0].init?.body as string)).toEqual({ confirmed_text: "原文。" });
});

test("creating a round posts the request body", async () => {
  const calls = mockFetch({ "POST /api/tasks/t1/rounds": makeTask({ status: "generating" }) });
  const { wrapper } = setup();
  const { result } = renderHook(() => useCreateRound("t1"), { wrapper });
  result.current.mutate({ suggestion: { round_id: 3, index: 0 } });
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(JSON.parse(calls[0].init?.body as string)).toEqual({ suggestion: { round_id: 3, index: 0 } });
});
```

- [x] **Step 3: 运行，确认失败**

Run: `cd frontend && npx vitest run src/lib/status.test.ts src/api/hooks.test.tsx`
Expected: FAIL（无法解析 `./status`、`./hooks`）

- [x] **Step 4: 实现 `frontend/src/lib/status.ts`**

```ts
import type { TaskStatus } from "../api/types";

export const STATUS_LABEL: Record<TaskStatus, string> = {
  uploaded: "已上传",
  transcribing: "转写中",
  awaiting_confirm: "待确认原文",
  transcribe_failed: "转写失败",
  ready: "待生成",
  generating: "生成中",
  reviewing: "审查中",
  reviewed: "已审查",
  round_failed: "生成失败",
  done: "已定稿",
};

const WORKING: TaskStatus[] = ["uploaded", "transcribing", "generating", "reviewing"];

export function isWorking(task: { status: TaskStatus; busy?: boolean }): boolean {
  return task.busy === true || WORKING.includes(task.status);
}

/** Poll every 2 s while the backend is working on the task; stop otherwise. */
export function pollInterval(task: { status: TaskStatus; busy?: boolean } | undefined): number | false {
  return task && isWorking(task) ? 2000 : false;
}
```

- [x] **Step 5: 实现 `frontend/src/api/hooks.ts`**

```ts
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { pollInterval } from "../lib/status";
import { api } from "./client";
import type {
  AdminUser,
  GuestTask,
  Me,
  Quota,
  RoundRequest,
  SettingsView,
  Task,
  TaskPage,
} from "./types";

export const qk = {
  me: ["me"] as const,
  tasks: ["tasks"] as const,
  task: (id: string) => ["task", id] as const,
  guestTask: (id: string | null) => ["guest-task", id] as const,
  quota: ["guest-quota"] as const,
  users: ["admin-users"] as const,
  settings: ["admin-settings"] as const,
};

export function useMe() {
  return useQuery({ queryKey: qk.me, queryFn: () => api<Me>("/api/me") });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      api<Me>("/api/auth/login", { json: body }),
    onSuccess: (me) => qc.setQueryData(qk.me, me),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
    onSuccess: () => qc.clear(),
  });
}

export function useTask(id: string) {
  return useQuery({
    queryKey: qk.task(id),
    queryFn: () => api<Task>(`/api/tasks/${id}`),
    refetchInterval: (query) => pollInterval(query.state.data),
  });
}

export function useTasks(limit = 20) {
  return useInfiniteQuery({
    queryKey: [...qk.tasks, limit],
    queryFn: ({ pageParam }) =>
      api<TaskPage>(
        `/api/tasks?limit=${limit}${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`,
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}

function useTaskMutation<V>(id: string, fn: (variables: V) => Promise<Task>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (task) => {
      qc.setQueryData(qk.task(id), task);
      void qc.invalidateQueries({ queryKey: qk.tasks });
      void qc.invalidateQueries({ queryKey: qk.me });
    },
  });
}

export const useConfirmText = (id: string) =>
  useTaskMutation(id, (text: string) =>
    api<Task>(`/api/tasks/${id}/text`, { method: "PUT", json: { confirmed_text: text } }),
  );

export const useRetryTranscribe = (id: string) =>
  useTaskMutation<void>(id, () => api<Task>(`/api/tasks/${id}/transcribe`, { method: "POST" }));

export const useCreateRound = (id: string) =>
  useTaskMutation(id, (request: RoundRequest) => api<Task>(`/api/tasks/${id}/rounds`, { json: request }));

export const useRetryRound = (id: string) =>
  useTaskMutation(id, (seq: number) =>
    api<Task>(`/api/tasks/${id}/rounds/${seq}/retry`, { method: "POST" }),
  );

export const useSetFinal = (id: string) =>
  useTaskMutation(id, (roundId: number) =>
    api<Task>(`/api/tasks/${id}/final`, { json: { round_id: roundId } }),
  );

export function useUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<Task>("/api/tasks", { form });
    },
    onSuccess: (task) => {
      qc.setQueryData(qk.task(task.id), task);
      void qc.invalidateQueries({ queryKey: qk.tasks });
    },
  });
}

export function useDeleteTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => api<void>(`/api/tasks/${taskId}`, { method: "DELETE" }),
    onSuccess: (_data, taskId) => {
      qc.removeQueries({ queryKey: qk.task(taskId) });
      void qc.invalidateQueries({ queryKey: qk.tasks });
    },
  });
}

export function useGuestQuota() {
  return useQuery({ queryKey: qk.quota, queryFn: () => api<Quota>("/api/guest/quota") });
}

export function useGuestTask(id: string | null) {
  return useQuery({
    queryKey: qk.guestTask(id),
    queryFn: () => api<GuestTask>(`/api/guest/tasks/${id}`),
    enabled: id !== null,
    refetchInterval: (query) => pollInterval(query.state.data),
  });
}

export function useGuestUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, prompt }: { file: File; prompt: string }) => {
      const form = new FormData();
      form.append("file", file);
      if (prompt.trim()) form.append("prompt", prompt.trim());
      return api<GuestTask>("/api/guest/tasks", { form });
    },
    onSuccess: (task) => {
      qc.setQueryData(qk.guestTask(task.id), task);
      void qc.invalidateQueries({ queryKey: qk.quota });
    },
    onError: () => {
      void qc.invalidateQueries({ queryKey: qk.quota });
    },
  });
}

export function useAdminUsers() {
  return useQuery({ queryKey: qk.users, queryFn: () => api<AdminUser[]>("/api/admin/users") });
}

export interface NewUser {
  username: string;
  password: string;
  role: "admin" | "user";
  daily_quota: number | null;
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NewUser) => api<AdminUser>("/api/admin/users", { json: body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.users });
    },
  });
}

export interface UserPatch {
  id: number;
  password?: string;
  role?: "admin" | "user";
  disabled?: boolean;
  daily_quota?: number;
}

export function usePatchUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...patch }: UserPatch) =>
      api<AdminUser>(`/api/admin/users/${id}`, { method: "PATCH", json: patch }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.users });
    },
  });
}

export function useAdminSettings() {
  return useQuery({ queryKey: qk.settings, queryFn: () => api<SettingsView>("/api/admin/settings") });
}

export function usePatchSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (changes: Record<string, string | number>) =>
      api<SettingsView>("/api/admin/settings", { method: "PATCH", json: changes }),
    onSuccess: (view) => qc.setQueryData(qk.settings, view),
  });
}
```

- [x] **Step 6: 运行，确认通过**

Run: `cd frontend && npx vitest run && npm run typecheck`
Expected: 全部 passed；tsc 无错误

- [x] **Step 7: Commit**

```bash
git add frontend/src/lib/status.ts frontend/src/lib/status.test.ts frontend/src/api/hooks.ts frontend/src/api/hooks.test.tsx frontend/src/test/fixtures.ts
git commit -m "feat: status helpers and TanStack Query hooks" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 登录、路由与外壳

**Files:**
- Create: `frontend/src/components/ErrorNote.tsx`, `frontend/src/components/Working.tsx`, `frontend/src/components/RequireAuth.tsx`, `frontend/src/components/AppShell.tsx`, `frontend/src/pages/LoginPage.tsx`, `frontend/src/pages/NotFound.tsx`, 占位页 `frontend/src/pages/{WorkbenchPage,TaskPage,HistoryPage,GuestPage,AdminPage}.tsx`, `frontend/src/test/utils.tsx`, `frontend/src/App.test.tsx`, `frontend/src/components/ErrorNote.test.tsx`
- Modify: `frontend/src/App.tsx`（替换占位）

**Interfaces:**
- Consumes: hooks（Task 4）、`ApiError`
- Produces:
  - `ErrorNote({ error, sessionAware = true })`：401 且 `sessionAware` 时显示“登录已过期，请重新登录。”+“去登录”链接，否则显示 `error.message`；`role="alert"`
  - `Working({ text })`：`role="status"` 的加载提示
  - `RequireAuth({ children })`：`/api/me` 401 → 重定向 `/login`（`state.from` = 原路径）；`RequireAdmin({ children })`
  - `AppShell`：顶栏（工作台/历史/管理(仅管理员)/用户名·今日用量/退出）+ `<Outlet/>`
  - 路由：`/login`、`/guest`（公开）；`/`、`/tasks/:id`、`/history`、`/admin`（需登录；admin 需管理员）；`*` NotFound
  - 页面标题约定（测试依赖）：工作台 `<h1>工作台</h1>`、历史 `<h1>历史</h1>`、管理 `<h1>管理</h1>`
  - 测试工具：`renderWithProviders(ui, { route, path })`（未匹配路由渲染 `data-testid="location"` 显示当前路径）、`renderApp(route)`

- [x] **Step 1: 写测试工具 `frontend/src/test/utils.tsx`**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import App from "../App";

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname + location.search}</div>;
}

/** Render one page at `route`, matched by `path`; navigation elsewhere shows the location probe. */
export function renderWithProviders(ui: ReactElement, { route = "/", path = "/" } = {}) {
  const client = newClient();
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path={path} element={ui} />
          <Route path="*" element={<LocationProbe />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, ...view };
}

export function renderApp(route = "/") {
  const client = newClient();
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { client, ...view };
}
```

- [x] **Step 2: 写失败测试**

`frontend/src/components/ErrorNote.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import { ApiError } from "../api/client";
import { renderWithProviders } from "../test/utils";
import { ErrorNote } from "./ErrorNote";

test("a 401 mid-session asks the user to log in again", () => {
  renderWithProviders(<ErrorNote error={new ApiError(401, "请先登录")} />);
  expect(screen.getByRole("alert")).toHaveTextContent("登录已过期，请重新登录");
  expect(screen.getByRole("link", { name: "去登录" })).toHaveAttribute("href", "/login");
});

test("other errors show the server message", () => {
  renderWithProviders(<ErrorNote error={new ApiError(429, "今日生成次数已用完")} />);
  expect(screen.getByRole("alert")).toHaveTextContent("今日生成次数已用完");
});

test("the login form shows 401 messages verbatim", () => {
  renderWithProviders(<ErrorNote error={new ApiError(401, "用户名或密码错误")} sessionAware={false} />);
  expect(screen.getByRole("alert")).toHaveTextContent("用户名或密码错误");
});
```

`frontend/src/App.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mockFetch } from "./test/fetch";
import { renderApp } from "./test/utils";

const alice = { id: 1, username: "alice", role: "user", daily_quota: 50, used_today: 2 };

test("unauthenticated visits are sent to the login page", async () => {
  mockFetch({ "/api/me": json(401, { detail: "请先登录" }) });
  renderApp("/");
  expect(await screen.findByRole("heading", { name: "登录 imgsr" })).toBeInTheDocument();
});

test("logging in returns to the page the user came from", async () => {
  let loggedIn = false;
  const calls = mockFetch({
    "/api/me": () => (loggedIn ? alice : json(401, { detail: "请先登录" })),
    "POST /api/auth/login": () => {
      loggedIn = true;
      return alice;
    },
    "/api/tasks": { items: [], next_cursor: null },
  });
  renderApp("/history");
  await userEvent.type(await screen.findByLabelText("用户名"), "alice");
  await userEvent.type(screen.getByLabelText("密码"), "password123");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));
  expect(await screen.findByRole("heading", { name: "历史" })).toBeInTheDocument();
  expect(screen.getByText(/alice · 今日 2\/50/)).toBeInTheDocument();
  const login = calls.find((c) => c.url === "/api/auth/login");
  expect(JSON.parse(login?.init?.body as string)).toEqual({ username: "alice", password: "password123" });
});

test("a wrong password shows the server message", async () => {
  mockFetch({
    "/api/me": json(401, { detail: "请先登录" }),
    "POST /api/auth/login": json(401, { detail: "用户名或密码错误" }),
  });
  renderApp("/login");
  await userEvent.type(screen.getByLabelText("用户名"), "alice");
  await userEvent.type(screen.getByLabelText("密码"), "nope");
  await userEvent.click(screen.getByRole("button", { name: "登录" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("用户名或密码错误");
});

test("only admins see the admin link", async () => {
  mockFetch({ "/api/me": alice, "/api/tasks": { items: [], next_cursor: null } });
  renderApp("/");
  expect(await screen.findByRole("link", { name: "工作台" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "管理" })).not.toBeInTheDocument();
});

test("admins see the admin link", async () => {
  mockFetch({ "/api/me": { ...alice, role: "admin" }, "/api/tasks": { items: [], next_cursor: null } });
  renderApp("/");
  expect(await screen.findByRole("link", { name: "管理" })).toBeInTheDocument();
});

test("unknown routes show the not-found page", async () => {
  mockFetch({ "/api/me": alice });
  renderApp("/nope/nope");
  expect(await screen.findByText("页面不存在")).toBeInTheDocument();
});
```

- [x] **Step 3: 运行，确认失败**

Run: `cd frontend && npx vitest run src/App.test.tsx src/components/ErrorNote.test.tsx`
Expected: FAIL（无法解析 `./ErrorNote` 等 / 占位 App 不含登录页）

- [x] **Step 4: 实现通用组件**

`frontend/src/components/ErrorNote.tsx`:

```tsx
import { Link } from "react-router";
import { ApiError } from "../api/client";

export function ErrorNote({ error, sessionAware = true }: { error: unknown; sessionAware?: boolean }) {
  const expired = sessionAware && error instanceof ApiError && error.status === 401;
  const message = error instanceof Error ? error.message : "出错了，请稍后重试";
  return (
    <div role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">
      {expired ? "登录已过期，请重新登录。" : message}
      {expired && (
        <Link to="/login" className="ml-2 underline">
          去登录
        </Link>
      )}
    </div>
  );
}
```

`frontend/src/components/Working.tsx`:

```tsx
export function Working({ text }: { text: string }) {
  return (
    <div role="status" className="flex items-center gap-3 rounded-lg bg-sky-50 px-3 py-3 text-sm text-sky-800">
      <span aria-hidden className="h-4 w-4 animate-spin rounded-full border-2 border-sky-300 border-t-sky-700" />
      {text}
    </div>
  );
}
```

`frontend/src/components/RequireAuth.tsx`:

```tsx
import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";
import { ApiError } from "../api/client";
import { useMe } from "../api/hooks";
import { ErrorNote } from "./ErrorNote";

export function RequireAuth({ children }: { children: ReactNode }) {
  const me = useMe();
  const location = useLocation();
  if (me.isPending) return <p className="p-6 text-slate-500">加载中…</p>;
  if (me.error instanceof ApiError && me.error.status === 401) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (me.error) return <ErrorNote error={me.error} />;
  return <>{children}</>;
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const me = useMe();
  if (me.data?.role !== "admin") return <p className="text-slate-500">需要管理员权限。</p>;
  return <>{children}</>;
}
```

`frontend/src/components/AppShell.tsx`:

```tsx
import { NavLink, Outlet, useNavigate } from "react-router";
import { useLogout, useMe } from "../api/hooks";

function navClass({ isActive }: { isActive: boolean }) {
  return `rounded-md px-3 py-1.5 text-sm ${isActive ? "bg-indigo-50 text-indigo-700" : "text-slate-600 hover:bg-slate-100"}`;
}

export function AppShell() {
  const me = useMe();
  const logout = useLogout();
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-2 px-4 py-2">
          <span className="mr-4 font-semibold">imgsr</span>
          <NavLink to="/" end className={navClass}>
            工作台
          </NavLink>
          <NavLink to="/history" className={navClass}>
            历史
          </NavLink>
          {me.data?.role === "admin" && (
            <NavLink to="/admin" className={navClass}>
              管理
            </NavLink>
          )}
          <span className="ml-auto text-sm text-slate-500">
            {me.data?.username} · 今日 {me.data?.used_today}/{me.data?.daily_quota}
          </span>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => logout.mutate(undefined, { onSuccess: () => navigate("/login") })}
          >
            退出
          </button>
        </div>
      </header>
      <main className="mx-auto max-w-6xl p-4">
        <Outlet />
      </main>
    </div>
  );
}
```

- [x] **Step 5: 实现页面与路由**

`frontend/src/pages/LoginPage.tsx`:

```tsx
import { useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import { useLogin } from "../api/hooks";
import { ErrorNote } from "../components/ErrorNote";

export default function LoginPage() {
  const login = useLogin();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 p-4">
      <form
        className="w-full max-w-sm space-y-3 rounded-xl border border-slate-200 bg-white p-6"
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate({ username, password }, { onSuccess: () => navigate(from, { replace: true }) });
        }}
      >
        <h1 className="text-xl font-semibold">登录 imgsr</h1>
        <label className="block text-sm">
          用户名
          <input className="input mt-1" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" />
        </label>
        <label className="block text-sm">
          密码
          <input className="input mt-1" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
        </label>
        {login.error && <ErrorNote error={login.error} sessionAware={false} />}
        <button type="submit" className="btn-primary w-full" disabled={login.isPending}>
          登录
        </button>
        <p className="text-center text-sm text-slate-500">
          没有账号？
          <Link to="/guest" className="text-indigo-600">
            临时使用
          </Link>
        </p>
      </form>
    </div>
  );
}
```

`frontend/src/pages/NotFound.tsx`:

```tsx
import { Link } from "react-router";

export default function NotFound() {
  return (
    <div className="p-8 text-center">
      <p className="text-lg">页面不存在</p>
      <Link to="/" className="text-indigo-600">
        回到工作台
      </Link>
    </div>
  );
}
```

占位页（后续 Task 替换为完整实现）：

`frontend/src/pages/WorkbenchPage.tsx`:

```tsx
export default function WorkbenchPage() {
  return <h1 className="text-xl font-semibold">工作台</h1>;
}
```

`frontend/src/pages/TaskPage.tsx`:

```tsx
export default function TaskPage() {
  return <h1 className="text-xl font-semibold">任务</h1>;
}
```

`frontend/src/pages/HistoryPage.tsx`:

```tsx
export default function HistoryPage() {
  return <h1 className="text-xl font-semibold">历史</h1>;
}
```

`frontend/src/pages/GuestPage.tsx`:

```tsx
export default function GuestPage() {
  return <h1 className="text-xl font-semibold">临时使用</h1>;
}
```

`frontend/src/pages/AdminPage.tsx`:

```tsx
export default function AdminPage() {
  return <h1 className="text-xl font-semibold">管理</h1>;
}
```

`frontend/src/App.tsx`（替换占位）:

```tsx
import { Route, Routes } from "react-router";
import { AppShell } from "./components/AppShell";
import { RequireAdmin, RequireAuth } from "./components/RequireAuth";
import AdminPage from "./pages/AdminPage";
import GuestPage from "./pages/GuestPage";
import HistoryPage from "./pages/HistoryPage";
import LoginPage from "./pages/LoginPage";
import NotFound from "./pages/NotFound";
import TaskPage from "./pages/TaskPage";
import WorkbenchPage from "./pages/WorkbenchPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/guest" element={<GuestPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<WorkbenchPage />} />
        <Route path="tasks/:id" element={<TaskPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route
          path="admin"
          element={
            <RequireAdmin>
              <AdminPage />
            </RequireAdmin>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
```

- [x] **Step 6: 运行，确认通过**

Run: `cd frontend && npx vitest run && npm run typecheck`
Expected: 全部 passed

- [x] **Step 7: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx frontend/src/test/utils.tsx frontend/src/components/ErrorNote.tsx frontend/src/components/ErrorNote.test.tsx frontend/src/components/Working.tsx frontend/src/components/RequireAuth.tsx frontend/src/components/AppShell.tsx frontend/src/pages/LoginPage.tsx frontend/src/pages/NotFound.tsx frontend/src/pages/WorkbenchPage.tsx frontend/src/pages/TaskPage.tsx frontend/src/pages/HistoryPage.tsx frontend/src/pages/GuestPage.tsx frontend/src/pages/AdminPage.tsx
git commit -m "feat: login, auth guard, routes and app shell" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 上传组件与工作台

**Files:**
- Create: `frontend/src/components/StatusBadge.tsx`, `frontend/src/components/UploadDropzone.tsx`, `frontend/src/components/UploadDropzone.test.tsx`, `frontend/src/pages/WorkbenchPage.test.tsx`
- Modify: `frontend/src/pages/WorkbenchPage.tsx`（替换占位）

**Interfaces:**
- Produces: `StatusBadge({ status })`；`UploadDropzone({ onFile, disabled?, hint? })`（点击选择、拖放、全局粘贴；隐藏 input `data-testid="file-input"`；禁用时忽略所有来源）；工作台：上传成功跳转 `/tasks/:id`，显示最近 6 个任务。

- [x] **Step 1: 写失败测试**

`frontend/src/components/UploadDropzone.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { UploadDropzone } from "./UploadDropzone";

const png = () => new File(["x"], "a.png", { type: "image/png" });

function paste(file: File) {
  const event = new Event("paste");
  Object.defineProperty(event, "clipboardData", { value: { files: [file] } });
  window.dispatchEvent(event);
}

test("choosing a file calls onFile", async () => {
  const onFile = vi.fn();
  render(<UploadDropzone onFile={onFile} />);
  await userEvent.upload(screen.getByTestId("file-input"), png());
  expect(onFile).toHaveBeenCalledWith(expect.objectContaining({ name: "a.png" }));
});

test("pasting an image calls onFile", () => {
  const onFile = vi.fn();
  render(<UploadDropzone onFile={onFile} />);
  paste(png());
  expect(onFile).toHaveBeenCalledTimes(1);
});

test("dropping a file calls onFile", () => {
  const onFile = vi.fn();
  render(<UploadDropzone onFile={onFile} />);
  fireEvent.drop(screen.getByRole("button", { name: /拖入、粘贴或点击/ }), {
    dataTransfer: { files: [png()] },
  });
  expect(onFile).toHaveBeenCalledTimes(1);
});

test("a disabled dropzone ignores paste and drop", () => {
  const onFile = vi.fn();
  render(<UploadDropzone onFile={onFile} disabled />);
  paste(png());
  fireEvent.drop(screen.getByRole("button", { name: /拖入、粘贴或点击/ }), {
    dataTransfer: { files: [png()] },
  });
  expect(onFile).not.toHaveBeenCalled();
});
```

`frontend/src/pages/WorkbenchPage.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mockFetch } from "../test/fetch";
import { makeTask } from "../test/fixtures";
import { renderWithProviders } from "../test/utils";
import WorkbenchPage from "./WorkbenchPage";

const empty = { items: [], next_cursor: null };

test("uploading a screenshot opens its task page", async () => {
  const calls = mockFetch({
    "/api/tasks": empty,
    "POST /api/tasks": makeTask({ id: "new1", status: "uploaded" }),
  });
  renderWithProviders(<WorkbenchPage />);
  await userEvent.upload(screen.getByTestId("file-input"), new File(["x"], "a.png", { type: "image/png" }));
  expect(await screen.findByTestId("location")).toHaveTextContent("/tasks/new1");
  const post = calls.find((c) => c.init?.method === "POST");
  expect((post?.init?.body as FormData).get("file")).toBeInstanceOf(File);
});

test("upload errors are shown", async () => {
  mockFetch({ "/api/tasks": empty, "POST /api/tasks": json(400, { detail: "只支持 PNG、JPG、WebP 图片" }) });
  renderWithProviders(<WorkbenchPage />);
  await userEvent.upload(screen.getByTestId("file-input"), new File(["x"], "a.png", { type: "image/png" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("只支持 PNG、JPG、WebP 图片");
});

test("recent tasks link to their pages", async () => {
  mockFetch({
    "/api/tasks": {
      items: [{ id: "abcdef12", status: "done", source_w: 4, source_h: 3, created_at: "2026-10-14T06:00:00", final_round_id: 1, rounds: 1 }],
      next_cursor: null,
    },
  });
  renderWithProviders(<WorkbenchPage />);
  const link = await screen.findByRole("link", { name: /任务 abcdef12/ });
  expect(link).toHaveAttribute("href", "/tasks/abcdef12");
  expect(screen.getByText("已定稿")).toBeInTheDocument();
});
```

- [x] **Step 2: 运行，确认失败**

Run: `cd frontend && npx vitest run src/components/UploadDropzone.test.tsx src/pages/WorkbenchPage.test.tsx`
Expected: FAIL（无法解析 `./UploadDropzone`；工作台占位无上传区）

- [x] **Step 3: 实现组件**

`frontend/src/components/StatusBadge.tsx`:

```tsx
import type { TaskStatus } from "../api/types";
import { STATUS_LABEL } from "../lib/status";

const TONE: Record<TaskStatus, string> = {
  uploaded: "bg-slate-100 text-slate-700",
  transcribing: "bg-sky-100 text-sky-800",
  awaiting_confirm: "bg-amber-100 text-amber-800",
  transcribe_failed: "bg-rose-100 text-rose-800",
  ready: "bg-slate-100 text-slate-700",
  generating: "bg-sky-100 text-sky-800",
  reviewing: "bg-sky-100 text-sky-800",
  reviewed: "bg-violet-100 text-violet-800",
  round_failed: "bg-rose-100 text-rose-800",
  done: "bg-emerald-100 text-emerald-800",
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${TONE[status]}`}>{STATUS_LABEL[status]}</span>;
}
```

`frontend/src/components/UploadDropzone.tsx`:

```tsx
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
```

`frontend/src/pages/WorkbenchPage.tsx`（替换占位）:

```tsx
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
```

- [x] **Step 4: 运行，确认通过**

Run: `cd frontend && npx vitest run && npm run typecheck`
Expected: 全部 passed

- [x] **Step 5: Commit**

```bash
git add frontend/src/components/StatusBadge.tsx frontend/src/components/UploadDropzone.tsx frontend/src/components/UploadDropzone.test.tsx frontend/src/pages/WorkbenchPage.tsx frontend/src/pages/WorkbenchPage.test.tsx
git commit -m "feat: upload dropzone and workbench page" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 对比查看器与原文确认区

**Files:**
- Create: `frontend/src/components/CompareViewer.tsx`, `frontend/src/components/CompareViewer.test.tsx`, `frontend/src/components/TranscriptPanel.tsx`, `frontend/src/components/TranscriptPanel.test.tsx`

**Interfaces:**
- Produces:
  - `CompareViewer({ left, right })`，`left/right: { src, label }`：“滑块”模式（右图为底，左图按滑块比例裁切叠加，`aria-label="对比位置"` 的 range）与“并排（同步缩放）”模式（两个 `TransformWrapper` 互相同步平移缩放）
  - `TranscriptPanel({ task, onConfirm(text), onRetry(), pending? })`：左原图可缩放，右原文可编辑（`aria-label="原文"`，A-/A+ 调字号 12–28），醒目提示；`transcribe_failed` 时显示错误与“重试转写”；`pending` 时禁用按钮

- [x] **Step 1: 写失败测试**

`frontend/src/components/CompareViewer.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CompareViewer } from "./CompareViewer";

const props = { left: { src: "/a.png", label: "原图" }, right: { src: "/b.png", label: "第 1 轮" } };

test("slider mode overlays the left image clipped at the slider position", () => {
  render(<CompareViewer {...props} />);
  const overlay = screen.getByAltText("原图");
  expect(overlay.style.clipPath).toBe("inset(0 50% 0 0)");
  fireEvent.change(screen.getByLabelText("对比位置"), { target: { value: "30" } });
  expect(overlay.style.clipPath).toBe("inset(0 70% 0 0)");
  expect(screen.getByAltText("第 1 轮")).toBeInTheDocument();
});

test("side-by-side mode shows both images with captions", async () => {
  render(<CompareViewer {...props} />);
  await userEvent.click(screen.getByRole("button", { name: "并排（同步缩放）" }));
  expect(screen.getByRole("button", { name: "并排（同步缩放）" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("原图", { selector: "figcaption" })).toBeInTheDocument();
  expect(screen.getByText("第 1 轮", { selector: "figcaption" })).toBeInTheDocument();
});
```

`frontend/src/components/TranscriptPanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeTask } from "../test/fixtures";
import { TranscriptPanel } from "./TranscriptPanel";

test("editing and confirming passes the edited text", async () => {
  const onConfirm = vi.fn();
  render(
    <TranscriptPanel task={makeTask({ status: "awaiting_confirm", confirmed_text: null, transcript_raw: "第一段。" })} onConfirm={onConfirm} onRetry={vi.fn()} />,
  );
  const box = screen.getByLabelText("原文");
  expect(box).toHaveValue("第一段。");
  await userEvent.type(box, "第二段。");
  await userEvent.click(screen.getByRole("button", { name: "确认原文" }));
  expect(onConfirm).toHaveBeenCalledWith("第一段。第二段。");
  expect(screen.getByText(/编成通顺的错词/)).toBeInTheDocument();
  expect(screen.getByAltText("原图")).toHaveAttribute("src", "/api/files/t1/source");
});

test("a failed transcription offers retry and manual entry", async () => {
  const onRetry = vi.fn();
  render(
    <TranscriptPanel task={makeTask({ status: "transcribe_failed", transcript_raw: null, confirmed_text: null, error: "上游超时" })} onConfirm={vi.fn()} onRetry={onRetry} />,
  );
  expect(screen.getByText(/转写失败：上游超时/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "重试转写" }));
  expect(onRetry).toHaveBeenCalled();
  expect(screen.getByLabelText("原文")).toHaveValue("");
});

test("font size controls change the editor font", async () => {
  render(<TranscriptPanel task={makeTask({ status: "awaiting_confirm" })} onConfirm={vi.fn()} onRetry={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "放大字号" }));
  expect(screen.getByLabelText("原文")).toHaveStyle({ fontSize: "18px" });
});

test("pending disables confirmation", () => {
  render(<TranscriptPanel task={makeTask({ status: "awaiting_confirm" })} onConfirm={vi.fn()} onRetry={vi.fn()} pending />);
  expect(screen.getByRole("button", { name: "确认原文" })).toBeDisabled();
});
```

- [x] **Step 2: 运行，确认失败**

Run: `cd frontend && npx vitest run src/components/CompareViewer.test.tsx src/components/TranscriptPanel.test.tsx`
Expected: FAIL（无法解析组件）

- [x] **Step 3: 实现 `frontend/src/components/CompareViewer.tsx`**

```tsx
import { useRef, useState } from "react";
import { TransformComponent, TransformWrapper, type ReactZoomPanPinchRef } from "react-zoom-pan-pinch";

export interface CompareSide {
  src: string;
  label: string;
}

const tab = (on: boolean) => `rounded-md px-2 py-1 ${on ? "bg-indigo-600 text-white" : "bg-slate-100 text-slate-700"}`;

export function CompareViewer({ left, right }: { left: CompareSide; right: CompareSide }) {
  const [mode, setMode] = useState<"slider" | "side">("slider");
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-slate-500">对比：</span>
        <button type="button" aria-pressed={mode === "slider"} className={tab(mode === "slider")} onClick={() => setMode("slider")}>
          滑块
        </button>
        <button type="button" aria-pressed={mode === "side"} className={tab(mode === "side")} onClick={() => setMode("side")}>
          并排（同步缩放）
        </button>
      </div>
      {mode === "slider" ? <SliderCompare left={left} right={right} /> : <SideBySide left={left} right={right} />}
    </div>
  );
}

function SliderCompare({ left, right }: { left: CompareSide; right: CompareSide }) {
  const [pos, setPos] = useState(50);
  return (
    <div>
      <div className="relative overflow-hidden rounded-lg bg-slate-50">
        <img src={right.src} alt={right.label} className="block w-full" />
        <img
          src={left.src}
          alt={left.label}
          className="absolute inset-0 h-full w-full object-contain"
          style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }}
        />
        <div className="pointer-events-none absolute inset-y-0 w-0.5 bg-indigo-500" style={{ left: `${pos}%` }} />
        <span className="absolute left-2 top-2 rounded bg-black/60 px-1.5 text-xs text-white">{left.label}</span>
        <span className="absolute right-2 top-2 rounded bg-black/60 px-1.5 text-xs text-white">{right.label}</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={pos}
        aria-label="对比位置"
        className="mt-2 w-full"
        onChange={(e) => setPos(Number(e.target.value))}
      />
    </div>
  );
}

function SideBySide({ left, right }: { left: CompareSide; right: CompareSide }) {
  const leftRef = useRef<ReactZoomPanPinchRef>(null);
  const rightRef = useRef<ReactZoomPanPinchRef>(null);
  const syncing = useRef(false);
  const follow = (other: typeof leftRef) => (source: ReactZoomPanPinchRef) => {
    if (syncing.current || !other.current) return;
    const { positionX, positionY, scale } = source.state;
    syncing.current = true;
    other.current.setTransform(positionX, positionY, scale, 0);
    syncing.current = false;
  };
  const sides = [
    { side: left, ref: leftRef, onTransformed: follow(rightRef) },
    { side: right, ref: rightRef, onTransformed: follow(leftRef) },
  ];
  return (
    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {sides.map(({ side, ref, onTransformed }) => (
        <figure key={side.label} className="overflow-hidden rounded-lg border border-slate-200 bg-slate-50">
          <TransformWrapper ref={ref} onTransformed={onTransformed} maxScale={8}>
            <TransformComponent wrapperClass="!w-full" contentClass="!w-full">
              <img src={side.src} alt={side.label} className="block w-full" />
            </TransformComponent>
          </TransformWrapper>
          <figcaption className="px-2 py-1 text-xs text-slate-600">{side.label}</figcaption>
        </figure>
      ))}
    </div>
  );
}
```

- [x] **Step 4: 实现 `frontend/src/components/TranscriptPanel.tsx`**

```tsx
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
```

- [x] **Step 5: 运行，确认通过**

Run: `cd frontend && npx vitest run && npm run typecheck`
Expected: 全部 passed

- [x] **Step 6: Commit**

```bash
git add frontend/src/components/CompareViewer.tsx frontend/src/components/CompareViewer.test.tsx frontend/src/components/TranscriptPanel.tsx frontend/src/components/TranscriptPanel.test.tsx
git commit -m "feat: compare viewer and transcript confirmation panel" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 轮次条、审查面板与生成表单

**Files:**
- Create: `frontend/src/components/RoundStrip.tsx`, `frontend/src/components/ReviewPanel.tsx`, `frontend/src/components/RoundForm.tsx`, `frontend/src/components/rounds.test.tsx`

**Interfaces:**
- Produces:
  - `RoundStrip({ taskId, rounds, selected, finalRoundId, onSelect(seq) })`：`role="tablist"`；每轮 `role="tab"`，文字 `R{seq} · {排队中|生成中|完成|失败}`（定稿加 `· 定稿`），成功轮次显示 `差异 N` 或 `审查失败`
  - `ReviewPanel({ round, onExecute(index), onAccept(), onRetryReview(), pending? })`：`review` 为空 → “正在审查结果文字…”；`review.error` → 错误 + “重试审查”；差异列表“应为 X → 实为 Y”+句子；建议卡片：`accept` → “设为最终版”按钮，`retry_with_hint`/`tile_refine` → “执行”按钮，`manual_check` 只有说明；`pending` 时按钮禁用
  - `RoundForm({ hasText, onSubmit(RoundRequest), pending?, submitLabel? = "开始生成" })`：提交 `{ prompt: 文本或 null, strategy, preupscale: 1|2, use_text_hint }`；无原文时“带原文提示”不可勾选

- [x] **Step 1: 写失败测试 `frontend/src/components/rounds.test.tsx`**

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { makeRound } from "../test/fixtures";
import { ReviewPanel } from "./ReviewPanel";
import { RoundForm } from "./RoundForm";
import { RoundStrip } from "./RoundStrip";

const reviewWithDiff = {
  model: "gpt-6-sol",
  transcript: "x",
  diffs: [{ expected: "亮", found: "光", sentence: "晚上还会发出亮光呢！" }],
  suggestions: [
    { action: "retry_with_hint" as const, reason: "带上完整原文重跑", diff_ids: [0], params: { use_text_hint: true } },
    { action: "manual_check" as const, reason: "请人工放大核对", diff_ids: [0], params: {} },
  ],
};

test("round strip shows status, final mark and diff counts", async () => {
  const onSelect = vi.fn();
  render(
    <RoundStrip
      taskId="t1"
      rounds={[makeRound(), makeRound({ id: 2, seq: 2, status: "failed", review: null })]}
      selected={1}
      finalRoundId={1}
      onSelect={onSelect}
    />,
  );
  expect(screen.getByRole("tab", { name: /R1 · 完成 · 定稿/ })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("差异 0")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("tab", { name: /R2 · 失败/ }));
  expect(onSelect).toHaveBeenCalledWith(2);
});

test("review panel lists diffs and executes suggestions by index", async () => {
  const onExecute = vi.fn();
  render(<ReviewPanel round={makeRound({ review: reviewWithDiff })} onExecute={onExecute} onAccept={vi.fn()} onRetryReview={vi.fn()} />);
  expect(screen.getByText("差异（1）")).toBeInTheDocument();
  expect(screen.getByText("晚上还会发出亮光呢！")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "执行" })).toHaveLength(1);
  await userEvent.click(screen.getByRole("button", { name: "执行" }));
  expect(onExecute).toHaveBeenCalledWith(0);
  expect(screen.getByText("请人工放大核对")).toBeInTheDocument();
});

test("accept suggestion sets the final round", async () => {
  const onAccept = vi.fn();
  render(<ReviewPanel round={makeRound()} onExecute={vi.fn()} onAccept={onAccept} onRetryReview={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "设为最终版" }));
  expect(onAccept).toHaveBeenCalled();
});

test("review errors offer a retry", async () => {
  const onRetryReview = vi.fn();
  const round = makeRound({ review: { model: null, transcript: "", diffs: [], suggestions: [], error: "服务重启" } });
  render(<ReviewPanel round={round} onExecute={vi.fn()} onAccept={vi.fn()} onRetryReview={onRetryReview} />);
  expect(screen.getByText(/审查失败：服务重启/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "重试审查" }));
  expect(onRetryReview).toHaveBeenCalled();
});

test("a pending review panel disables its buttons", () => {
  render(<ReviewPanel round={makeRound({ review: reviewWithDiff })} onExecute={vi.fn()} onAccept={vi.fn()} onRetryReview={vi.fn()} pending />);
  expect(screen.getByRole("button", { name: "执行" })).toBeDisabled();
});

test("a missing review shows progress", () => {
  render(<ReviewPanel round={makeRound({ review: null })} onExecute={vi.fn()} onAccept={vi.fn()} onRetryReview={vi.fn()} />);
  expect(screen.getByText("正在审查结果文字…")).toBeInTheDocument();
});

test("round form submits defaults and advanced options", async () => {
  const onSubmit = vi.fn();
  render(<RoundForm hasText onSubmit={onSubmit} />);
  await userEvent.click(screen.getByRole("button", { name: "开始生成" }));
  expect(onSubmit).toHaveBeenLastCalledWith({ prompt: null, strategy: "auto", preupscale: 1, use_text_hint: true });
  await userEvent.type(screen.getByLabelText("提示词"), "保持原样");
  await userEvent.selectOptions(screen.getByLabelText("切块策略"), "tiles");
  await userEvent.click(screen.getByLabelText("预放大 2 倍"));
  await userEvent.click(screen.getByRole("button", { name: "开始生成" }));
  expect(onSubmit).toHaveBeenLastCalledWith({ prompt: "保持原样", strategy: "tiles", preupscale: 2, use_text_hint: true });
});

test("without confirmed text the hint option is off and locked", () => {
  render(<RoundForm hasText={false} onSubmit={vi.fn()} />);
  expect(screen.getByLabelText(/带原文提示/)).not.toBeChecked();
  expect(screen.getByLabelText(/带原文提示/)).toBeDisabled();
});

test("a pending round form cannot be submitted twice", () => {
  render(<RoundForm hasText onSubmit={vi.fn()} pending />);
  expect(screen.getByRole("button", { name: "开始生成" })).toBeDisabled();
});
```

- [x] **Step 2: 运行，确认失败**

Run: `cd frontend && npx vitest run src/components/rounds.test.tsx`
Expected: FAIL（无法解析组件）

- [x] **Step 3: 实现 `frontend/src/components/RoundStrip.tsx`**

```tsx
import { fileUrl } from "../api/client";
import type { Round, RoundStatus } from "../api/types";

const ROUND_LABEL: Record<RoundStatus, string> = {
  queued: "排队中",
  running: "生成中",
  succeeded: "完成",
  failed: "失败",
};

export function RoundStrip({
  taskId,
  rounds,
  selected,
  finalRoundId,
  onSelect,
}: {
  taskId: string;
  rounds: Round[];
  selected: number;
  finalRoundId: number | null;
  onSelect: (seq: number) => void;
}) {
  return (
    <div role="tablist" aria-label="生成轮次" className="flex gap-2 overflow-x-auto pb-1">
      {rounds.map((r) => {
        const active = r.seq === selected;
        return (
          <button
            key={r.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onSelect(r.seq)}
            className={`w-28 shrink-0 rounded-lg border p-1 text-left ${active ? "border-indigo-500 bg-indigo-50" : "border-slate-200 bg-white"}`}
          >
            <div className="h-16 overflow-hidden rounded bg-slate-100">
              {r.status === "succeeded" && (
                <img src={fileUrl(taskId, `result-${r.seq}`)} alt="" className="h-full w-full object-cover" />
              )}
            </div>
            <div className="mt-1 text-xs">
              R{r.seq} · {ROUND_LABEL[r.status]}
              {r.id === finalRoundId ? " · 定稿" : ""}
            </div>
            {r.status === "succeeded" && r.review && (
              <div className="text-xs text-slate-500">{r.review.error ? "审查失败" : `差异 ${r.review.diffs.length}`}</div>
            )}
          </button>
        );
      })}
    </div>
  );
}
```

- [x] **Step 4: 实现 `frontend/src/components/ReviewPanel.tsx`**

```tsx
import type { Round, SuggestionAction } from "../api/types";

const ACTION_LABEL: Record<SuggestionAction, string> = {
  accept: "采用本轮",
  retry_with_hint: "带完整原文重跑",
  tile_refine: "切块精修（预放大 2 倍）",
  manual_check: "人工核对",
};

export function ReviewPanel({
  round,
  onExecute,
  onAccept,
  onRetryReview,
  pending = false,
}: {
  round: Round;
  onExecute: (index: number) => void;
  onAccept: () => void;
  onRetryReview: () => void;
  pending?: boolean;
}) {
  const review = round.review;
  if (!review) return <p className="text-sm text-slate-500">正在审查结果文字…</p>;
  return (
    <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
      {review.error && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg bg-rose-50 p-3 text-sm text-rose-800">
          <span>审查失败：{review.error}</span>
          <button type="button" className="btn-secondary" disabled={pending} onClick={onRetryReview}>
            重试审查
          </button>
        </div>
      )}
      <div>
        <h3 className="font-semibold">差异（{review.diffs.length}）</h3>
        {review.diffs.length === 0 ? (
          <p className="text-sm text-slate-500">
            {review.error ? "—" : "结果转写与确认原文一致。形近字（如“耍/要”）仍建议放大抽查。"}
          </p>
        ) : (
          <ul className="mt-1 space-y-1 text-sm">
            {review.diffs.map((d, i) => (
              <li key={i} className="rounded bg-slate-50 px-2 py-1">
                <span className="text-slate-500">应为</span> <mark className="bg-emerald-100">{d.expected || "（无）"}</mark>{" "}
                <span className="text-slate-500">→ 实为</span> <mark className="bg-rose-100">{d.found || "（缺失）"}</mark>
                <div className="text-xs text-slate-500">{d.sentence}</div>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <h3 className="font-semibold">建议</h3>
        <ul className="mt-1 space-y-2">
          {review.suggestions.map((s, i) => (
            <li key={i} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 p-2 text-sm">
              <div>
                <div className="font-medium">{ACTION_LABEL[s.action]}</div>
                <div className="text-slate-600">{s.reason}</div>
              </div>
              {s.action === "accept" && (
                <button type="button" className="btn-primary" disabled={pending} onClick={onAccept}>
                  设为最终版
                </button>
              )}
              {(s.action === "retry_with_hint" || s.action === "tile_refine") && (
                <button type="button" className="btn-primary" disabled={pending} onClick={() => onExecute(i)}>
                  执行
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
```

- [x] **Step 5: 实现 `frontend/src/components/RoundForm.tsx`**

```tsx
import { useState } from "react";
import type { RoundRequest } from "../api/types";

type StrategyMode = "auto" | "whole" | "tiles";

export function RoundForm({
  hasText,
  onSubmit,
  pending = false,
  submitLabel = "开始生成",
}: {
  hasText: boolean;
  onSubmit: (request: RoundRequest) => void;
  pending?: boolean;
  submitLabel?: string;
}) {
  const [prompt, setPrompt] = useState("");
  const [strategy, setStrategy] = useState<StrategyMode>("auto");
  const [preupscale, setPreupscale] = useState(false);
  const [useHint, setUseHint] = useState(hasText);
  return (
    <form
      className="space-y-3 rounded-xl border border-slate-200 bg-white p-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          prompt: prompt.trim() || null,
          strategy,
          preupscale: preupscale ? 2 : 1,
          use_text_hint: hasText && useHint,
        });
      }}
    >
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={hasText && useHint} disabled={!hasText} onChange={(e) => setUseHint(e.target.checked)} />
        带原文提示{!hasText && "（未确认原文）"}
      </label>
      <details>
        <summary className="cursor-pointer text-sm text-slate-600">高级选项</summary>
        <div className="mt-2 space-y-2">
          <label className="block text-sm">
            提示词（留空使用默认）
            <textarea
              aria-label="提示词"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              className="mt-1 h-28 w-full rounded-lg border border-slate-300 p-2 text-sm"
            />
          </label>
          <label className="block text-sm">
            切块策略
            <select
              aria-label="切块策略"
              value={strategy}
              onChange={(e) => setStrategy(e.target.value as StrategyMode)}
              className="input mt-1 w-auto"
            >
              <option value="auto">自动</option>
              <option value="whole">整图</option>
              <option value="tiles">强制切块</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" aria-label="预放大 2 倍" checked={preupscale} onChange={(e) => setPreupscale(e.target.checked)} />
            预放大 2 倍（小字更准，块数约 ×4，可能超过单轮 16 块上限）
          </label>
        </div>
      </details>
      <button type="submit" className="btn-primary" disabled={pending}>
        {submitLabel}
      </button>
    </form>
  );
}
```

- [x] **Step 6: 运行，确认通过**

Run: `cd frontend && npx vitest run && npm run typecheck`
Expected: 全部 passed

- [x] **Step 7: Commit**

```bash
git add frontend/src/components/RoundStrip.tsx frontend/src/components/ReviewPanel.tsx frontend/src/components/RoundForm.tsx frontend/src/components/rounds.test.tsx
git commit -m "feat: round strip, review panel and round form" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 任务页

**Files:**
- Modify: `frontend/src/pages/TaskPage.tsx`（替换占位）
- Create: `frontend/src/pages/TaskPage.test.tsx`

**Interfaces:**
- Consumes: Task 4 钩子、Task 6–8 组件
- Produces（页面行为，测试依赖的文案）：
  - 头部：`任务 {id 前 8 位}` + 状态徽标 + 尺寸/时间；“修改原文”（非处理中且已有原文阶段时）；删除为两步确认（“删除” → “确认删除”），成功后跳转 `/history`
  - `uploaded/transcribing` → `Working` “正在识别原文（约 1 分钟）…”
  - `awaiting_confirm/transcribe_failed` 或点了“修改原文” → `TranscriptPanel`
  - 无轮次且 `ready` → `RoundForm`（“开始生成”）
  - 有轮次：`RoundStrip`（默认选最新）+ 所选轮次详情：`queued/running` → `Working` “正在生成（单轮约 1–3 分钟）…”；`failed` → 错误 + “重试”；`succeeded` → `CompareViewer`（原图 vs 第 N 轮）、切块说明（`strategy.plan.notes`）、链接“下载”（`download-N?download=1`）与“原生分辨率”（`result-N?download=1`）、`ReviewPanel`；任务未处理中时显示折叠的“再来一轮”表单（`submitLabel="生成新一轮"`）
  - 任何 mutation 错误用 `ErrorNote` 显示

- [x] **Step 1: 写失败测试 `frontend/src/pages/TaskPage.test.tsx`**

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mockFetch } from "../test/fetch";
import { makeRound, makeTask } from "../test/fixtures";
import { renderWithProviders } from "../test/utils";
import TaskPage from "./TaskPage";

function renderTask() {
  return renderWithProviders(<TaskPage />, { route: "/tasks/t1", path: "/tasks/:id" });
}

const bodyOf = (calls: { url: string; init?: RequestInit }[], url: string) =>
  JSON.parse(calls.find((c) => c.url === url)?.init?.body as string);

test("transcribing shows progress", async () => {
  mockFetch({ "/api/tasks/t1": makeTask({ status: "transcribing", transcript_raw: null, confirmed_text: null, busy: true }) });
  renderTask();
  expect(await screen.findByText("正在识别原文（约 1 分钟）…")).toBeInTheDocument();
});

test("confirming the transcript sends it", async () => {
  const calls = mockFetch({
    "/api/tasks/t1": makeTask({ status: "awaiting_confirm", confirmed_text: null, transcript_raw: "第一段。" }),
    "PUT /api/tasks/t1/text": makeTask({ status: "ready", confirmed_text: "第一段。" }),
  });
  renderTask();
  await userEvent.click(await screen.findByRole("button", { name: "确认原文" }));
  expect(bodyOf(calls, "/api/tasks/t1/text")).toEqual({ confirmed_text: "第一段。" });
  expect(await screen.findByRole("button", { name: "开始生成" })).toBeInTheDocument();
});

test("starting the first round posts the form", async () => {
  const calls = mockFetch({
    "/api/tasks/t1": makeTask({ status: "ready" }),
    "POST /api/tasks/t1/rounds": makeTask({ status: "generating", busy: true, rounds: [makeRound({ status: "queued", review: null })] }),
  });
  renderTask();
  await userEvent.click(await screen.findByRole("button", { name: "开始生成" }));
  expect(bodyOf(calls, "/api/tasks/t1/rounds")).toEqual({ prompt: null, strategy: "auto", preupscale: 1, use_text_hint: true });
  expect(await screen.findByText("正在生成（单轮约 1–3 分钟）…")).toBeInTheDocument();
});

test("a reviewed round shows comparison, downloads and executable suggestions", async () => {
  const round = makeRound({
    id: 7,
    review: {
      model: "gpt-6-sol",
      transcript: "x",
      diffs: [{ expected: "亮", found: "光", sentence: "发出亮光呢！" }],
      suggestions: [{ action: "retry_with_hint", reason: "带上完整原文重跑", diff_ids: [0], params: {} }],
    },
    strategy: { mode: "auto", preupscale: 1, plan: { mode: "tiles", tiles: [], notes: ["区域 (0, 0) 超过像素上限，该块会被模型缩小"] }, scale: 1 },
  });
  const calls = mockFetch({
    "/api/tasks/t1": makeTask({ rounds: [round] }),
    "POST /api/tasks/t1/rounds": makeTask({ status: "generating", busy: true, rounds: [round, makeRound({ id: 8, seq: 2, status: "queued", review: null })] }),
  });
  renderTask();
  expect(await screen.findByAltText("第 1 轮")).toHaveAttribute("src", "/api/files/t1/result-1");
  expect(screen.getByRole("link", { name: "下载" })).toHaveAttribute("href", "/api/files/t1/download-1?download=1");
  expect(screen.getByRole("link", { name: "原生分辨率" })).toHaveAttribute("href", "/api/files/t1/result-1?download=1");
  expect(screen.getByText(/该块会被模型缩小/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "执行" }));
  expect(bodyOf(calls, "/api/tasks/t1/rounds")).toEqual({ suggestion: { round_id: 7, index: 0 } });
});

test("accepting sets the final round", async () => {
  const calls = mockFetch({
    "/api/tasks/t1": makeTask({ rounds: [makeRound({ id: 7 })] }),
    "POST /api/tasks/t1/final": makeTask({ status: "done", final_round_id: 7, rounds: [makeRound({ id: 7 })] }),
  });
  renderTask();
  await userEvent.click(await screen.findByRole("button", { name: "设为最终版" }));
  expect(bodyOf(calls, "/api/tasks/t1/final")).toEqual({ round_id: 7 });
  expect(await screen.findByText("已定稿")).toBeInTheDocument();
});

test("a failed round can be retried", async () => {
  const calls = mockFetch({
    "/api/tasks/t1": makeTask({ status: "round_failed", rounds: [makeRound({ status: "failed", error: "上游繁忙：x", review: null })] }),
    "POST /api/tasks/t1/rounds/1/retry": makeTask({ status: "generating", busy: true, rounds: [makeRound({ status: "queued", review: null })] }),
  });
  renderTask();
  expect(await screen.findByText(/上游繁忙：x/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(calls.some((c) => c.url === "/api/tasks/t1/rounds/1/retry")).toBe(true);
});

test("quota errors are shown", async () => {
  mockFetch({
    "/api/tasks/t1": makeTask({ status: "ready" }),
    "POST /api/tasks/t1/rounds": json(429, { detail: "今日生成次数已用完，明天再来或联系管理员调整额度" }),
  });
  renderTask();
  await userEvent.click(await screen.findByRole("button", { name: "开始生成" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("今日生成次数已用完");
});

test("deleting needs a second click and returns to history", async () => {
  const calls = mockFetch({
    "/api/tasks/t1": makeTask({ status: "ready" }),
    "DELETE /api/tasks/t1": new Response(null, { status: 204 }),
  });
  renderTask();
  await userEvent.click(await screen.findByRole("button", { name: "删除" }));
  expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "确认删除" }));
  expect(await screen.findByTestId("location")).toHaveTextContent("/history");
});

test("a missing task shows the server message", async () => {
  mockFetch({ "/api/tasks/t1": json(404, { detail: "任务不存在" }) });
  renderTask();
  expect(await screen.findByRole("alert")).toHaveTextContent("任务不存在");
});
```

- [x] **Step 2: 运行，确认失败**

Run: `cd frontend && npx vitest run src/pages/TaskPage.test.tsx`
Expected: FAIL（占位页只显示“任务”）

- [x] **Step 3: 实现 `frontend/src/pages/TaskPage.tsx`**

```tsx
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
            onExecute={(index) => createRound.mutate({ suggestion: { round_id: current.id, index } })}
            onAccept={() => setFinal.mutate(current.id)}
          />
          {!pending && (
            <details className="rounded-xl border border-slate-200 bg-white p-3">
              <summary className="cursor-pointer text-sm font-medium">再来一轮</summary>
              <div className="mt-3">
                <RoundForm
                  hasText={Boolean(t.confirmed_text)}
                  submitLabel="生成新一轮"
                  onSubmit={(req) => createRound.mutate(req, { onSuccess: () => setSelected(null) })}
                />
              </div>
            </details>
          )}
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
  return (
    <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
      <div className="space-y-2">
        <CompareViewer
          left={{ src: fileUrl(task.id, "source"), label: "原图" }}
          right={{ src: fileUrl(task.id, `result-${round.seq}`), label: `第 ${round.seq} 轮` }}
        />
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <a className="btn-primary" href={fileUrl(task.id, `download-${round.seq}`, true)}>
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
```

- [x] **Step 4: 运行，确认通过**

Run: `cd frontend && npx vitest run && npm run typecheck`
Expected: 全部 passed

- [x] **Step 5: Commit**

```bash
git add frontend/src/pages/TaskPage.tsx frontend/src/pages/TaskPage.test.tsx
git commit -m "feat: task page with transcript, rounds, review and downloads" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: 历史页与游客页

**Files:**
- Modify: `frontend/src/pages/HistoryPage.tsx`, `frontend/src/pages/GuestPage.tsx`（替换占位）
- Create: `frontend/src/pages/HistoryPage.test.tsx`, `frontend/src/pages/GuestPage.test.tsx`

**Interfaces:**
- Produces:
  - 历史页：`<h1>历史</h1>`；每行链接 `任务 {id8}`、尺寸/轮数/时间/是否定稿、状态徽标、两步删除（“删除”→“确认删除”，`aria-label` 含任务号）；有下一页时“加载更多”（带 `cursor`）
  - 游客页：`<h1>截图文字清晰化 · 临时使用</h1>`；“今日剩余 N 次”；上传区（剩余 0 时禁用）+ 折叠的自定义提示词；上传成功写入 `?task=<id>`；按 `?task=` 轮询游客任务：`generating` → Working；`round_failed` → 错误 + “重新上传”；`done` → 对比 + “下载”链接 + “再处理一张”

- [x] **Step 1: 写失败测试**

`frontend/src/pages/HistoryPage.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockFetch } from "../test/fetch";
import { renderWithProviders } from "../test/utils";
import HistoryPage from "./HistoryPage";

const item = (id: string) => ({
  id,
  status: "done" as const,
  source_w: 400,
  source_h: 300,
  created_at: "2026-10-14T06:00:00",
  final_round_id: 1,
  rounds: 2,
});

test("lists tasks and loads more with the cursor", async () => {
  const calls = mockFetch({
    "/api/tasks": (_init: RequestInit | undefined, url: string) =>
      url.includes("cursor=")
        ? { items: [item("cccccccc")], next_cursor: null }
        : { items: [item("aaaaaaaa"), item("bbbbbbbb")], next_cursor: "2026-10-14T05:00:00" },
  });
  renderWithProviders(<HistoryPage />);
  expect(await screen.findByRole("link", { name: "任务 aaaaaaaa" })).toHaveAttribute("href", "/tasks/aaaaaaaa");
  expect(screen.getAllByText(/2 轮/)).toHaveLength(2);
  await userEvent.click(screen.getByRole("button", { name: "加载更多" }));
  expect(await screen.findByRole("link", { name: "任务 cccccccc" })).toBeInTheDocument();
  expect(calls.some((c) => c.url.includes("cursor=2026-10-14T05%3A00%3A00"))).toBe(true);
});

test("deleting asks for a second click", async () => {
  const calls = mockFetch({
    "/api/tasks": { items: [item("aaaaaaaa")], next_cursor: null },
    "DELETE /api/tasks/aaaaaaaa": new Response(null, { status: 204 }),
  });
  renderWithProviders(<HistoryPage />);
  await userEvent.click(await screen.findByRole("button", { name: "删除任务 aaaaaaaa" }));
  expect(calls.some((c) => c.init?.method === "DELETE")).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "确认删除任务 aaaaaaaa" }));
  expect(calls.some((c) => c.init?.method === "DELETE")).toBe(true);
});
```

`frontend/src/pages/GuestPage.test.tsx`:

```tsx
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mockFetch } from "../test/fetch";
import { makeRound } from "../test/fixtures";
import { renderWithProviders } from "../test/utils";
import GuestPage from "./GuestPage";

const quota = { limit: 3, remaining: 2, global_remaining: 90 };
const guestTask = (over = {}) => ({
  id: "g1",
  status: "done",
  source_w: 400,
  source_h: 300,
  created_at: "2026-10-14T06:00:00",
  expires_at: "2026-10-15T06:00:00",
  round: makeRound({ use_text_hint: false, review: null }),
  ...over,
});

test("shows the remaining quota and uploads with an optional prompt", async () => {
  const calls = mockFetch({ "/api/guest/quota": quota, "POST /api/guest/tasks": guestTask() });
  renderWithProviders(<GuestPage />, { route: "/guest", path: "/guest" });
  expect(await screen.findByText(/今日剩余 2 次/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("提示词"), "保持原样");
  await userEvent.upload(screen.getByTestId("file-input"), new File(["x"], "a.png", { type: "image/png" }));
  const body = calls.find((c) => c.init?.method === "POST")?.init?.body as FormData;
  expect(body.get("prompt")).toBe("保持原样");
  expect(await screen.findByRole("link", { name: "下载" })).toHaveAttribute("href", "/api/files/g1/download-1?download=1");
});

test("an exhausted quota disables uploading and explains why", async () => {
  mockFetch({ "/api/guest/quota": { ...quota, remaining: 0 } });
  renderWithProviders(<GuestPage />, { route: "/guest", path: "/guest" });
  expect(await screen.findByText(/今日剩余 0 次/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /拖入、粘贴或点击/ })).toHaveAttribute("aria-disabled", "true");
});

test("quota errors from the server are shown", async () => {
  mockFetch({
    "/api/guest/quota": quota,
    "POST /api/guest/tasks": json(429, { detail: "今日免费次数已用完，登录后可继续使用" }),
  });
  renderWithProviders(<GuestPage />, { route: "/guest", path: "/guest" });
  await userEvent.upload(await screen.findByTestId("file-input"), new File(["x"], "a.png", { type: "image/png" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("今日免费次数已用完");
});

test("refreshing with ?task= resumes the task", async () => {
  mockFetch({ "/api/guest/quota": quota, "/api/guest/tasks/g1": guestTask({ status: "generating", round: null }) });
  renderWithProviders(<GuestPage />, { route: "/guest?task=g1", path: "/guest" });
  expect(await screen.findByText("正在生成（约 1–3 分钟）…")).toBeInTheDocument();
});

test("a failed guest round explains and offers a fresh upload", async () => {
  mockFetch({
    "/api/guest/quota": quota,
    "/api/guest/tasks/g1": guestTask({ status: "round_failed", round: makeRound({ status: "failed", error: "上游繁忙：x", review: null }) }),
  });
  renderWithProviders(<GuestPage />, { route: "/guest?task=g1", path: "/guest" });
  expect(await screen.findByText(/上游繁忙：x/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "重新上传" }));
  expect(await screen.findByTestId("file-input")).toBeInTheDocument();
});
```

- [x] **Step 2: 运行，确认失败**

Run: `cd frontend && npx vitest run src/pages/HistoryPage.test.tsx src/pages/GuestPage.test.tsx`
Expected: FAIL（占位页）

- [x] **Step 3: 实现 `frontend/src/pages/HistoryPage.tsx`**

```tsx
import { useState } from "react";
import { Link } from "react-router";
import { fileUrl } from "../api/client";
import { useDeleteTask, useTasks } from "../api/hooks";
import { ErrorNote } from "../components/ErrorNote";
import { StatusBadge } from "../components/StatusBadge";
import { formatSize, formatTime } from "../lib/format";

export default function HistoryPage() {
  const tasks = useTasks(20);
  const remove = useDeleteTask();
  const [confirming, setConfirming] = useState<string | null>(null);
  const items = tasks.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">历史</h1>
      {tasks.error && <ErrorNote error={tasks.error} />}
      {remove.error && <ErrorNote error={remove.error} />}
      {items.length === 0 && !tasks.isPending ? (
        <p className="text-sm text-slate-500">暂无任务。</p>
      ) : (
        <ul className="divide-y divide-slate-200 rounded-xl border border-slate-200 bg-white">
          {items.map((t) => {
            const short = t.id.slice(0, 8);
            const armed = confirming === t.id;
            return (
              <li key={t.id} className="flex flex-wrap items-center gap-3 p-3">
                <img src={fileUrl(t.id, "thumb")} alt="" className="h-14 w-20 rounded object-cover" />
                <div className="min-w-0 flex-1">
                  <Link to={`/tasks/${t.id}`} className="font-medium text-indigo-700">
                    任务 {short}
                  </Link>
                  <div className="text-xs text-slate-500">
                    {formatSize(t.source_w, t.source_h)} · {t.rounds} 轮 · {formatTime(t.created_at)}
                    {t.final_round_id ? " · 已定稿" : ""}
                  </div>
                </div>
                <StatusBadge status={t.status} />
                <button
                  type="button"
                  className="btn-danger"
                  aria-label={`${armed ? "确认删除" : "删除"}任务 ${short}`}
                  disabled={remove.isPending}
                  onClick={() => {
                    if (!armed) {
                      setConfirming(t.id);
                      return;
                    }
                    remove.mutate(t.id, { onSuccess: () => setConfirming(null) });
                  }}
                >
                  {armed ? "确认删除" : "删除"}
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {tasks.hasNextPage && (
        <button type="button" className="btn-secondary" disabled={tasks.isFetchingNextPage} onClick={() => void tasks.fetchNextPage()}>
          加载更多
        </button>
      )}
    </div>
  );
}
```

- [x] **Step 4: 实现 `frontend/src/pages/GuestPage.tsx`**

```tsx
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
```

- [x] **Step 5: 运行，确认通过**

Run: `cd frontend && npx vitest run && npm run typecheck`
Expected: 全部 passed（含 Task 5 的 App 测试：历史页仍有 `<h1>历史</h1>`）

- [x] **Step 6: Commit**

```bash
git add frontend/src/pages/HistoryPage.tsx frontend/src/pages/HistoryPage.test.tsx frontend/src/pages/GuestPage.tsx frontend/src/pages/GuestPage.test.tsx
git commit -m "feat: history page and guest page" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: 管理页

**Files:**
- Modify: `frontend/src/pages/AdminPage.tsx`（替换占位）
- Create: `frontend/src/pages/AdminPage.test.tsx`

**Interfaces:**
- Produces：`<h1>管理</h1>`；用户区：新建表单（`aria-label` 新用户名/新用户密码/新用户角色/新用户额度，额度留空 → `null`）、用户表（角色、`今日/额度` 可编辑并在失焦时保存、禁用/启用、重置密码内联输入“{用户名} 的新密码”+“保存密码”）；设置区：每个 `effective` 键一个输入框（中文标签），“保存设置”只提交改动项，数字类转成 number；错误统一 `ErrorNote`

- [x] **Step 1: 写失败测试 `frontend/src/pages/AdminPage.test.tsx`**

```tsx
import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { json, mockFetch } from "../test/fetch";
import { renderWithProviders } from "../test/utils";
import AdminPage from "./AdminPage";

const users = [
  { id: 1, username: "root", role: "admin", daily_quota: 50, disabled: false, created_at: "2026-10-14T06:00:00", used_today: 3 },
  { id: 2, username: "bob", role: "user", daily_quota: 50, disabled: false, created_at: "2026-10-14T06:00:00", used_today: 0 },
];
const settings = {
  effective: { image_model: "gpt-image-2.5", pixel_cap: 1550000 },
  overrides: {},
  restart_required: ["upstream_concurrency"],
};

function setup(extra: Record<string, unknown> = {}) {
  const calls = mockFetch({ "/api/admin/users": users, "/api/admin/settings": settings, ...extra });
  renderWithProviders(<AdminPage />);
  return calls;
}

const lastBody = (calls: { url: string; init?: RequestInit }[], url: string) =>
  JSON.parse([...calls].reverse().find((c) => c.url === url && c.init?.method !== "GET")?.init?.body as string);

test("creates a user with a default quota", async () => {
  const calls = setup({ "POST /api/admin/users": users[1] });
  await userEvent.type(await screen.findByLabelText("新用户名"), "carol");
  await userEvent.type(screen.getByLabelText("新用户密码"), "password123");
  await userEvent.click(screen.getByRole("button", { name: "新建用户" }));
  expect(lastBody(calls, "/api/admin/users")).toEqual({ username: "carol", password: "password123", role: "user", daily_quota: null });
});

test("disables a user and edits the quota", async () => {
  const calls = setup({ "PATCH /api/admin/users/2": users[1] });
  const rowButtons = await screen.findAllByRole("button", { name: "禁用" });
  await userEvent.click(rowButtons[1]);
  expect(lastBody(calls, "/api/admin/users/2")).toEqual({ disabled: true });
  const quota = screen.getByLabelText("bob 的每日额度");
  await userEvent.clear(quota);
  await userEvent.type(quota, "5");
  fireEvent.blur(quota);
  expect(lastBody(calls, "/api/admin/users/2")).toEqual({ daily_quota: 5 });
});

test("resets a password inline", async () => {
  const calls = setup({ "PATCH /api/admin/users/2": users[1] });
  const resets = await screen.findAllByRole("button", { name: "重置密码" });
  await userEvent.click(resets[1]);
  await userEvent.type(screen.getByLabelText("bob 的新密码"), "newpassword1");
  await userEvent.click(screen.getByRole("button", { name: "保存密码" }));
  expect(lastBody(calls, "/api/admin/users/2")).toEqual({ password: "newpassword1" });
});

test("saves only changed settings with numbers kept numeric", async () => {
  const calls = setup({ "PATCH /api/admin/settings": settings });
  const save = await screen.findByRole("button", { name: "保存设置" });
  expect(save).toBeDisabled();
  await userEvent.clear(screen.getByLabelText("单次输出像素上限"));
  await userEvent.type(screen.getByLabelText("单次输出像素上限"), "1200000");
  await userEvent.click(save);
  expect(lastBody(calls, "/api/admin/settings")).toEqual({ pixel_cap: 1200000 });
});

test("setting validation errors are shown", async () => {
  setup({ "PATCH /api/admin/settings": json(400, { detail: "pixel_cap 必须在 100000 到 20000000 之间" }) });
  await userEvent.clear(await screen.findByLabelText("单次输出像素上限"));
  await userEvent.type(screen.getByLabelText("单次输出像素上限"), "10");
  await userEvent.click(screen.getByRole("button", { name: "保存设置" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("pixel_cap 必须在 100000 到 20000000 之间");
});
```

- [x] **Step 2: 运行，确认失败**

Run: `cd frontend && npx vitest run src/pages/AdminPage.test.tsx`
Expected: FAIL（占位页）

- [x] **Step 3: 实现 `frontend/src/pages/AdminPage.tsx`**

```tsx
import { useState } from "react";
import {
  useAdminSettings,
  useAdminUsers,
  useCreateUser,
  usePatchSettings,
  usePatchUser,
} from "../api/hooks";
import type { AdminUser, SettingsView } from "../api/types";
import { ErrorNote } from "../components/ErrorNote";

const SETTING_LABEL: Record<string, string> = {
  image_model: "生图模型",
  transcribe_model: "转写模型",
  review_model: "审查模型",
  pixel_cap: "单次输出像素上限",
  upstream_concurrency: "上游并发（重启后生效）",
  guest_daily_per_ip: "游客每 IP 每日次数",
  guest_daily_global: "游客全站每日次数",
  user_daily_default: "新用户默认每日额度",
  retention_user_days: "登录用户保留天数",
  retention_guest_hours: "游客保留小时数",
  max_upload_mb: "上传大小上限（MB）",
  max_pixels: "上传像素上限",
};

export default function AdminPage() {
  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold">管理</h1>
      <UsersSection />
      <SettingsSection />
    </div>
  );
}

function UsersSection() {
  const users = useAdminUsers();
  const create = useCreateUser();
  const patch = usePatchUser();
  const [form, setForm] = useState({ username: "", password: "", role: "user" as "user" | "admin", quota: "" });
  const [resetFor, setResetFor] = useState<number | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const error = users.error ?? create.error ?? patch.error;
  return (
    <section className="space-y-3">
      <h2 className="font-semibold">用户</h2>
      {error && <ErrorNote error={error} />}
      <form
        className="flex flex-wrap items-end gap-2 rounded-xl border border-slate-200 bg-white p-3"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            {
              username: form.username.trim(),
              password: form.password,
              role: form.role,
              daily_quota: form.quota === "" ? null : Number(form.quota),
            },
            { onSuccess: () => setForm({ username: "", password: "", role: "user", quota: "" }) },
          );
        }}
      >
        <label className="text-sm">
          用户名
          <input aria-label="新用户名" className="input mt-1" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
        </label>
        <label className="text-sm">
          密码
          <input aria-label="新用户密码" type="password" className="input mt-1" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </label>
        <label className="text-sm">
          角色
          <select aria-label="新用户角色" className="input mt-1" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as "user" | "admin" })}>
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </select>
        </label>
        <label className="text-sm">
          每日额度
          <input aria-label="新用户额度" type="number" min={0} placeholder="默认" className="input mt-1 w-24" value={form.quota} onChange={(e) => setForm({ ...form, quota: e.target.value })} />
        </label>
        <button type="submit" className="btn-primary" disabled={create.isPending}>
          新建用户
        </button>
      </form>
      <div className="overflow-x-auto">
        <table className="w-full rounded-xl border border-slate-200 bg-white text-sm">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="p-2">用户名</th>
              <th>角色</th>
              <th>今日/额度</th>
              <th>状态</th>
              <th className="p-2">操作</th>
            </tr>
          </thead>
          <tbody>
            {users.data?.map((u) => (
              <tr key={u.id} className="border-t border-slate-100">
                <td className="p-2">{u.username}</td>
                <td>{u.role === "admin" ? "管理员" : "普通用户"}</td>
                <td>
                  <QuotaEditor user={u} onSave={(q) => patch.mutate({ id: u.id, daily_quota: q })} />
                </td>
                <td>{u.disabled ? "已禁用" : "正常"}</td>
                <td className="space-x-2 p-2 whitespace-nowrap">
                  <button type="button" className="btn-secondary" onClick={() => patch.mutate({ id: u.id, disabled: !u.disabled })}>
                    {u.disabled ? "启用" : "禁用"}
                  </button>
                  {resetFor === u.id ? (
                    <span className="inline-flex gap-1">
                      <input aria-label={`${u.username} 的新密码`} type="password" className="input w-36" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
                      <button
                        type="button"
                        className="btn-primary"
                        onClick={() =>
                          patch.mutate(
                            { id: u.id, password: newPassword },
                            {
                              onSuccess: () => {
                                setResetFor(null);
                                setNewPassword("");
                              },
                            },
                          )
                        }
                      >
                        保存密码
                      </button>
                    </span>
                  ) : (
                    <button type="button" className="btn-secondary" onClick={() => setResetFor(u.id)}>
                      重置密码
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function QuotaEditor({ user, onSave }: { user: AdminUser; onSave: (quota: number) => void }) {
  const [value, setValue] = useState(String(user.daily_quota));
  return (
    <span className="inline-flex items-center gap-1">
      {user.used_today}/
      <input
        aria-label={`${user.username} 的每日额度`}
        type="number"
        min={0}
        className="input w-20"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => {
          if (value !== "" && Number(value) !== user.daily_quota) onSave(Number(value));
        }}
      />
    </span>
  );
}

function SettingsSection() {
  const settings = useAdminSettings();
  const patch = usePatchSettings();
  if (!settings.data) return settings.error ? <ErrorNote error={settings.error} /> : null;
  return <SettingsForm view={settings.data} pending={patch.isPending} error={patch.error} onSave={(c) => patch.mutate(c)} />;
}

function SettingsForm({
  view,
  pending,
  error,
  onSave,
}: {
  view: SettingsView;
  pending: boolean;
  error: unknown;
  onSave: (changes: Record<string, string | number>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(view.effective).map(([k, v]) => [k, String(v)])),
  );
  const changes: Record<string, string | number> = Object.fromEntries(
    Object.entries(values)
      .filter(([k, v]) => v !== String(view.effective[k]))
      .map(([k, v]) => [k, typeof view.effective[k] === "number" ? Number(v) : v]),
  );
  return (
    <form
      className="space-y-3 rounded-xl border border-slate-200 bg-white p-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSave(changes);
      }}
    >
      <h2 className="font-semibold">系统设置</h2>
      {error ? <ErrorNote error={error} /> : null}
      <div className="grid gap-3 sm:grid-cols-2">
        {Object.keys(view.effective).map((key) => (
          <label key={key} className="text-sm">
            {SETTING_LABEL[key] ?? key}
            <input
              aria-label={SETTING_LABEL[key] ?? key}
              className="input mt-1"
              value={values[key]}
              onChange={(e) => setValues({ ...values, [key]: e.target.value })}
            />
          </label>
        ))}
      </div>
      <button type="submit" className="btn-primary" disabled={pending || Object.keys(changes).length === 0}>
        保存设置
      </button>
    </form>
  );
}
```

- [x] **Step 4: 运行，确认通过**

Run: `cd frontend && npx vitest run && npm run typecheck`
Expected: 全部 passed

- [x] **Step 5: Commit**

```bash
git add frontend/src/pages/AdminPage.tsx frontend/src/pages/AdminPage.test.tsx
git commit -m "feat: admin page for users and settings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: 浏览器 E2E 与构建集成

**Files:**
- Create: `scripts/e2e_server.py`, `frontend/playwright.config.ts`, `frontend/e2e/smoke.spec.ts`, `frontend/e2e/fixtures/sample.png`（64×48 白图，由 Step 3 生成）
- Modify: `README.md`（新增“前端”一节）

**Interfaces:**
- Consumes: 后端 `create_app`（Task 1 的 SPA 托管）、`tests/fakes.py` 的 `FakeImages/FakeChat`、构建产物 `frontend/dist`
- Produces: `uv run python scripts/e2e_server.py --port 18091`（临时数据目录、假上游：转写与审查都返回“示例原文。”、预置管理员 `admin/password123`）；`npm run e2e` 跑两条冒烟：登录用户完整流程、游客流程（含 390px 手机视口无横向滚动）。

- [x] **Step 1: 写 `scripts/e2e_server.py`**

```python
"""Run the app with fake relay clients for browser E2E tests (no network, no cost).

usage: uv run python scripts/e2e_server.py [--port 18091]
Serves frontend/dist (run `npm run build` in frontend/ first). Seeds admin/password123.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from imgsr.api.app import create_app  # noqa: E402
from imgsr.auth import hash_password  # noqa: E402
from imgsr.config import Settings  # noqa: E402
from imgsr.db.models import User  # noqa: E402
from imgsr.db.session import make_engine, migrate  # noqa: E402
from tests.fakes import FakeChat, FakeImages  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18091)
    args = parser.parse_args()
    data_dir = Path(tempfile.mkdtemp(prefix="imgsr-e2e-"))
    settings = Settings(_env_file=None, data_dir=data_dir, cookie_secure=False,
                        trusted_proxies="127.0.0.1/32", static_dir=ROOT / "frontend" / "dist")
    engine = make_engine(settings.db_path)
    migrate(engine)
    with Session(engine) as db:
        db.add(User(username="admin", password_hash=hash_password("password123"), role="admin", daily_quota=100))
        db.commit()
    engine.dispose()
    app = create_app(settings, images=FakeImages(scale=1.5), chat=FakeChat(lambda i, size: "示例原文。"),
                     retry_delays=(0.0, 0.0), maintenance=False)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
```

- [x] **Step 2: 写 `frontend/playwright.config.ts`**

```ts
import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:18091", locale: "zh-CN" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "cd .. && uv run python scripts/e2e_server.py --port 18091",
    url: "http://127.0.0.1:18091/api/health",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
```

- [x] **Step 3: 生成测试图片并写 `frontend/e2e/smoke.spec.ts`**

```bash
mkdir -p frontend/e2e/fixtures
uv run python -c "from PIL import Image; Image.new('RGB', (64, 48), 'white').save('frontend/e2e/fixtures/sample.png')"
```

```ts
import { expect, test } from "@playwright/test";

const file = "e2e/fixtures/sample.png"; // relative to frontend/, where `npm run e2e` runs

test("logged-in flow: upload → confirm → generate → accept → download", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
  await page.getByLabel("用户名").fill("admin");
  await page.getByLabel("密码").fill("password123");
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { name: "工作台" })).toBeVisible();
  await page.getByTestId("file-input").setInputFiles(file);
  await expect(page.getByLabel("原文")).toHaveValue("示例原文。", { timeout: 20_000 });
  await page.getByRole("button", { name: "确认原文" }).click();
  await page.getByRole("button", { name: "开始生成" }).click();
  await page.getByRole("button", { name: "设为最终版" }).click({ timeout: 20_000 });
  await expect(page.getByText("已定稿").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "下载" })).toHaveAttribute("href", /download-1\?download=1$/);
});

test("guest flow on a phone-sized screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/guest");
  await expect(page.getByText(/今日剩余 3 次/)).toBeVisible();
  await page.getByTestId("file-input").setInputFiles(file);
  await expect(page.getByRole("link", { name: "下载" })).toBeVisible({ timeout: 20_000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
```

- [x] **Step 4: 构建并运行 E2E**

```bash
cd frontend
npm run build
npx playwright install chromium
npm run e2e
```

Expected: `2 passed`。若首条用例在“设为最终版”超时，先确认后端日志里 review 任务完成（假上游转写与审查返回同一段文字 → 差异为 0 → 建议为 accept）。

- [x] **Step 5: 更新 `README.md`**

在“## 测试”一节之前插入：

````markdown
## 前端

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173，/api 代理到 127.0.0.1:18090（先在仓库根 uv run imgsr serve --port 18090）
npm test           # Vitest 单元测试
npm run build      # 输出 frontend/dist，由后端 STATIC_DIR（默认 frontend/dist）托管
npm run e2e        # Playwright 冒烟：自动启动 scripts/e2e_server.py（假上游，不花钱）
```
````

- [x] **Step 6: 全量验证**

Run: `uv run pytest -q && uv run ruff check src tests scripts && cd frontend && npx vitest run && npm run typecheck && npm run build`
Expected: 全部通过

- [x] **Step 7: Commit**

```bash
git add scripts/e2e_server.py frontend/playwright.config.ts frontend/e2e/smoke.spec.ts frontend/e2e/fixtures/sample.png README.md
git commit -m "test: browser E2E against a fake relay; document the frontend" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 执行记录

2026-10-14，分支 `feat/frontend`，Native 方式（本会话逐 Task 执行 + 结束时一次 Opus 整分支审查）。

**Task 提交**：T1 951b56d · T2 1a21242 · T3 c19ece8 · T4 791dea9 · T5 74f4359 · T6 922abbf · T7 7fa01ae · T8 ca7c30e · T9 96efb27 · T10 70df5a8 · T11 6cfc0b2 · T12 ad6625b；审查修复 87353d0。

**最终测试**：前端 vitest 85/85、typecheck 无错误、Playwright E2E 2/2（重新 build 后）；后端 pytest 198/198。

**偏离计划的裁决**：
- T1：5 条 SPA 测试中 3 条（未知 /api 404、路径穿越、静态目录缺失）在实现前就通过——属于防回归测试；2 条托管测试按预期先红后绿。
- T2：计划固定 `vitest@^3`，其依赖 tinypool / @vitest/mocker 带 2 个 critical + 1 个 moderate 的 npm 漏洞告警，改用 `vitest@^4`（4.1.11），0 漏洞。
- T11：额度输入失焦后 PATCH 在下一个微任务才发出，测试断言改用 `waitFor`（仅测试代码）。
- T12：E2E 首次运行即通过（T12 无新增生产代码，行为已由 T1–T11 单测驱动），无 RED 阶段。
- 视觉检查：Playwright MCP 需要 9222 端口的 CDP Chrome，未运行，改用项目自带 Playwright Chromium 截图；登录、工作台、原文确认、审查结果、并排对比、游客页 390px 均正常，无横向滚动，并排模式滚轮缩放同步。

**整分支审查（Opus）**：结论“修复后可合并”。1 个 Critical + 8 个 Important 在一轮修复中处理，每项先写失败测试再修（`frontend/src/pages/regressions.test.tsx`）：
- 任一成功轮次都可“设为最终版”（此前只有差异为 0 的轮次能定稿）；审查建议里的接受按钮改名为“采用本轮并定稿”，避免同名按钮。
- 没有确认原文、未经比对的审查不再显示“一致 / 差异 0”，改为“未比对”。
- 执行建议、重试后自动切到新一轮；操作被拒（如 409）时刷新任务，让轮询恢复。
- 游客失败退额后刷新额度；游客任务不存在时提供“重新上传”。
- “再来一轮”表单在请求进行中保持挂载，被拒后不丢输入。
- 对比查看器可选“对比基准”（原图或其他轮次）。
- 差异条目可点击（复制所在句子并提示到对比查看器中放大查找），`manual_check` 涉及的差异标“需人工核对”。

**审查中未判断事项的裁决**：CSP / 安全头放到部署计划；手机上缩放与页面滚动的冲突、iPhone Safari 下微秒时间戳的显示，部署后真机检查；手机加载原尺寸图、每条建议一个“执行”、“同步缩放”无说明、同 `created_at` 分页、React 19、无改角色界面（角色在 `imgsr create-user --admin` 时确定）——均维持现状。

**暂缓的 Minor**（留待后续）：轮询出错时整页被替换；401 后仍轮询；旧的操作错误残留；“去登录”不带 `from`；已完成任务默认不选中定稿轮；删除确认状态不重置；“修改原文”没有取消；RoundForm 不预填；默认提示词不可见；执行建议时不能叠加高级设置；2xx 非 JSON / `text()` 异常未处理；413 提示不友好；路径段未 `encodeURIComponent`；SPA 细节（未知 /api 的 POST/HEAD 返回 405、favicon.ico 返回 index、assets 与 index.html 缓存头、相对 `static_dir` 日志）；无障碍（dropzone 空格键、tablist 角色）；admin（密码 minLength、额度回车保存）；测试层面（双击测试只测 prop、e2e 不先 build、游客刷新未测、e2e_server 临时目录泄漏）；登录用户头部“今日 x/y”在退额后不刷新。
