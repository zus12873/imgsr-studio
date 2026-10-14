# imgsr-studio 设计说明（截图文字清晰化工具站）

- 日期：2026-10-14
- 状态：待用户审阅
- 部署目标：`https://imgsr.huanmeng.cc`（自有服务器，已有 Docker + 反代）
- 前期实验与样张：`~/Downloads/Projects/ai_video_gen/data/imgsr/`（不进 Git）

## 1. 背景与目标

用户在 Gemini 里用“帮我将图片中的文字及相关内容更清晰”把模糊截图重绘成清晰版（`data/imgsr/sample.jpg` → `target.jpg`）。这不是像素超分，而是**生成式整页重绘**：文字换成清晰字体、保留颜色与排版、放大约 1.65 倍。

本项目做一个小型工具站，用 sub2api 中转站上的 OpenAI 图像模型复现这一效果，并加入“转写 → 生成 → 审查 → 人确认”的半自动循环，把**错字**这个生成式方法的核心风险降到可控。

**使用者**：站长本人 + 少数熟人（登录用户）；另有免登录的临时使用页（按 IP 限次）。

**成功标准**

1. 登录用户能对一张截图完成：上传 → 确认原文 → 生成 → 查看审查差异 → 按建议再来一轮 → 定稿下载。
2. 输出与原图逐字一致是首要目标；无法自动保证时，界面能让人高效核对（同步缩放对比、差异列表）。
3. 超过模型像素上限的图自动切块，输出分辨率不低于原图；宽高比 > 3:1 的图不被拉伸。
4. 游客与登录用户的调用次数受限，密钥不外泄，成本有上限。

## 2. 已实测的事实（决定设计的约束）

以下均为 2026-10-13/14 在 `your-relay.example.com` 上的实测，每项样本量小（多为 1 次），换模型或中转站变化后需重测。

| 事实 | 数据 | 设计影响 |
|---|---|---|
| `gpt-image-2.5` 的 `/v1/images/edits`（multipart）可用 | 21 张样张全部 200；单次 15–45 s | 默认图像模型 |
| 输出面积硬上限 ≈ **1.57 MP**，与请求的 `size` 无关 | 1104×1424、1886×834、1677×938… | 超限图必须切块；`PIXEL_CAP` 可配置 |
| 宽高比被夹到 ≤ 3:1，超出部分由模型补白边 | 1838×456 → 2171×724 | 送入前自行补边到 3:1，回来后裁掉 |
| 中转站回报 `quality` 为 low/medium，不受请求控制 | 请求 high，回报 low | 不暴露 quality 选项 |
| `gpt-image-2` 同样 1.57 MP 上限 | 1885×834 | — |
| `grok-imagine-image-2.0` 改图输出约 1 MP，且擅自改字色 | 896×1152，“想养”变蓝 | 不作为默认；保留可配置 |
| 首轮 21 张中 19 张未发现错字（OCR 比对 + 放大抽查）；错字集中在字小/被下采样的图 | 家→冢、蹿→蹦、亮光→光光、玩耍→玩要 | 需要原文提示 + 切块 + 审查 |
| 在提示词里附上**确切原文**后，被提示的句子全部修正 | 图片2/17 重跑 | 生成默认带原文提示 |
| 切块（按空白行/列切，重叠 ≈ 空白带宽度）后拼接缝不可见 | 接缝两侧底色差 < 1 | 自动切块可行 |
| 重跑会在别处引入新错（按下葫芦浮起瓢） | 图片2 第 2、3 次重跑 | 每轮审查整图；保留所有轮次供人挑选 |
| 模型对个别字形有系统性偏差，加提示也改不对 | 粗楷体“耍”3 次都画成“要” | 规则引擎给出 `manual_check`；字形修补留二期 |
| `gpt-6-sol` 流式 chat 可用（不触发 524），先思考 50–60 s 再一次性输出 | — | 前端只显示“处理中”，不显示逐字流 |
| `gpt-6-sol` 转写：清晰截图 100%；**模糊讲义 95.3%，会编出通顺的错词且不标不确定** | 单杠→草杆、笛声→钢琴 | 原文确认页必须让人逐句核对 |
| `gpt-6-sol` 转写清晰结果图做审查 | 99.8%；抓到“光光”，漏“玩要” | 审查是提示而非保证 |
| 让视觉模型直接“对照原文找差异”效果更差 | 2 处真错全漏 + 误报 | 审查=独立转写 + 代码比对 |
| sub2api 在 Cloudflare 后，非流式请求 > 100 s 返回 **524** | `gpt-6.1-sol` 实测 | 所有 chat 调用走流式 |
| 对照数据：`gpt-5.5` 模糊讲义转写 99.8%、11–66 s | — | 作为可切换备选 |

用户已选择 ①转写 与 ③审查 默认都用 `gpt-6-sol`；管理页可按环节切换。

## 3. 范围

**一期（本 spec）**

- 登录用户完整循环：①转写 → 人确认原文 → ②生成（自动切块、原文提示）→ ③审查 → ④规则建议 → 人点执行；多轮对比、定稿、下载、历史。
- 游客临时页：上传 → 可选改提示词 → 生成一轮 → 对比 → 下载；无转写、无审查、无历史。
- 管理：建号/禁用/重置密码/调限额；模型、并发、限额、保留期等设置。
- 单容器部署到服务器，子域名 `imgsr.huanmeng.cc`。

**二期（不在本 spec）**

- 跨轮次按区域拼出最佳版本；agent 自动连跑多轮。
- 带坐标的 OCR（如 PaddleOCR），在图上框出差异位置。
- 字形修补工具（用字体替换个别错字）。
- 架构升级到 PostgreSQL + Redis 队列 + 独立 worker（用户量上升后）。

**非目标**

- 不做注册、找回密码、邮件、第三方登录。
- 不专门做去水印；默认提示词不包含去水印指令。
- 不做批量上传（一期一次一张）。

## 4. 架构与组件

方案 A：**单 FastAPI 进程 + React SPA + SQLite + 本地磁盘**，一个 Docker 容器。

```
浏览器（React + Vite SPA）
   │ HTTPS：反代 → 容器 127.0.0.1:18090（默认，部署前检查端口占用）
FastAPI 进程（同时托管 SPA 静态文件）
 ├─ api/        路由：auth / tasks / rounds / files / guest / admin / health；只做校验与权限
 ├─ jobs/       任务执行器：asyncio 队列 + 上游并发闸门（默认 3）；任务状态持久化在 SQLite
 ├─ pipeline/   纯函数（无网络、无 DB）
 │    ├─ tiling.py    空白带检测 → 切块方案；3:1 补边方案
 │    ├─ compose.py   缩放、拼接、裁回、下载版尺寸
 │    ├─ prompt.py    基础提示词 + 原文提示 → 最终提示词
 │    ├─ textdiff.py  标点/空白归一化 → 字级差异 → 按句聚合
 │    └─ align.py     把切块转写对齐到确认原文，截出每块对应原文
 ├─ review/     审查 agent：结果转写 → textdiff → rules.py 产出建议
 ├─ relay/      中转站客户端：images.edit()、chat.transcribe()（流式）；重试/超时/错误分类
 ├─ storage/    文件读写与路径规划（/data/files/{task_id}/…）
 ├─ db/         SQLAlchemy 2 模型 + Alembic 迁移
 └─ cli.py      create-user / reset-password / cleanup
```

**技术栈**：Python ≥ 3.11（uv 管理）、FastAPI、SQLAlchemy 2、Alembic、Pillow、httpx、argon2-cffi、pydantic-settings；前端 React 18 + TypeScript + Vite + React Router + TanStack Query + Tailwind CSS + `react-zoom-pan-pinch`。

**原则**

- `pipeline/` 全部是可单测的纯函数；网络只在 `relay/`；I/O 只在 `storage/` 与 `db/`。
- CPU 密集的图像处理在 `asyncio.to_thread` 中执行，不阻塞事件循环。
- 模型名、中转站地址、上限、并发、限额均为配置项；换模型不改代码。
- 审查 agent 用**规则引擎**选动作，不让大模型做决策；大模型只负责转写。

## 5. 数据模型（SQLite）

| 表 | 字段（要点） | 说明 |
|---|---|---|
| `users` | id, username(unique), password_hash(argon2id), role(admin/user), daily_quota, disabled, created_at | 无注册入口 |
| `sessions` | id, token_hash, user_id, expires_at, last_seen_at | Cookie 会话，库里只存 token 哈希 |
| `tasks` | id(uuid), owner_user_id(nullable), guest_token_hash(nullable), client_ip, source_path, source_w, source_h, status, transcript_raw, confirmed_text, transcript_model, final_round_id, created_at, expires_at | 一张原图一个任务 |
| `rounds` | id, task_id, seq, image_model, prompt, strategy(JSON), use_text_hint, status, result_path, result_w, result_h, download_w, download_h, elapsed_s, error, review(JSON), created_at | 每次生成一轮 |
| `jobs` | id, kind(transcribe/generate/review), task_id, round_id, status(queued/running/succeeded/failed), attempts, error, created_at, started_at, finished_at | 执行器队列 |
| `usage_daily` | subject(`user:<id>`/`ip:<addr>`/`guest:global`), date, image_calls, llm_calls | 限额按 `image_calls`（=轮数）计；`llm_calls` 仅统计 |
| `settings` | key, value(JSON), updated_at | 管理页设置，覆盖环境变量默认值 |

`rounds.strategy` 示例：

```json
{"mode": "tiles", "axis": "x", "tiles": [[0,0,1000,1294],[920,0,2316,1294]],
 "seams": [960], "pad_to_3_1": false, "preupscale": 1, "cap": 1550000}
```

`rounds.review` 示例：

```json
{"model": "gpt-6-sol", "transcript": "...",
 "diffs": [{"expected": "亮光", "found": "光光", "sentence": "晚上还会发出亮光呢！"}],
 "suggestions": [{"action": "retry_with_hint", "reason": "...", "diff_ids": [0]}]}
```

**任务状态机**

```
uploaded → transcribing → awaiting_confirm → ready
transcribing → transcribe_failed →(重试 / 手动输入原文 / 跳过)→ ready
ready → generating → reviewing → reviewed →(再来一轮)→ generating …
reviewed →(设为最终版)→ done            generating/reviewing → round_failed →(重试)
```

游客任务：`uploaded → generating → done | round_failed`。

**磁盘布局**：`/data/files/{task_id}/source.png`、`thumb.webp`、`rounds/{seq}/result.png`、`rounds/{seq}/download.png`、`rounds/{seq}/tiles/*`；`/data/db/imgsr.sqlite3`；`/data/backup/`。

**保留期**：登录用户 30 天、游客 24 小时（可在管理页调）；每日清理任务删除过期记录与文件。

## 6. 处理流程与接口

### 6.1 登录用户的一个任务

1. **上传** `POST /api/tasks`（multipart）：校验（§8）→ 统一转 RGB PNG、去 EXIF → 生成缩略图 → 入队 `transcribe`。
2. **① 转写**：`relay.chat.transcribe(model=TRANSCRIBE_MODEL, image)`，流式；结果存 `transcript_raw` → `awaiting_confirm`。
3. **人确认** `PUT /api/tasks/{id}/text {confirmed_text}` → `ready`。也允许空文本（= 不用原文提示）。
4. **② 生成** `POST /api/tasks/{id}/rounds {prompt?, strategy: "auto"|"whole"|"tiles", preupscale?: 1|2, use_text_hint: bool, suggestion?: {round_id, index}}`：
   1. `tiling.plan(source, cap, strategy)` 得到整图或切块方案（§6.3）。
   2. 对每块：如需 3:1 补边则补边；如 `preupscale=2` 则 Lanczos 放大 2 倍。
   3. 若 `use_text_hint`：整图直接用 `confirmed_text`；切块时每块先转写（同一切块几何结果缓存复用），再 `align.slice(confirmed_text, tile_transcript)` 截出该块对应原文。
   4. `prompt.build(base_or_user_prompt, hint)`（§6.4），调用 `relay.images.edit(model=IMAGE_MODEL, image, prompt)`，每块独立重试（§9）。
   5. `compose`：各块缩放到统一倍率 → 在接缝处拼接 → 裁掉补边 → `result.png`（模型原生分辨率）；`download.png` = 若小于原图则 Lanczos 放大到原图尺寸，否则同 `result.png`。
   6. 自动入队 `review`。
5. **③ 审查**：对结果逐块转写（`REVIEW_MODEL`，流式）→ 拼接转写 → `textdiff.compare(confirmed_text, transcript)` → `rules.suggest()`（§6.5）→ 写 `rounds.review` → `reviewed`。`confirmed_text` 为空时跳过比对，只给 `manual_check`（提示人工核对）。
6. **④ 人选择**：勾选建议执行（等价于带对应参数调用 ②），或改提示词/原文后重跑，或定稿。
7. **定稿** `POST /api/tasks/{id}/final {round_id}` → `done`；可改选其他轮次。

### 6.1b 游客任务

`POST /api/guest/tasks`（multipart，可带 `prompt`）：校验 → 检查并扣减 IP 与全站额度 → 入队 `generate`（`strategy=auto`、`use_text_hint=false`、无转写、无审查）→ 完成后 `done`。结果页凭 `guest_token` Cookie 访问；不进入任何历史列表；24 小时后清理。

### 6.2 接口一览

| 用途 | 接口 |
|---|---|
| 健康检查 | `GET /api/health` |
| 认证 | `POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/me` |
| 任务 | `POST /api/tasks`、`GET /api/tasks?cursor=`（仅本人）、`GET /api/tasks/{id}`、`DELETE /api/tasks/{id}` |
| 原文 | `PUT /api/tasks/{id}/text`、`POST /api/tasks/{id}/transcribe`（重试转写） |
| 轮次 | `POST /api/tasks/{id}/rounds`、`POST /api/tasks/{id}/rounds/{seq}/retry`、`POST /api/tasks/{id}/final` |
| 文件 | `GET /api/files/{task_id}/{name}`（校验归属后返回；`name` 白名单：source/thumb/result-{seq}/download-{seq}） |
| 游客 | `POST /api/guest/tasks`（下发 `guest_token` Cookie）、`GET /api/guest/tasks/{id}`、`GET /api/guest/quota` |
| 管理 | `GET/POST/PATCH /api/admin/users`、`GET/PATCH /api/admin/settings` |

进度：有活动任务时前端每 2 s 轮询 `GET /api/tasks/{id}`。

并发：全局上游并发 `UPSTREAM_CONCURRENCY`（默认 3）；每个登录用户同时最多 1 个 generate 任务；游客同一 IP 同时最多 1 个。

### 6.3 切块规则（`pipeline/tiling.py`）

- `cap = PIXEL_CAP`（默认 1,550,000，略低于实测 1.57 MP）。
- `whole`：`W×H ≤ cap` 且宽高比 ≤ 3:1。
- 超限时：沿长边方向找**空白带**（该行/列像素标准差 < 3 且接近背景色，宽度 ≥ 8 px）；按“每块面积 ≤ 0.95·cap、块数最少、接缝尽量均分”贪心选接缝（取空白带中线）；每块范围延伸到相邻空白带边缘形成重叠；拼接时在接缝中线处切换。
- 沿长边切完仍有块超限：对该块在其内部沿另一方向再找空白带切分（最多两层）。
- 找不到合适空白带：退回整图（输出会小于原图，`download.png` 放大回原尺寸），并在轮次上记一条说明。
- 单块宽高比 > 3:1：用边缘中位色补边到 3:1，回来后按比例裁回。
- `preupscale=2`（仅 `tile_refine` 建议或用户手动选择）：每块送入前 Lanczos 放大 2 倍；拼接倍率取各块实际倍率的最小值，向下取到 0.1。

### 6.4 提示词（`pipeline/prompt.py`）

基础提示词（前期实验验证过；用户可在任务页整体编辑）：

> This is a blurry, low-resolution screenshot that contains Chinese text. Restore it into a sharp, clean, high-resolution version of exactly the same image. Keep every Chinese character, punctuation mark, number, letter, emoji, icon, line break and paragraph exactly as in the original; do not add, remove, translate, rephrase, reorder or move anything. Preserve the layout, positions, proportions, borders, boxes, callout bubbles, underlines, buttons, background colors and every text color and weight. Re-render all text with crisp, clean typefaces that match the original styles. No blur, no noise, no JPEG artifacts.

原文提示附加段（`use_text_hint=true` 且有原文时）：

> For reference, the original text contains these exact phrases (keep them character-for-character): 「…」 / 「…」.

按段落拆成短语，用 ` / ` 连接；切块时只放该块对应的原文。

### 6.5 建议规则（`review/rules.py`）

输入：本轮 `diffs`、本轮参数（`use_text_hint`、`strategy`、`preupscale`）、同任务前几轮的 `diffs`。输出：按顺序排列的建议列表，每条含 `action`、`reason`、关联的 `diff_ids`、执行该建议时 ② 的参数。

| 动作 | 触发条件 | 执行参数 |
|---|---|---|
| `accept` | `diffs` 为空 | 设为最终版 |
| `retry_with_hint` | 有差异且本轮未用原文提示 | `use_text_hint=true`，其余沿用 |
| `tile_refine` | 有差异、已用原文提示、未 `preupscale` | `strategy=tiles`、`preupscale=2`、`use_text_hint=true` |
| `manual_check` | 某处差异（按 `expected` 匹配）在连续 ≥ 2 轮出现；或无原文可比对 | 不执行生成；在 UI 中高亮这些句子，提示人工放大核对或接受 |

同一轮可同时给出多条建议；用户也可以忽略建议直接改提示词或原文重跑。

## 7. 前端页面

React + Vite，中文界面，桌面优先、手机可用。

| 路由 | 内容 |
|---|---|
| `/login` | 用户名 + 密码 |
| `/` | 上传区（拖拽/粘贴/选择）+ 最近任务 |
| `/tasks/:id` | 原文确认区 → 轮次条 → 对比查看器 → 审查结果 → 建议与执行 → 定稿/下载 |
| `/history` | 本人任务列表（缩略图、状态、最终版、日期、删除） |
| `/guest` | 上传 → 可选改提示词 → 生成 → 对比 → 下载；显示本 IP 今日剩余次数 |
| `/admin` | 用户管理 + 系统设置（各环节模型、并发、限额、保留期、像素上限） |

**任务页要点**

- 原文确认区：原图（缩放/平移）与转写文本（可编辑）左右并排、同步缩放；醒目提示“模型可能把看不清的字编成通顺的错词，请逐句核对”。
- 轮次条：R1、R2…，缩略图 + 状态 + 差异数；失败轮次可重试。
- 对比查看器：滑块对比 / 左右并排（同步缩放平移）；可选“原图 vs 第 N 轮”或“第 M 轮 vs 第 N 轮”。
- 审查结果：差异列表（应为“…” → 实为“…”，所在句子）。一期不能在图上框出位置；点击差异时复制该句并提示到对比查看器放大查找。
- 建议与执行：建议复选 + “高级”折叠区（编辑提示词、策略、预放大）+「执行下一轮」。
- 下载默认 `download.png`；同时提供模型原生分辨率版本。

## 8. 登录、限流与安全

- 密码 argon2id；会话 Cookie `HttpOnly; Secure; SameSite=Lax`，14 天滑动过期。
- 首个管理员：`uv run imgsr create-user --admin <name>`（交互输入密码）。
- 登录失败：同 IP 15 分钟 10 次后临时锁定。
- CSRF：写操作要求 JSON `Content-Type` 或自定义请求头 + `SameSite`。
- 限额（管理页可调）：游客每 IP 每日 3 次、全站游客每日 100 次；登录用户默认每日 50 次（可逐人设置）。一轮计 1 次（不论切几块）；**排队时扣减，因上游原因整体失败时退回**。
- 真实 IP：仅信任来自可信代理的头。`CLIENT_IP_HEADER`（`X-Forwarded-For` 或 `CF-Connecting-IP`）与 `TRUSTED_PROXIES` 可配；部署时从外部检查响应头（是否有 `cf-ray`）确定。
- 上传：仅 PNG/JPG/WebP，≤ 15 MB，≤ 25 MP；设置 `Image.MAX_IMAGE_PIXELS`；统一重编码为 PNG、去 EXIF；文件名用 UUID；文件接口校验归属，不开放目录。
- 密钥：`OPEN_API_KEY` 仅在服务器 `.env`；不进仓库、不下发前端；日志只记脱敏形式（`sk-8b1…af8e`）。
- HTTPS 由上游反代终止；容器只监听 `127.0.0.1`。

## 9. 错误处理

| 情况 | 处理 |
|---|---|
| 上游 429 / 503（限流、无可用账号） | 退避重试 2 次（10 s、30 s）；仍失败 → 轮次失败，提示“上游繁忙”，退回额度 |
| 5xx / 524 / 超时 / 空结果 | 重试 2 次（生图可能已被受理，次数从严）；仍失败同上 |
| 400（内容审核、图片不合规） | 不重试，展示原因 |
| 切块中某块失败 | 该块独立重试；最终仍失败则整轮失败（一期不做半成品拼接） |
| 转写失败 | 任务进入 `transcribe_failed`；可重试、手动输入原文或跳过 |
| 服务重启 | 启动时将 `running` 任务置 `failed`（原因“服务重启”），`queued` 任务重新入队 |
| 磁盘剩余 < 1 GB | 拒绝新上传，健康检查告警 |

超时：生图单次 180 s；转写流式整体 240 s。日志为结构化 JSON 输出到 stdout，每个任务记录模型、耗时、尺寸、状态；不记录密钥与图片数据。

## 10. 测试

按 TDD 推进（红 → 绿 → 重构）。

- **pipeline 单元测试**（主体）：空白带检测与切块（合成图）、像素上限、3:1 补边与裁回、拼接接缝与尺寸、下载版尺寸规则、提示词拼装、`textdiff` 归一化（全/半角标点、空白）与中文差异聚合、`align` 截取、`rules` 表驱动。
- **relay**：`httpx.MockTransport` 覆盖重试与退避、错误分类、SSE 流式解析、`b64_json`/`url`（含网关相对路径）两种返回。
- **API**：TestClient + 临时 SQLite + 假 relay：登录与会话、A 用户访问 B 的任务/文件被拒、guest token、IP 限额与全站上限、失败退额、上传校验（类型/大小/像素）、状态机与重启恢复。
- **前端**：关键组件 Vitest；Playwright 端到端冒烟（假 relay）：上传 → 确认原文 → 生成 → 审查 → 定稿 → 下载。
- **真实上游回归**（手动脚本，不进 CI，会产生费用）：用样张 图片1/2/9/14/17 跑真实流程，输出逐字比对报告与耗时。

## 11. 部署

- `Dockerfile`：多阶段（Node 构建前端 → uv 安装 Python 依赖的运行镜像），非 root 运行。
- `docker-compose.yml`：单服务；`127.0.0.1:${HOST_PORT:-18090}:8000`；`./data:/data`；`env_file: .env`；`restart: unless-stopped`；健康检查 `/api/health`。
- `scripts/deploy.sh`（Mac 上执行）：`rsync` 代码到服务器（排除 `data/`、`.env`、`node_modules/`）→ ssh 执行 `docker compose up -d --build` → 轮询健康检查。仓库暂无远端，后续建远端后可改为 `git pull`。
- 备份：每日 SQLite `.backup` 到 `/data/backup/`，保留 7 份；图片文件有保留期，不额外备份。
- 域名：`imgsr.huanmeng.cc` → 服务器。DNS 变更为对外操作，执行前单独确认。
- 反代：在服务器现有反代加一条到容器的路由。读取/修改该反代配置需用户届时**点名授权**；否则提供配置片段由用户自行添加。
- 部署前验证：服务器到 `your-relay.example.com` 的出站连通性（未验证）。

## 12. 配置项

| 变量 | 默认 | 说明 |
|---|---|---|
| `OPEN_API_BASE_URL` | `https://your-relay.example.com` | 中转站地址（可带 `/v1`） |
| `OPEN_API_KEY` | — | OpenAI 分组用户 key（必填） |
| `IMAGE_MODEL` | `gpt-image-2.5` | ② 生成 |
| `TRANSCRIBE_MODEL` | `gpt-6-sol` | ① 转写 |
| `REVIEW_MODEL` | `gpt-6-sol` | ③ 审查转写 |
| `PIXEL_CAP` | `1550000` | 单次输出像素上限 |
| `UPSTREAM_CONCURRENCY` | `3` | 全局上游并发 |
| `HOST_PORT` | `18090` | 宿主机监听端口（仅 127.0.0.1） |
| `GUEST_DAILY_PER_IP` / `GUEST_DAILY_GLOBAL` | `3` / `100` | 游客限额 |
| `USER_DAILY_DEFAULT` | `50` | 新用户默认日限额 |
| `RETENTION_USER_DAYS` / `RETENTION_GUEST_HOURS` | `30` / `24` | 保留期 |
| `MAX_UPLOAD_MB` / `MAX_PIXELS` | `15` / `25000000` | 上传限制 |
| `SESSION_DAYS` / `COOKIE_SECURE` | `14` / `true` | 会话 |
| `CLIENT_IP_HEADER` / `TRUSTED_PROXIES` | `X-Forwarded-For` / `127.0.0.1,172.16.0.0/12` | 真实 IP |
| `DATA_DIR` | `/data` | 数据目录 |

除密钥与目录外，其余均可在管理页覆盖（存 `settings` 表）。

## 13. 风险与未决

1. **中转站行为会变**：像素上限、质量档、模型可用性均为实测而非契约；`PIXEL_CAP` 与模型名可配，并保留真实上游回归脚本。
2. **转写幻觉**：`gpt-6-sol` 在模糊图上会编出通顺错词；若人确认时漏看，错误会被“忠实”画出。缓解：并排同步缩放 + 提示文案；管理页可切到 `gpt-5.5`。
3. **审查漏检形近字**（耍/要）：审查只作提示；最终靠人对比。二期考虑带坐标 OCR 与字形修补。
4. **成本**：每轮上游调用 ≈ 块数 ×（1 次生图 + 1 次审查转写）+ 切块原文对齐时的块转写（可缓存）。由限额与全站游客上限兜底。
5. **延迟**：`gpt-6-sol` 每次转写 20–60 s，加上生图 15–45 s；单轮可能 1–3 分钟。界面需清晰展示阶段与等待。
6. **服务器未知项**：反代类型与配置、是否经 CDN、出站连通性——部署阶段在授权范围内确认。

## 14. 验收标准

1. 用样张 图片1、图片9 走完登录用户全流程（真实上游），轮次、差异、建议正确展示；定稿可下载。
2. 图片17（3.0 MP）自动切块，`download.png` 尺寸 = 原图尺寸，接缝两侧 30 px 带内平均色差 < 3。
3. 图片14（4:1）补边后生成，结果无拉伸，宽高比与原图误差 ≤ 1%。
4. 同一 IP 当日第 4 次游客请求返回 429 与中文提示；全站游客上限生效；上游失败时额度退回。
5. 用户 A 无法读取用户 B 的任务与文件（404）。
6. 任务运行中重启容器：该任务标记失败，点击重试可成功完成。
7. 部署到 `https://imgsr.huanmeng.cc`：健康检查通过；游客限流使用的是真实客户端 IP。
8. 仓库与日志中不出现密钥明文。
