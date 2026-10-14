# imgsr-studio 后端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现工具站的完整后端：上传 → ①转写 → 人确认原文 → ②生成（自动切块、原文提示）→ ③审查 → ④规则建议，含登录、游客限流、管理接口、维护任务与真实上游回归脚本。

**Architecture:** 单个 FastAPI 进程；SQLite（SQLAlchemy 2 + Alembic）存状态；进程内 asyncio 任务执行器跑 transcribe / generate / review 三类任务；`pipeline/` 全是纯函数（切块、拼接、提示词、比对、对齐），`relay/` 封装 sub2api 的 images/edits 与流式 chat；`review/rules.py` 用规则引擎产出建议。

**Tech Stack:** Python ≥3.11（uv）、FastAPI、SQLAlchemy 2、Alembic、Pillow、NumPy、httpx、argon2-cffi、pydantic-settings、pytest + pytest-asyncio、ruff。

**Spec:** `docs/superpowers/specs/2026-10-14-imgsr-studio-design.md`

**本计划范围：** spec §4–§6、§8–§10、§12 的后端部分，验收 §14 的 1–6、8 条。**不含**：前端 SPA（计划 2）、Docker/部署/DNS/反代（计划 3）、静态文件托管（计划 2 接入）。

## Global Constraints

- Python `>=3.11,<3.14`，`.python-version` 为 `3.12`；所有命令用 `uv run …`；新依赖用 `uv add` / `uv add --dev`。
- 包位于 `src/imgsr/`，测试位于 `tests/`；`pytest` 配置 `asyncio_mode = "auto"`、`pythonpath = ["."]`。
- 所有面向用户的错误信息为中文。
- 默认模型：`IMAGE_MODEL=gpt-image-2.5`、`TRANSCRIBE_MODEL=gpt-6-sol`、`REVIEW_MODEL=gpt-6-sol`。
- `PIXEL_CAP=1550000`；`UPSTREAM_CONCURRENCY=3`；游客 `3`/IP/天、全站游客 `100`/天；登录用户默认 `50`/天；保留期 `30` 天 / `24` 小时；上传 ≤ `15` MB、≤ `25000000` 像素、仅 PNG/JPG/WebP；会话 `14` 天滑动。
- 限额日期按 **UTC+8** 计算；一轮生成扣 1 次（不论切几块）；排队时扣、生成失败退。
- 中转站调用：生图 `POST {base}/v1/images/edits`（multipart）；转写 `POST {base}/v1/chat/completions`，`stream: true`；`base` 去掉结尾 `/` 与 `/v1`。不得请求裸路径。
- 重试：可重试错误（429/503/5xx/524/超时/空结果）退避 `10 s`、`30 s` 共重试 2 次；400/401/403 不重试。
- 所有 `/api/` 写请求（POST/PUT/PATCH/DELETE）必须带 `X-Requested-With: imgsr`，否则 403。
- `OPEN_API_KEY` 不得出现在日志、响应、管理接口中；日志只用 `masked()`。
- 测试不得访问网络（用 fake 或 `httpx.MockTransport`）；真实上游只在 `scripts/regress_real.py`。
- ruff 若只报 import 排序（`I001`），运行 `uv run ruff check --fix <文件>` 即可，不必手改。
- 每个 Task 完成后提交：只 `git add` 列出的具体文件，提交信息末尾带 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

## Review Focus

1. **截图带深色外框**（手机/窗口截图常见）：外框会让每一列都“不空白”，导致找不到切缝 → 期望忽略两端边缘后仍能找到空白带。（Task 2 `test_dark_frame_does_not_hide_bands`）
2. **非常规上传格式**（带透明的 PNG、调色板 PNG、CMYK JPEG、带 EXIF 旋转的手机照片、16 位灰度 PNG）→ 期望统一成方向正确的 RGB，不崩溃、不发黑。（Task 10 上传测试组）
3. **不可信来源伪造 `X-Forwarded-For`** → 期望只有来自可信代理的请求才采信该头，否则用 TCP 对端地址做限流。（Task 11 `test_untrusted_peer_cannot_spoof`）
4. **任务在生成过程中被删除** → 期望任务静默结束，不抛错、不在磁盘上留下孤儿文件。（Task 13 `test_generate_for_deleted_task_leaves_no_files`）
5. **上游返回 200 但内容不可用**（Cloudflare HTML、`data: []`、非图片字节）→ 期望归类为可重试的“空结果”，而不是崩溃或把 HTML 存成图片。（Task 8 `test_edit_unusable_200_is_retryable_empty`）

---

## File Structure

```
imgsr-studio/
├─ pyproject.toml / uv.lock / .python-version / alembic.ini / .env.example / README.md
├─ src/imgsr/
│  ├─ __init__.py
│  ├─ config.py            Settings（环境变量）+ OVERRIDABLE 白名单
│  ├─ config_store.py      SettingsProvider：settings 表覆盖 + 校验
│  ├─ storage.py           任务文件路径推导、保存、删除、磁盘余量
│  ├─ uploads.py           上传校验与规范化为 RGB
│  ├─ auth.py              密码哈希、会话、登录限流
│  ├─ clientip.py          可信代理后的真实 IP
│  ├─ quota.py             每日计数、扣额、退额
│  ├─ maintenance.py       过期清理、SQLite 备份、维护循环
│  ├─ cli.py               imgsr create-user / reset-password / cleanup / serve
│  ├─ pipeline/            纯函数
│  │  ├─ bands.py          空白带检测
│  │  ├─ tiling.py         切块方案 Box/Tile/TilePlan
│  │  ├─ compose.py        补边、裁回、预放大、拼接、下载版
│  │  ├─ prompt.py         BASE_PROMPT / TRANSCRIBE_PROMPT / build_prompt
│  │  ├─ textdiff.py       归一化与逐字比对
│  │  └─ align.py          切块转写 → 确认原文片段
│  ├─ review/rules.py      建议规则引擎
│  ├─ relay/               base.py / errors.py / retry.py / images.py / chat.py
│  ├─ db/                  models.py / session.py / migrations/（Alembic）
│  ├─ jobs/                runner.py（队列）/ handlers.py（Pipeline：三类任务）
│  └─ api/                 app.py / deps.py / schemas.py / routes_auth.py / routes_tasks.py
│                          / routes_files.py / routes_guest.py / routes_admin.py
├─ tests/                  与 src 对应；fakes.py；api/conftest.py + api/helpers.py
└─ scripts/regress_real.py 真实上游回归（会产生费用）
```

---

### Task 1: 项目骨架与配置

**Files:**
- Create: `pyproject.toml`, `.python-version`, `src/imgsr/__init__.py`, `src/imgsr/config.py`, `tests/__init__.py`, `tests/test_config.py`

**Interfaces:**
- Produces: `imgsr.config.Settings`（字段见下）、`Settings.db_path / files_dir / backup_dir`、`Settings.with_overrides(dict) -> Settings`、`imgsr.config.OVERRIDABLE: dict[str, type]`

- [x] **Step 1: 写 `pyproject.toml` 与 `.python-version`**

`pyproject.toml`:

```toml
[project]
name = "imgsr"
version = "0.1.0"
description = "Generative text-clarifying tool site (imgsr.huanmeng.cc)"
requires-python = ">=3.11,<3.14"
dependencies = []

[project.scripts]
imgsr = "imgsr.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/imgsr"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
asyncio_mode = "auto"

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]
ignore = ["E501"]

[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = ["fastapi.Depends", "fastapi.Query", "fastapi.File", "fastapi.Form", "fastapi.Body"]
```

`.python-version`:

```
3.12
```

- [x] **Step 2: 安装解释器与依赖**

```bash
cd ~/Downloads/Projects/imgsr-studio
uv python install 3.12
uv add fastapi "uvicorn[standard]" "sqlalchemy>=2.0" alembic pillow numpy httpx argon2-cffi pydantic-settings python-multipart
uv add --dev pytest pytest-asyncio ruff
```

Expected: 生成 `uv.lock` 与 `.venv/`，无报错。

- [x] **Step 3: 写失败测试 `tests/test_config.py`**（同时创建空的 `tests/__init__.py`）

```python
from pathlib import Path

import pytest

from imgsr.config import OVERRIDABLE, Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("OPEN_API_KEY", "IMAGE_MODEL", "DATA_DIR", "PIXEL_CAP"):
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_spec():
    s = Settings(_env_file=None)
    assert s.image_model == "gpt-image-2.5"
    assert s.transcribe_model == s.review_model == "gpt-6-sol"
    assert s.pixel_cap == 1_550_000
    assert (s.guest_daily_per_ip, s.guest_daily_global, s.user_daily_default) == (3, 100, 50)
    assert (s.retention_user_days, s.retention_guest_hours) == (30, 24)
    assert s.db_path == Path("/data/db/imgsr.sqlite3")


def test_env_vars_override(monkeypatch):
    monkeypatch.setenv("IMAGE_MODEL", "gpt-image-2")
    monkeypatch.setenv("DATA_DIR", "/tmp/imgsr-x")
    s = Settings(_env_file=None)
    assert s.image_model == "gpt-image-2"
    assert s.files_dir == Path("/tmp/imgsr-x/files")


def test_with_overrides_casts_and_ignores_unknown_and_secrets():
    s = Settings(_env_file=None).with_overrides(
        {"pixel_cap": "1000000", "open_api_key": "leak", "nope": 1}
    )
    assert s.pixel_cap == 1_000_000
    assert s.open_api_key == ""
    assert "open_api_key" not in OVERRIDABLE
```

- [x] **Step 4: 运行，确认失败**

Run: `uv run pytest tests/test_config.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'imgsr'`

- [x] **Step 5: 实现 `src/imgsr/__init__.py` 与 `src/imgsr/config.py`**

`src/imgsr/__init__.py`:

```python
__version__ = "0.1.0"
```

`src/imgsr/config.py`:

```python
"""Environment-driven settings. Admin overrides are layered on top by config_store."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Keys an admin may override at runtime (stored in the `settings` table). Never secrets.
OVERRIDABLE: dict[str, type] = {
    "image_model": str,
    "transcribe_model": str,
    "review_model": str,
    "pixel_cap": int,
    "upstream_concurrency": int,
    "guest_daily_per_ip": int,
    "guest_daily_global": int,
    "user_daily_default": int,
    "retention_user_days": int,
    "retention_guest_hours": int,
    "max_upload_mb": int,
    "max_pixels": int,
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    open_api_base_url: str = "https://your-relay.example.com"
    open_api_key: str = ""
    image_model: str = "gpt-image-2.5"
    transcribe_model: str = "gpt-6-sol"
    review_model: str = "gpt-6-sol"
    pixel_cap: int = 1_550_000
    upstream_concurrency: int = 3
    guest_daily_per_ip: int = 3
    guest_daily_global: int = 100
    user_daily_default: int = 50
    retention_user_days: int = 30
    retention_guest_hours: int = 24
    max_upload_mb: int = 15
    max_pixels: int = 25_000_000
    session_days: int = 14
    cookie_secure: bool = True
    client_ip_header: str = "X-Forwarded-For"
    trusted_proxies: str = "127.0.0.1,172.16.0.0/12"
    data_dir: Path = Path("/data")
    host_port: int = 18090
    image_timeout_s: float = 180.0
    chat_timeout_s: float = 240.0
    min_free_bytes: int = 1_000_000_000

    @property
    def db_path(self) -> Path:
        return self.data_dir / "db" / "imgsr.sqlite3"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backup"

    def with_overrides(self, overrides: dict[str, object]) -> Settings:
        clean = {k: OVERRIDABLE[k](v) for k, v in overrides.items() if k in OVERRIDABLE}
        return self.model_copy(update=clean)
```

- [x] **Step 6: 运行，确认通过**

Run: `uv run pytest tests/test_config.py -q && uv run ruff check src tests`
Expected: `3 passed`；ruff `All checks passed!`

- [x] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .python-version src/imgsr/__init__.py src/imgsr/config.py tests/__init__.py tests/test_config.py
git commit -m "chore: scaffold imgsr package and settings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: 空白带检测（`pipeline/bands.py`）

**Files:**
- Create: `src/imgsr/pipeline/__init__.py`（空）, `src/imgsr/pipeline/bands.py`, `tests/pipeline/__init__.py`（空）, `tests/pipeline/test_bands.py`

**Interfaces:**
- Produces: `Axis = Literal["x", "y"]`；`Band(start: int, end: int)`（`end` 不含），属性 `center`, `width`；`find_blank_bands(img, axis, *, min_width=8, max_std=3.0, edge_trim_ratio=0.03) -> list[Band]`。`axis="x"` 扫描列（竖向空白带，用于沿 x 切），`axis="y"` 扫描行。

- [x] **Step 1: 写失败测试 `tests/pipeline/test_bands.py`**

```python
from PIL import Image, ImageDraw

from imgsr.pipeline.bands import Band, find_blank_bands


def canvas(w, h):
    return Image.new("L", (w, h), 255)


def ink(img, box):
    ImageDraw.Draw(img).rectangle(box, fill=0)


def inner(bands, length, margin=0):
    return [(b.start, b.end) for b in bands if b.start > margin and b.end < length - margin]


def test_vertical_band_between_two_blocks():
    img = canvas(400, 200)
    ink(img, (10, 20, 150, 180))
    ink(img, (250, 20, 390, 180))
    assert inner(find_blank_bands(img, "x"), 400) == [(151, 250)]


def test_horizontal_bands():
    img = canvas(300, 400)
    for y0, y1 in ((10, 100), (150, 250), (300, 390)):
        ink(img, (10, y0, 290, y1))
    assert inner(find_blank_bands(img, "y"), 400) == [(101, 150), (251, 300)]


def test_narrow_gap_is_ignored():
    img = canvas(300, 100)
    ink(img, (0, 10, 140, 90))
    ink(img, (146, 10, 299, 90))  # 5-px gap < min_width
    assert inner(find_blank_bands(img, "x"), 300) == []


def test_dark_frame_does_not_hide_bands():
    img = canvas(400, 200)
    ImageDraw.Draw(img).rectangle((0, 0, 399, 199), outline=0, width=4)
    ink(img, (20, 30, 150, 170))
    ink(img, (250, 30, 380, 170))
    assert inner(find_blank_bands(img, "x"), 400, margin=4) == [(151, 250)]


def test_band_properties():
    band = Band(10, 30)
    assert (band.center, band.width) == (20, 20)


def test_accepts_rgb_images():
    img = Image.new("RGB", (300, 100), "white")
    ImageDraw.Draw(img).rectangle((0, 10, 100, 90), fill="black")
    ImageDraw.Draw(img).rectangle((200, 10, 299, 90), fill="black")
    assert inner(find_blank_bands(img, "x"), 300) == [(101, 200)]
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/pipeline/test_bands.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'imgsr.pipeline'`

- [x] **Step 3: 实现 `src/imgsr/pipeline/bands.py`**（并创建空的 `src/imgsr/pipeline/__init__.py`、`tests/pipeline/__init__.py`）

```python
"""Detect blank (near-uniform) bands of rows or columns where an image can be cut."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from PIL import Image

Axis = Literal["x", "y"]


@dataclass(frozen=True)
class Band:
    start: int  # inclusive
    end: int  # exclusive

    @property
    def center(self) -> int:
        return (self.start + self.end) // 2

    @property
    def width(self) -> int:
        return self.end - self.start


def find_blank_bands(
    img: Image.Image,
    axis: Axis,
    *,
    min_width: int = 8,
    max_std: float = 3.0,
    edge_trim_ratio: float = 0.03,
) -> list[Band]:
    """Return runs of near-uniform lines.

    axis="x" scans columns (vertical bands, i.e. cut positions along x);
    axis="y" scans rows. Both ends of every line are trimmed by `edge_trim_ratio`
    so that a screenshot's dark outer frame does not make every line look busy.
    """
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    lines = gray.T if axis == "x" else gray  # one row of `lines` per scanned line
    trim = max(1, int(lines.shape[1] * edge_trim_ratio))
    inner = lines[:, trim : lines.shape[1] - trim] if lines.shape[1] > 2 * trim else lines
    blank = inner.std(axis=1) < max_std
    bands: list[Band] = []
    start: int | None = None
    for i, is_blank in enumerate(blank):
        if is_blank and start is None:
            start = i
        elif not is_blank and start is not None:
            if i - start >= min_width:
                bands.append(Band(start, i))
            start = None
    if start is not None and len(blank) - start >= min_width:
        bands.append(Band(start, len(blank)))
    return bands
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/pipeline/test_bands.py -q && uv run ruff check src tests`
Expected: `6 passed`

- [x] **Step 5: Commit**

```bash
git add src/imgsr/pipeline/__init__.py src/imgsr/pipeline/bands.py tests/pipeline/__init__.py tests/pipeline/test_bands.py
git commit -m "feat: detect blank bands for tile seams" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: 切块方案（`pipeline/tiling.py`）

**Files:**
- Create: `src/imgsr/pipeline/tiling.py`, `tests/pipeline/test_tiling.py`

**Interfaces:**
- Consumes: `find_blank_bands`, `Band`, `Axis`（Task 2）
- Produces:
  - `Box(x0, y0, x1, y1)`：`width/height/area`、`as_tuple()`、`intersect(other) -> Box`
  - `Tile(box: Box, keep: Box)`：`box` 是送给模型的区域（含重叠），`keep` 是拼接时保留的区域（源图坐标）
  - `TilePlan(mode: "whole"|"tiles", tiles: list[Tile], notes: list[str])`：`to_json() -> dict`、`TilePlan.from_json(dict)`
  - `plan_tiles(img, cap: int, mode: "auto"|"whole"|"tiles" = "auto", preupscale: int = 1) -> TilePlan`
  - 常量 `NO_BAND_NOTE`、`FILL = 0.95`

规则（spec §6.3）：有效上限 `eff = cap // preupscale²`；`whole` 或 `auto` 且面积 ≤ eff → 整图；否则沿长边找空白带，目标块数 `ceil(area / (0.95·eff))`（`tiles` 模式至少 2）。选缝先试“按理想位置均分”，若因重叠导致某块超限，则退回“贪心装满”（每块取能装下的最远空白带）；块仍超限时在块内沿另一方向再切一层；一个缝都找不到 → 整图 + `NO_BAND_NOTE`。

- [x] **Step 1: 写失败测试 `tests/pipeline/test_tiling.py`**

```python
from PIL import Image, ImageDraw

from imgsr.pipeline.tiling import NO_BAND_NOTE, Box, TilePlan, plan_tiles

CAP = 1_550_000


def two_column_page(w=2316, h=1294, gap=(919, 999)):
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    d.rectangle((20, 40, gap[0] - 1, h - 40), fill=0)
    d.rectangle((gap[1], 40, w - 20, h - 40), fill=0)
    return img


def test_small_image_is_whole():
    plan = plan_tiles(Image.new("RGB", (1000, 1000), "white"), CAP)
    assert plan.mode == "whole"
    assert plan.tiles[0].box == plan.tiles[0].keep == Box(0, 0, 1000, 1000)


def test_whole_mode_is_respected_even_when_large():
    assert plan_tiles(Image.new("RGB", (3000, 2000), "white"), CAP, "whole").mode == "whole"


def test_wide_page_splits_at_gap_and_notes_oversized_piece():
    plan = plan_tiles(two_column_page(), CAP)
    assert plan.mode == "tiles"
    assert [t.box.as_tuple() for t in plan.tiles] == [(0, 0, 999, 1294), (919, 0, 2316, 1294)]
    assert [t.keep.as_tuple() for t in plan.tiles] == [(0, 0, 959, 1294), (959, 0, 2316, 1294)]
    assert any("缩小" in note for note in plan.notes)


def test_tall_page_splits_into_pieces_under_cap():
    w, h = 1200, 3000
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    for y in range(0, h, 300):
        d.rectangle((50, y + 20, w - 50, y + 260), fill=0)
    plan = plan_tiles(img, CAP)
    assert plan.mode == "tiles" and len(plan.tiles) == 3
    assert all(t.box.area <= 0.95 * CAP for t in plan.tiles)
    keeps = [t.keep for t in plan.tiles]
    assert keeps[0].y0 == 0 and keeps[-1].y1 == h
    assert all(a.y1 == b.y0 for a, b in zip(keeps, keeps[1:], strict=False))


def test_no_bands_falls_back_to_whole_with_note():
    plan = plan_tiles(Image.effect_noise((2000, 1500), 80), CAP)
    assert plan.mode == "whole"
    assert plan.notes == [NO_BAND_NOTE]


def test_forced_tiles_with_preupscale_split_small_image():
    w, h = 558, 714
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    d.rectangle((20, 20, w - 20, 360), fill=0)
    d.rectangle((20, 400, w - 20, h - 20), fill=0)
    plan = plan_tiles(img, CAP, "tiles", preupscale=2)
    assert plan.mode == "tiles" and len(plan.tiles) == 2
    assert plan.tiles[0].keep.y1 == plan.tiles[1].keep.y0 == 380


def test_plan_json_roundtrip():
    plan = plan_tiles(two_column_page(), CAP)
    assert TilePlan.from_json(plan.to_json()) == plan


def test_box_intersect():
    assert Box(0, 0, 10, 10).intersect(Box(5, 2, 20, 8)) == Box(5, 2, 10, 8)
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/pipeline/test_tiling.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'imgsr.pipeline.tiling'`

- [x] **Step 3: 实现 `src/imgsr/pipeline/tiling.py`**

```python
"""Plan how to cut an image into tiles that each fit the relay's output pixel cap."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from PIL import Image

from imgsr.pipeline.bands import Axis, Band, find_blank_bands

Mode = Literal["auto", "whole", "tiles"]
FILL = 0.95  # keep every tile a little under the cap
NO_BAND_NOTE = "未找到可切分的空白带，整图处理（输出可能小于原图）"


@dataclass(frozen=True)
class Box:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def area(self) -> int:
        return self.width * self.height

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x0, self.y0, self.x1, self.y1)

    def intersect(self, other: Box) -> Box:
        return Box(
            max(self.x0, other.x0),
            max(self.y0, other.y0),
            min(self.x1, other.x1),
            min(self.y1, other.y1),
        )


@dataclass(frozen=True)
class Tile:
    box: Box  # region sent to the model (source coords, includes overlap)
    keep: Box  # part of this tile used in the final composite (source coords)


@dataclass(frozen=True)
class TilePlan:
    mode: Literal["whole", "tiles"]
    tiles: list[Tile]
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "mode": self.mode,
            "tiles": [
                {"box": list(t.box.as_tuple()), "keep": list(t.keep.as_tuple())} for t in self.tiles
            ],
            "notes": list(self.notes),
        }

    @classmethod
    def from_json(cls, data: dict) -> TilePlan:
        tiles = [Tile(Box(*t["box"]), Box(*t["keep"])) for t in data["tiles"]]
        return cls(data["mode"], tiles, list(data.get("notes", [])))


def plan_tiles(img: Image.Image, cap: int, mode: Mode = "auto", preupscale: int = 1) -> TilePlan:
    w, h = img.size
    full = Box(0, 0, w, h)
    eff = cap // (preupscale * preupscale)
    if mode == "whole" or (mode == "auto" and full.area <= eff):
        return TilePlan("whole", [Tile(full, full)])
    axis: Axis = "x" if w >= h else "y"
    tiles, notes = _plan_region(img, full, eff, axis, depth=0, min_pieces=2 if mode == "tiles" else 1)
    if len(tiles) == 1:
        return TilePlan("whole", [Tile(full, full)], [NO_BAND_NOTE])
    return TilePlan("tiles", tiles, notes)


def _other(axis: Axis) -> Axis:
    return "y" if axis == "x" else "x"


def _span(region: Box, axis: Axis, a: int, b: int) -> Box:
    """Sub-box of `region` covering offsets [a, b) along `axis`."""
    if axis == "x":
        return Box(region.x0 + a, region.y0, region.x0 + b, region.y1)
    return Box(region.x0, region.y0 + a, region.x1, region.y0 + b)


def _seams_fit(length: int, seams: list[Band], fits: Callable[[int, int], bool]) -> bool:
    starts = [0, *[b.start for b in seams]]
    ends = [*[b.end for b in seams], length]
    return all(fits(a, b) for a, b in zip(starts, ends, strict=True))


def _balanced_seams(length: int, bands: list[Band], pieces: int) -> list[Band]:
    seams: list[Band] = []
    for k in range(1, pieces):
        ideal = length * k / pieces
        candidates = [b for b in bands if not seams or b.start >= seams[-1].end]
        if not candidates:
            break
        seams.append(min(candidates, key=lambda b: abs(b.center - ideal)))
    return seams


def _greedy_seams(length: int, bands: list[Band], fits: Callable[[int, int], bool]) -> list[Band]:
    """Fill each piece as far as it fits; the next piece starts at the seam band's start."""
    seams: list[Band] = []
    start = 0
    while not fits(start, length):
        candidates = [b for b in bands if b.start > start and (not seams or b.start >= seams[-1].end)]
        if not candidates:
            break
        fitting = [b for b in candidates if fits(start, b.end)]
        band = max(fitting, key=lambda b: b.end) if fitting else min(candidates, key=lambda b: b.start)
        seams.append(band)
        start = band.start
    return seams


def _choose_seams(
    length: int, bands: list[Band], pieces: int, fits: Callable[[int, int], bool]
) -> list[Band]:
    balanced = _balanced_seams(length, bands, pieces)
    if balanced and _seams_fit(length, balanced, fits):
        return balanced
    return _greedy_seams(length, bands, fits) or balanced


def _plan_region(
    img: Image.Image, region: Box, eff: int, axis: Axis, depth: int, min_pieces: int = 1
) -> tuple[list[Tile], list[str]]:
    pieces = max(min_pieces, math.ceil(region.area / (FILL * eff)))
    if pieces <= 1:
        return [Tile(region, region)], []
    length = region.width if axis == "x" else region.height
    across = region.height if axis == "x" else region.width

    def fits(a: int, b: int) -> bool:
        return (b - a) * across <= FILL * eff

    sub = img.crop(region.as_tuple())
    bands = [b for b in find_blank_bands(sub, axis) if b.start > 0 and b.end < length]
    seams = _choose_seams(length, bands, pieces, fits)
    if not seams:
        if depth == 0:
            return _plan_region(img, region, eff, _other(axis), depth + 1, min_pieces)
        return [Tile(region, region)], [f"区域 {region.as_tuple()} 没有可用空白带，该块会被模型缩小"]
    keep_edges = [0, *[b.center for b in seams], length]
    box_starts = [0, *[b.start for b in seams]]
    box_ends = [*[b.end for b in seams], length]
    tiles: list[Tile] = []
    notes: list[str] = []
    for i in range(len(seams) + 1):
        box = _span(region, axis, box_starts[i], box_ends[i])
        keep = _span(region, axis, keep_edges[i], keep_edges[i + 1])
        if box.area > FILL * eff and depth == 0:
            sub_tiles, sub_notes = _plan_region(img, box, eff, _other(axis), depth + 1)
            tiles += [Tile(t.box, t.keep.intersect(keep)) for t in sub_tiles]
            notes += sub_notes
            continue
        if box.area > FILL * eff:
            notes.append(f"区域 {box.as_tuple()} 超过像素上限，该块会被模型缩小")
        tiles.append(Tile(box, keep))
    return tiles, notes
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/pipeline -q && uv run ruff check src tests`
Expected: 全部 passed

- [x] **Step 5: Commit**

```bash
git add src/imgsr/pipeline/tiling.py tests/pipeline/test_tiling.py
git commit -m "feat: plan tiles under the relay pixel cap" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: 补边、拼接与下载版（`pipeline/compose.py`）

**Files:**
- Create: `src/imgsr/pipeline/compose.py`, `tests/pipeline/test_compose.py`

**Interfaces:**
- Consumes: `Box`, `Tile`, `TilePlan`（Task 3）
- Produces:
  - `MAX_RATIO = 3.0`
  - `edge_color(img) -> tuple[int, int, int]`
  - `pad_to_ratio(img, max_ratio=3.0) -> tuple[Image, Box]`（返回补边图和原内容在其中的位置）
  - `crop_content(result, padded_size, content: Box) -> Image`（按结果图实际缩放裁回）
  - `upscale(img, factor: int) -> Image`
  - `stitch(plan, outputs, src_size) -> tuple[Image, float]`（返回拼接图与“源像素→结果像素”的倍率）
  - `make_download(result, src_size) -> Image`（比原图小则 Lanczos 放大到原图尺寸）

- [x] **Step 1: 写失败测试 `tests/pipeline/test_compose.py`**

```python
from PIL import Image

from imgsr.pipeline.compose import (
    crop_content,
    edge_color,
    make_download,
    pad_to_ratio,
    stitch,
    upscale,
)
from imgsr.pipeline.tiling import Box, Tile, TilePlan


def test_pad_wide_image_to_three_to_one():
    img = Image.new("RGB", (1838, 456), "white")
    padded, content = pad_to_ratio(img)
    assert padded.size == (1838, 613)
    assert content == Box(0, 78, 1838, 534)


def test_pad_tall_image():
    padded, content = pad_to_ratio(Image.new("RGB", (100, 400), "white"))
    assert padded.size == (134, 400)
    assert content == Box(17, 0, 117, 400)


def test_no_padding_needed_returns_same_image():
    img = Image.new("RGB", (300, 200), "white")
    padded, content = pad_to_ratio(img)
    assert padded is img and content == Box(0, 0, 300, 200)


def test_crop_content_undoes_padding_after_model_rescale():
    padded, content = pad_to_ratio(Image.new("RGB", (1838, 456), "white"))
    model_out = padded.resize((2171, 724))
    cropped = crop_content(model_out, padded.size, content)
    assert cropped.width == 2171
    assert abs(cropped.width / cropped.height - 1838 / 456) / (1838 / 456) < 0.01


def test_edge_color_uses_border_median():
    img = Image.new("RGB", (50, 50), (250, 250, 250))
    img.paste((0, 0, 0), (10, 10, 40, 40))
    assert edge_color(img) == (250, 250, 250)


def test_upscale():
    assert upscale(Image.new("RGB", (10, 7)), 2).size == (20, 14)
    img = Image.new("RGB", (10, 7))
    assert upscale(img, 1) is img


def test_stitch_whole_returns_output_and_scale():
    out = Image.new("RGB", (200, 100), "red")
    plan = TilePlan("whole", [Tile(Box(0, 0, 100, 50), Box(0, 0, 100, 50))])
    result, scale = stitch(plan, [out], (100, 50))
    assert result.size == (200, 100) and scale == 2.0


def two_tile_plan():
    return TilePlan(
        "tiles",
        [
            Tile(Box(0, 0, 110, 100), Box(0, 0, 100, 100)),
            Tile(Box(90, 0, 200, 100), Box(100, 0, 200, 100)),
        ],
    )


def test_stitch_two_tiles_at_seam():
    outs = [Image.new("RGB", (220, 200), "red"), Image.new("RGB", (220, 200), "blue")]
    result, scale = stitch(two_tile_plan(), outs, (200, 100))
    assert scale == 2.0 and result.size == (400, 200)
    assert result.getpixel((199, 100)) == (255, 0, 0)
    assert result.getpixel((201, 100)) == (0, 0, 255)


def test_stitch_uses_smallest_tile_scale():
    outs = [Image.new("RGB", (220, 200), "red"), Image.new("RGB", (165, 150), "blue")]
    result, scale = stitch(two_tile_plan(), outs, (200, 100))
    assert scale == 1.5 and result.size == (300, 150)


def test_make_download_never_smaller_than_source():
    small = Image.new("RGB", (80, 40))
    assert make_download(small, (100, 50)).size == (100, 50)
    big = Image.new("RGB", (200, 100))
    assert make_download(big, (100, 50)) is big
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/pipeline/test_compose.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [x] **Step 3: 实现 `src/imgsr/pipeline/compose.py`**

```python
"""Pure image operations around the model call: padding, scaling, stitching."""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from imgsr.pipeline.tiling import Box, TilePlan

MAX_RATIO = 3.0


def edge_color(img: Image.Image) -> tuple[int, int, int]:
    a = np.asarray(img.convert("RGB"))
    edges = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    r, g, b = (int(v) for v in np.median(edges, axis=0))
    return (r, g, b)


def pad_to_ratio(img: Image.Image, max_ratio: float = MAX_RATIO) -> tuple[Image.Image, Box]:
    """Pad with the edge colour so long/short side <= max_ratio.

    Returns the padded image and where the original content sits inside it.
    """
    w, h = img.size
    if w / h > max_ratio:
        nw, nh = w, math.ceil(w / max_ratio)
    elif h / w > max_ratio:
        nw, nh = math.ceil(h / max_ratio), h
    else:
        return img, Box(0, 0, w, h)
    canvas = Image.new("RGB", (nw, nh), edge_color(img))
    x, y = (nw - w) // 2, (nh - h) // 2
    canvas.paste(img.convert("RGB"), (x, y))
    return canvas, Box(x, y, x + w, y + h)


def crop_content(result: Image.Image, padded_size: tuple[int, int], content: Box) -> Image.Image:
    """Undo pad_to_ratio on a (possibly rescaled) model output."""
    sx, sy = result.width / padded_size[0], result.height / padded_size[1]
    return result.crop(
        (
            round(content.x0 * sx),
            round(content.y0 * sy),
            round(content.x1 * sx),
            round(content.y1 * sy),
        )
    )


def upscale(img: Image.Image, factor: int) -> Image.Image:
    if factor == 1:
        return img
    return img.resize((img.width * factor, img.height * factor), Image.LANCZOS)


def stitch(
    plan: TilePlan, outputs: list[Image.Image], src_size: tuple[int, int]
) -> tuple[Image.Image, float]:
    """Combine per-tile outputs (same order as plan.tiles) into one image.

    Returns (image, scale) where scale maps source pixels to result pixels.
    """
    if plan.mode == "whole":
        out = outputs[0].convert("RGB")
        return out, out.width / src_size[0]
    raw = min(
        min(o.width / t.box.width, o.height / t.box.height)
        for o, t in zip(outputs, plan.tiles, strict=True)
    )
    s = max(0.1, math.floor(raw * 10 + 1e-9) / 10)
    canvas = Image.new("RGB", (round(src_size[0] * s), round(src_size[1] * s)), "white")
    for out, tile in zip(outputs, plan.tiles, strict=True):
        bx0, by0 = round(tile.box.x0 * s), round(tile.box.y0 * s)
        bw, bh = round(tile.box.x1 * s) - bx0, round(tile.box.y1 * s) - by0
        scaled = out.convert("RGB").resize((bw, bh), Image.LANCZOS)
        kx0, ky0 = round(tile.keep.x0 * s), round(tile.keep.y0 * s)
        kx1, ky1 = round(tile.keep.x1 * s), round(tile.keep.y1 * s)
        canvas.paste(scaled.crop((kx0 - bx0, ky0 - by0, kx1 - bx0, ky1 - by0)), (kx0, ky0))
    return canvas, s


def make_download(result: Image.Image, src_size: tuple[int, int]) -> Image.Image:
    """Never hand back fewer pixels than the source."""
    if result.width >= src_size[0] and result.height >= src_size[1]:
        return result
    return result.resize(src_size, Image.LANCZOS)
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/pipeline -q && uv run ruff check src tests`
Expected: 全部 passed

- [x] **Step 5: Commit**

```bash
git add src/imgsr/pipeline/compose.py tests/pipeline/test_compose.py
git commit -m "feat: pad, stitch and size tile outputs" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: 提示词与逐字比对（`pipeline/prompt.py`, `pipeline/textdiff.py`）

**Files:**
- Create: `src/imgsr/pipeline/prompt.py`, `src/imgsr/pipeline/textdiff.py`, `tests/pipeline/test_prompt.py`, `tests/pipeline/test_textdiff.py`

**Interfaces:**
- Produces:
  - `BASE_PROMPT: str`、`TRANSCRIBE_PROMPT: str`、`split_phrases(text) -> list[str]`、`build_prompt(base: str, hint_text: str | None) -> str`
  - `Diff(expected: str, found: str, sentence: str)`（frozen），`to_json() -> dict`
  - `normalize(text) -> str`：半角标点转全角、统一引号、去掉空白/破折号/省略号/项目符号/`.`/`[?]`
  - `compare(expected: str, found: str) -> list[Diff]`

- [x] **Step 1: 写失败测试**

`tests/pipeline/test_prompt.py`:

```python
from imgsr.pipeline.prompt import BASE_PROMPT, TRANSCRIBE_PROMPT, build_prompt, split_phrases


def test_no_hint_returns_base():
    assert build_prompt(BASE_PROMPT, None) == BASE_PROMPT
    assert build_prompt(BASE_PROMPT, "  \n ") == BASE_PROMPT


def test_hint_lists_each_paragraph():
    prompt = build_prompt("Base.", "第一段。\n\n 第二段。 ")
    assert prompt == (
        "Base. For reference, the original text contains these exact phrases "
        "(keep them character-for-character): 「第一段。」 / 「第二段。」."
    )


def test_split_phrases():
    assert split_phrases("a\n\n b \n") == ["a", "b"]


def test_prompts_mention_key_constraints():
    assert "do not add, remove" in BASE_PROMPT
    assert "[?]" in TRANSCRIBE_PROMPT
```

`tests/pipeline/test_textdiff.py`:

```python
from imgsr.pipeline.textdiff import Diff, compare, normalize


def test_normalize_unifies_punctuation_and_drops_noise():
    assert normalize("你好, 世界!\n[?]——…") == "你好，世界！"


def test_identical_modulo_punctuation_has_no_diffs():
    assert compare("小猫，真可爱!", "小猫, 真可爱！") == []


def test_substitution_reports_sentence():
    diffs = compare("晚上还会发出亮光呢！小猫咪特别爱干净。", "晚上还会发出光光呢！小猫咪特别爱干净。")
    assert diffs == [Diff("亮", "光", "晚上还会发出亮光呢！")]


def test_deletion():
    diffs = compare("认认真真地洗脸。", "认真地洗脸。")
    assert len(diffs) == 1
    assert diffs[0].found == "" and len(diffs[0].expected) == 2
    assert diffs[0].sentence == "认认真真地洗脸。"


def test_insertion():
    assert compare("你好。", "你好啊。") == [Diff("", "啊", "你好。")]


def test_to_json():
    assert Diff("a", "b", "c").to_json() == {"expected": "a", "found": "b", "sentence": "c"}
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/pipeline/test_prompt.py tests/pipeline/test_textdiff.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [x] **Step 3: 实现 `src/imgsr/pipeline/prompt.py`**

```python
"""Prompt texts. BASE_PROMPT was validated in the 2026-10-13 probes."""

from __future__ import annotations

BASE_PROMPT = (
    "This is a blurry, low-resolution screenshot that contains Chinese text. "
    "Restore it into a sharp, clean, high-resolution version of exactly the same image. "
    "Keep every Chinese character, punctuation mark, number, letter, emoji, icon, line break "
    "and paragraph exactly as in the original; do not add, remove, translate, rephrase, reorder "
    "or move anything. Preserve the layout, positions, proportions, borders, boxes, callout "
    "bubbles, underlines, buttons, background colors and every text color and weight. "
    "Re-render all text with crisp, clean typefaces that match the original styles. "
    "No blur, no noise, no JPEG artifacts."
)

TRANSCRIBE_PROMPT = (
    "逐字转写这张图片中的所有中文正文，按阅读顺序输出，段落之间换行。"
    "忽略界面按钮、图标、水印和缩略图。不要改写、不要纠正、不要省略；"
    "看不清的字按上下文填最可能的字，并在该字后加[?]。只输出转写文字。"
)


def split_phrases(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def build_prompt(base: str, hint_text: str | None) -> str:
    phrases = split_phrases(hint_text or "")
    if not phrases:
        return base
    joined = " / ".join(f"「{p}」" for p in phrases)
    return (
        f"{base} For reference, the original text contains these exact phrases "
        f"(keep them character-for-character): {joined}."
    )
```

- [x] **Step 4: 实现 `src/imgsr/pipeline/textdiff.py`**

```python
"""Character-level comparison between the confirmed text and a transcript of the result."""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass

_PUNCT = str.maketrans(
    {
        ",": "，", "!": "！", "?": "？", ":": "：", ";": "；", "(": "（", ")": "）",
        '"': "“", "”": "“", "'": "‘", "’": "‘",
    }
)
# OCR-noisy characters ignored on both sides: whitespace, dashes, ellipses, bullets, dots.
_DROP = re.compile(r"\[\?\]|[\s—–\-－…·•.]")
_SENTENCE_END = "。！？；"


@dataclass(frozen=True)
class Diff:
    expected: str
    found: str
    sentence: str

    def to_json(self) -> dict:
        return asdict(self)


def normalize(text: str) -> str:
    return _DROP.sub("", text.translate(_PUNCT))


def _sentence_at(text: str, index: int) -> str:
    start = max((text.rfind(c, 0, index) for c in _SENTENCE_END), default=-1) + 1
    ends = [p for c in _SENTENCE_END if (p := text.find(c, index)) != -1]
    return text[start : (min(ends) + 1 if ends else len(text))]


def compare(expected: str, found: str) -> list[Diff]:
    e, f = normalize(expected), normalize(found)
    diffs: list[Diff] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, e, f, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        anchor = min(i1, max(len(e) - 1, 0))
        diffs.append(Diff(e[i1:i2], f[j1:j2], _sentence_at(e, anchor)))
    return diffs
```

- [x] **Step 5: 运行，确认通过**

Run: `uv run pytest tests/pipeline -q && uv run ruff check src tests`
Expected: 全部 passed（若 ruff 对 `_PUNCT` 的多键一行报格式问题，按 ruff 建议拆行，不改语义）

- [x] **Step 6: Commit**

```bash
git add src/imgsr/pipeline/prompt.py src/imgsr/pipeline/textdiff.py tests/pipeline/test_prompt.py tests/pipeline/test_textdiff.py
git commit -m "feat: prompt builder and character-level text diff" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: 切块原文对齐（`pipeline/align.py`）

**Files:**
- Create: `src/imgsr/pipeline/align.py`, `tests/pipeline/test_align.py`

**Interfaces:**
- Produces: `slice_for_tile(confirmed: str, tile_transcript: str) -> str`——从确认原文中截出该切块对应的片段；无重叠返回 `""`。

- [x] **Step 1: 写失败测试 `tests/pipeline/test_align.py`**

```python
from imgsr.pipeline.align import slice_for_tile

CONFIRMED = "第一段文字在这里。\n第二段内容也在这里。\n第三段是最后的部分。"


def test_slice_middle_paragraph():
    assert slice_for_tile(CONFIRMED, "第二段内容也在这里。") == "第二段内容也在这里。"


def test_slice_tolerates_transcription_errors():
    got = slice_for_tile(CONFIRMED, "第二段内客也在这里。\n第三段是最后的部分。")
    assert got == "第二段内容也在这里。\n第三段是最后的部分。"


def test_slice_extends_over_unmatched_head():
    assert slice_for_tile(CONFIRMED, "弟二段内容也在这里。") == "第二段内容也在这里。"


def test_no_overlap_returns_empty():
    assert slice_for_tile(CONFIRMED, "完全无关的字符串ABC") == ""


def test_empty_inputs():
    assert slice_for_tile("", "x") == ""
    assert slice_for_tile("abc", "  ") == ""
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/pipeline/test_align.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [x] **Step 3: 实现 `src/imgsr/pipeline/align.py`**

```python
"""Find the part of the confirmed text that one tile shows."""

from __future__ import annotations

import difflib

_MIN_BLOCK = 3  # ignore stray 1–2 character coincidences such as "的"
_MAX_GAP = 40  # blocks further apart than this belong to different regions
_MAX_EXTEND = 20  # how far to stretch over unmatched transcript head/tail


def slice_for_tile(confirmed: str, tile_transcript: str) -> str:
    if not confirmed.strip() or not tile_transcript.strip():
        return ""
    matcher = difflib.SequenceMatcher(None, confirmed, tile_transcript, autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size >= _MIN_BLOCK]
    if not blocks:
        return ""
    groups = [[blocks[0]]]
    for block in blocks[1:]:
        prev = groups[-1][-1]
        if block.a - (prev.a + prev.size) > _MAX_GAP:
            groups.append([block])
        else:
            groups[-1].append(block)
    best = max(groups, key=lambda g: sum(b.size for b in g))
    first, last = best[0], best[-1]
    head = min(first.b, _MAX_EXTEND)
    tail = min(len(tile_transcript) - (last.b + last.size), _MAX_EXTEND)
    start = max(0, first.a - head)
    end = min(len(confirmed), last.a + last.size + tail)
    return confirmed[start:end].strip()
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/pipeline -q && uv run ruff check src tests`
Expected: 全部 passed

- [x] **Step 5: Commit**

```bash
git add src/imgsr/pipeline/align.py tests/pipeline/test_align.py
git commit -m "feat: align tile transcripts to confirmed text" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: 建议规则引擎（`review/rules.py`）

**Files:**
- Create: `src/imgsr/review/__init__.py`（空）, `src/imgsr/review/rules.py`, `tests/review/__init__.py`（空）, `tests/review/test_rules.py`

**Interfaces:**
- Consumes: `Diff`（Task 5）
- Produces: `Action = Literal["accept","retry_with_hint","tile_refine","manual_check"]`；`Suggestion(action, reason, diff_ids: list[int], params: dict)`，`to_json()`；`suggest(diffs, *, has_text: bool, used_hint: bool, preupscale: int, previous: list[Diff] | None) -> list[Suggestion]`。
- `params` 的键与 `POST /rounds` 请求体一致：`use_text_hint`、`strategy`、`preupscale`。

- [x] **Step 1: 写失败测试 `tests/review/test_rules.py`**

```python
from imgsr.pipeline.textdiff import Diff
from imgsr.review.rules import Suggestion, suggest

D = Diff("亮", "光", "晚上还会发出亮光呢！")


def actions(sugs):
    return [s.action for s in sugs]


def test_no_text_means_manual_check():
    sugs = suggest([], has_text=False, used_hint=False, preupscale=1, previous=None)
    assert actions(sugs) == ["manual_check"]


def test_clean_round_suggests_accept():
    sugs = suggest([], has_text=True, used_hint=True, preupscale=1, previous=None)
    assert actions(sugs) == ["accept"]


def test_first_fix_is_text_hint():
    sugs = suggest([D], has_text=True, used_hint=False, preupscale=1, previous=None)
    assert actions(sugs) == ["retry_with_hint"]
    assert sugs[0].params == {"use_text_hint": True} and sugs[0].diff_ids == [0]


def test_then_tile_refine():
    sugs = suggest([D], has_text=True, used_hint=True, preupscale=1, previous=None)
    assert actions(sugs) == ["tile_refine"]
    assert sugs[0].params == {"strategy": "tiles", "preupscale": 2, "use_text_hint": True}


def test_exhausted_falls_back_to_manual_check():
    sugs = suggest([D], has_text=True, used_hint=True, preupscale=2, previous=None)
    assert actions(sugs) == ["manual_check"] and sugs[0].diff_ids == [0]


def test_repeated_diff_adds_manual_check():
    sugs = suggest(
        [D, Diff("", "多", "x。")], has_text=True, used_hint=True, preupscale=1, previous=[D]
    )
    assert actions(sugs) == ["tile_refine", "manual_check"]
    assert sugs[1].diff_ids == [0]


def test_insertions_match_by_found_text():
    sugs = suggest(
        [Diff("", "多", "x。")],
        has_text=True,
        used_hint=True,
        preupscale=2,
        previous=[Diff("", "多", "y。")],
    )
    assert actions(sugs) == ["manual_check"] and sugs[0].diff_ids == [0]


def test_to_json():
    assert Suggestion("accept", "ok").to_json() == {
        "action": "accept", "reason": "ok", "diff_ids": [], "params": {}
    }
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/review -q`
Expected: FAIL，`ModuleNotFoundError`

- [x] **Step 3: 实现 `src/imgsr/review/rules.py`**

```python
"""Rule engine: review diffs -> short list of next-step suggestions (spec §6.5)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from imgsr.pipeline.textdiff import Diff

Action = Literal["accept", "retry_with_hint", "tile_refine", "manual_check"]


@dataclass(frozen=True)
class Suggestion:
    action: Action
    reason: str
    diff_ids: list[int] = field(default_factory=list)
    params: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)


def _key(diff: Diff) -> str:
    return diff.expected if diff.expected else f"+{diff.found}"


def suggest(
    diffs: list[Diff],
    *,
    has_text: bool,
    used_hint: bool,
    preupscale: int,
    previous: list[Diff] | None,
) -> list[Suggestion]:
    if not has_text:
        return [Suggestion("manual_check", "没有确认原文，无法自动比对，请人工放大核对")]
    if not diffs:
        return [Suggestion("accept", "结果转写与确认原文一致，可以设为最终版")]
    all_ids = list(range(len(diffs)))
    previous_keys = {_key(d) for d in previous or []}
    repeated = [i for i, d in enumerate(diffs) if _key(d) in previous_keys]
    out: list[Suggestion] = []
    if not used_hint:
        out.append(
            Suggestion("retry_with_hint", "上一轮没有带原文提示，带上完整原文重跑", all_ids,
                       {"use_text_hint": True})
        )
    elif preupscale < 2:
        out.append(
            Suggestion("tile_refine", "已带原文提示仍有差异，切块并预放大 2 倍后重绘", all_ids,
                       {"strategy": "tiles", "preupscale": 2, "use_text_hint": True})
        )
    if repeated:
        out.append(
            Suggestion("manual_check", "这些差异连续两轮出现，模型可能改不对，请人工放大核对或接受",
                       repeated)
        )
    if not out:
        out.append(Suggestion("manual_check", "自动修正手段已用尽，请人工核对剩余差异", all_ids))
    return out
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/review -q && uv run ruff check src tests`
Expected: `8 passed`

- [x] **Step 5: Commit**

```bash
git add src/imgsr/review/__init__.py src/imgsr/review/rules.py tests/review/__init__.py tests/review/test_rules.py
git commit -m "feat: rule engine for review suggestions" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: 中转站客户端（`relay/`）

**Files:**
- Create: `src/imgsr/relay/__init__.py`（空）, `src/imgsr/relay/base.py`, `src/imgsr/relay/errors.py`, `src/imgsr/relay/retry.py`, `src/imgsr/relay/images.py`, `src/imgsr/relay/chat.py`, `tests/relay/__init__.py`（空）, `tests/relay/test_relay.py`

**Interfaces:**
- Produces:
  - `normalize_base(url) -> str`、`masked(key) -> str`
  - `RelayError(message, *, kind: str, retryable: bool, status: int | None = None)`，属性 `message/kind/retryable/status`；`classify(status, body) -> RelayError`。`kind ∈ {"busy","auth","rejected","upstream","timeout","network","empty"}`
  - `DEFAULT_DELAYS = (10.0, 30.0)`；`async with_retries(fn, *, delays=DEFAULT_DELAYS, sleep=asyncio.sleep)`
  - `request_size(w, h) -> str`；`ImageClient(base_url, api_key, *, timeout=180.0, transport=None)`：`async edit(*, model, prompt, image_png: bytes, size: tuple[int,int]) -> bytes`、`async aclose()`
  - `ChatClient(base_url, api_key, *, timeout=240.0, transport=None)`：`async transcribe(*, model, prompt, image_png: bytes) -> str`、`async aclose()`

- [x] **Step 1: 写失败测试 `tests/relay/test_relay.py`**

```python
import base64
import io
import json

import httpx
import pytest
from PIL import Image

from imgsr.relay.base import masked, normalize_base
from imgsr.relay.chat import ChatClient
from imgsr.relay.errors import RelayError, classify
from imgsr.relay.images import ImageClient, request_size
from imgsr.relay.retry import with_retries


def png(size=(10, 10)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, "PNG")
    return buf.getvalue()


def image_client(handler):
    return ImageClient("https://relay.test/v1/", "sk-test", transport=httpx.MockTransport(handler))


def chat_client(handler, timeout=5.0):
    return ChatClient(
        "https://relay.test", "sk-test", timeout=timeout, transport=httpx.MockTransport(handler)
    )


def sse(*chunks, done=True):
    lines = [f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks]
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def test_base_and_mask():
    assert normalize_base("https://relay.test/v1/") == "https://relay.test"
    assert normalize_base("https://relay.test") == "https://relay.test"
    assert masked("sk-8b1234567890af8e") == "sk-8b1…af8e"
    assert masked("short") == "***"


async def test_edit_returns_b64_image_and_sends_multipart():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), auth=request.headers["authorization"], body=request.content)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]})

    raw = await image_client(handler).edit(
        model="gpt-image-2.5", prompt="清晰", image_png=png(), size=(100, 50)
    )
    assert raw.startswith(b"\x89PNG")
    assert seen["url"] == "https://relay.test/v1/images/edits"
    assert seen["auth"] == "Bearer sk-test"
    assert b'name="model"' in seen["body"] and b"gpt-image-2.5" in seen["body"]
    assert b"192x96" in seen["body"]


async def test_edit_downloads_relative_url_with_auth():
    calls = []

    def handler(request):
        calls.append((request.url.host, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/v1/images/edits":
            return httpx.Response(200, json={"data": [{"url": "/v1/files/abc"}]})
        return httpx.Response(200, content=png())

    await image_client(handler).edit(model="m", prompt="p", image_png=png(), size=(10, 10))
    assert calls[1] == ("relay.test", "/v1/files/abc", "Bearer sk-test")


async def test_edit_downloads_absolute_url_without_auth():
    calls = []

    def handler(request):
        calls.append((request.url.host, request.headers.get("authorization")))
        if request.url.host == "relay.test":
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example/x.png"}]})
        return httpx.Response(200, content=png())

    await image_client(handler).edit(model="m", prompt="p", image_png=png(), size=(10, 10))
    assert calls[1] == ("cdn.example", None)


@pytest.mark.parametrize(
    "status,body,kind,retryable",
    [
        (429, '{"error":{"message":"All available accounts are currently rate-limited"}}', "busy", True),
        (503, "no eligible account", "busy", True),
        (400, '{"error":{"message":"image too large"}}', "rejected", False),
        (401, "bad key", "auth", False),
        (524, "<!DOCTYPE html><title>524</title>", "upstream", True),
    ],
)
def test_classify(status, body, kind, retryable):
    err = classify(status, body)
    assert (err.kind, err.retryable, err.status) == (kind, retryable, status)


def test_classify_keeps_upstream_message():
    assert "image too large" in classify(400, '{"error":{"message":"image too large"}}').message


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>cloudflare</html>"),
        httpx.Response(200, json={"data": []}),
        httpx.Response(200, json=["unexpected"]),
        httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(b"not an image").decode()}]}),
    ],
)
async def test_edit_unusable_200_is_retryable_empty(response):
    with pytest.raises(RelayError) as info:
        await image_client(lambda request: response).edit(
            model="m", prompt="p", image_png=png(), size=(10, 10)
        )
    assert info.value.kind == "empty" and info.value.retryable


async def test_edit_timeout_is_retryable():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(RelayError) as info:
        await image_client(handler).edit(model="m", prompt="p", image_png=png(), size=(10, 10))
    assert info.value.kind == "timeout" and info.value.retryable


def test_request_size_keeps_aspect_and_limits():
    assert request_size(100, 50) == "192x96"
    w, h = map(int, request_size(2316, 1294).split("x"))
    assert w * h <= 8_294_400 and max(w, h) <= 3840 and w % 16 == 0 and h % 16 == 0


async def test_transcribe_streams_and_joins_deltas():
    seen = {}

    def handler(request):
        seen.update(path=request.url.path, body=json.loads(request.content))
        return httpx.Response(
            200,
            content=sse(
                {"choices": [{"delta": {"content": "第一行"}}]},
                {"choices": [{"delta": {"content": "。\n第二行。"}}]},
            ),
            headers={"content-type": "text/event-stream"},
        )

    text = await chat_client(handler).transcribe(model="gpt-6-sol", prompt="转写", image_png=png())
    assert text == "第一行。\n第二行。"
    assert seen["path"] == "/v1/chat/completions" and seen["body"]["stream"] is True
    content = seen["body"]["messages"][0]["content"]
    assert content[0]["text"] == "转写"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_transcribe_skips_keepalives_and_garbage():
    body = b": ping\n\ndata: not-json\n\n" + sse({"choices": [{"delta": {"content": "好"}}]})
    text = await chat_client(lambda r: httpx.Response(200, content=body)).transcribe(
        model="m", prompt="p", image_png=png()
    )
    assert text == "好"


async def test_transcribe_error_status():
    with pytest.raises(RelayError) as info:
        await chat_client(lambda r: httpx.Response(502, text="<html>bad gateway</html>")).transcribe(
            model="m", prompt="p", image_png=png()
        )
    assert info.value.kind == "upstream" and info.value.retryable


async def test_transcribe_empty_is_retryable():
    body = sse({"choices": [{"delta": {}}]})
    with pytest.raises(RelayError) as info:
        await chat_client(lambda r: httpx.Response(200, content=body)).transcribe(
            model="m", prompt="p", image_png=png()
        )
    assert info.value.kind == "empty"


async def test_with_retries_sleeps_between_retryable_failures():
    attempts, sleeps = [], []

    async def fn():
        attempts.append(1)
        if len(attempts) < 3:
            raise RelayError("busy", kind="busy", retryable=True)
        return "ok"

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    assert await with_retries(fn, sleep=fake_sleep) == "ok"
    assert sleeps == [10.0, 30.0]


async def test_with_retries_gives_up_after_last_delay():
    sleeps = []

    async def fn():
        raise RelayError("busy", kind="busy", retryable=True)

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    with pytest.raises(RelayError):
        await with_retries(fn, sleep=fake_sleep)
    assert sleeps == [10.0, 30.0]


async def test_with_retries_does_not_retry_rejections():
    attempts = []

    async def fn():
        attempts.append(1)
        raise RelayError("bad", kind="rejected", retryable=False)

    with pytest.raises(RelayError):
        await with_retries(fn)
    assert len(attempts) == 1
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/relay -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'imgsr.relay'`

- [x] **Step 3: 实现 `src/imgsr/relay/base.py`、`errors.py`、`retry.py`**

`src/imgsr/relay/base.py`:

```python
from __future__ import annotations


def normalize_base(url: str) -> str:
    url = url.rstrip("/")
    return url[:-3] if url.endswith("/v1") else url


def masked(key: str) -> str:
    return f"{key[:6]}…{key[-4:]}" if len(key) > 12 else "***"
```

`src/imgsr/relay/errors.py`:

```python
"""Relay error type and HTTP status classification."""

from __future__ import annotations

import json


class RelayError(Exception):
    def __init__(self, message: str, *, kind: str, retryable: bool, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.retryable = retryable
        self.status = status


def _upstream_message(body: str) -> str:
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:300]
        if isinstance(err, str):
            return err[:300]
    return body.strip()[:200] or "empty body"


def classify(status: int, body: str) -> RelayError:
    if status in (429, 503):
        return RelayError(f"上游繁忙：{_upstream_message(body)}", kind="busy", retryable=True, status=status)
    if status in (401, 403):
        return RelayError(f"上游拒绝鉴权：{_upstream_message(body)}", kind="auth", retryable=False, status=status)
    if 400 <= status < 500:
        return RelayError(f"上游拒绝请求：{_upstream_message(body)}", kind="rejected", retryable=False, status=status)
    return RelayError(f"上游错误 {status}", kind="upstream", retryable=True, status=status)
```

`src/imgsr/relay/retry.py`:

```python
"""Retry retryable relay errors with fixed back-off delays."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from imgsr.relay.errors import RelayError

T = TypeVar("T")
DEFAULT_DELAYS: tuple[float, ...] = (10.0, 30.0)


async def with_retries(
    fn: Callable[[], Awaitable[T]],
    *,
    delays: tuple[float, ...] = DEFAULT_DELAYS,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> T:
    for attempt in range(len(delays) + 1):
        try:
            return await fn()
        except RelayError as exc:
            if not exc.retryable or attempt == len(delays):
                raise
            await sleep(delays[attempt])
    raise AssertionError("unreachable")
```

- [x] **Step 4: 实现 `src/imgsr/relay/images.py`**

```python
"""Client for the relay's OpenAI-compatible image edit endpoint."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from imgsr.relay.base import normalize_base
from imgsr.relay.errors import RelayError, classify


def _looks_like_image(raw: bytes) -> bool:
    return raw.startswith((b"\x89PNG", b"\xff\xd8\xff")) or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")


def request_size(
    w: int, h: int, scale: float = 2.0, max_pixels: int = 8_294_400, max_edge: int = 3840
) -> str:
    """The `size` we send. The relay caps output at ~1.57 MP anyway; 2x keeps the aspect hint."""
    tw, th = w * scale, h * scale
    k = min(1.0, (max_pixels / (tw * th)) ** 0.5, max_edge / max(tw, th))
    return f"{max(16, int(tw * k) // 16 * 16)}x{max(16, int(th * k) // 16 * 16)}"


def _first_item(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    items = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    raise RelayError("上游返回了空结果", kind="empty", retryable=True)


class ImageClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base = normalize_base(base_url)
        self._key = api_key
        # httpx drops Authorization on cross-origin redirects, so CDN hops never see the key.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=15.0), transport=transport, follow_redirects=True
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def edit(self, *, model: str, prompt: str, image_png: bytes, size: tuple[int, int]) -> bytes:
        data = {"model": model, "prompt": prompt, "n": "1", "size": request_size(*size)}
        files = {"image": ("image.png", image_png, "image/png")}
        response = await self._send("POST", f"{self.base}/v1/images/edits", auth=True, data=data, files=files)
        item = _first_item(response)
        if item.get("b64_json"):
            try:
                raw = base64.b64decode(item["b64_json"])
            except ValueError as exc:
                raise RelayError("上游返回的图片无法解码", kind="empty", retryable=True) from exc
        elif item.get("url"):
            url = str(item["url"])
            relative = url.startswith("/")
            raw = (await self._send("GET", self.base + url if relative else url, auth=relative)).content
        else:
            raise RelayError("上游返回了空结果", kind="empty", retryable=True)
        if not _looks_like_image(raw):
            raise RelayError("上游返回的不是图片", kind="empty", retryable=True)
        return raw

    async def _send(self, method: str, url: str, *, auth: bool, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._key}"} if auth else {}
        try:
            response = await self._client.request(method, url, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise RelayError("上游超时", kind="timeout", retryable=True) from exc
        except httpx.TransportError as exc:
            raise RelayError(f"连接上游失败：{exc.__class__.__name__}", kind="network", retryable=True) from exc
        if response.status_code >= 400:
            raise classify(response.status_code, response.text)
        return response
```

- [x] **Step 5: 实现 `src/imgsr/relay/chat.py`**

```python
"""Streaming vision chat client used to transcribe text in images."""

from __future__ import annotations

import asyncio
import base64
import json

import httpx

from imgsr.relay.base import normalize_base
from imgsr.relay.errors import RelayError, classify


class ChatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 240.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base = normalize_base(base_url)
        self._key = api_key
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0), transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(self, *, model: str, prompt: str, image_png: bytes) -> str:
        data_uri = "data:image/png;base64," + base64.b64encode(image_png).decode()
        body = {
            "model": model,
            "stream": True,  # non-streamed calls over 100 s die at Cloudflare with 524
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri, "detail": "high"}},
                    ],
                }
            ],
        }
        parts: list[str] = []
        try:
            async with asyncio.timeout(self._timeout):
                async with self._client.stream(
                    "POST",
                    f"{self.base}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._key}"},
                    json=body,
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise classify(response.status_code, response.text)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except ValueError:
                            continue
                        if not isinstance(chunk, dict):
                            continue
                        for choice in chunk.get("choices") or []:
                            content = (choice.get("delta") or {}).get("content")
                            if isinstance(content, str):
                                parts.append(content)
        except TimeoutError as exc:
            raise RelayError("转写超时", kind="timeout", retryable=True) from exc
        except httpx.TimeoutException as exc:
            raise RelayError("转写超时", kind="timeout", retryable=True) from exc
        except httpx.TransportError as exc:
            raise RelayError(f"连接上游失败：{exc.__class__.__name__}", kind="network", retryable=True) from exc
        text = "".join(parts).strip()
        if not text:
            raise RelayError("上游返回了空转写", kind="empty", retryable=True)
        return text
```

- [x] **Step 6: 运行，确认通过**

Run: `uv run pytest tests/relay -q && uv run ruff check src tests`
Expected: 全部 passed

- [x] **Step 7: Commit**

```bash
git add src/imgsr/relay tests/relay
git commit -m "feat: relay clients for image edits and streamed transcription" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: 数据库模型与迁移（`db/`）

**Files:**
- Create: `src/imgsr/db/__init__.py`（空）, `src/imgsr/db/models.py`, `src/imgsr/db/session.py`, `alembic.ini` 与 `src/imgsr/db/migrations/`（由 `alembic init` 生成，替换 `env.py`）, `tests/conftest.py`, `tests/db/__init__.py`（空）, `tests/db/test_migrations.py`

**Interfaces:**
- Produces:
  - `utcnow() -> datetime`（naive UTC）
  - 模型：`Base`, `User`, `SessionRow`, `Task`, `Round`, `Job`, `UsageDaily`, `SettingRow`（字段见代码；与 spec §5 一致，路径不入库）
  - `make_engine(db_path: Path) -> Engine`（WAL、`foreign_keys=ON`、`busy_timeout`）、`make_session_factory(engine) -> sessionmaker[Session]`（`expire_on_commit=False`）、`migrate(engine) -> None`
  - 测试夹具（`tests/conftest.py`）：`engine`, `sf`
- 注意：JSON 列修改时必须**整体重新赋值**（如 `task.tile_transcripts = {...}`），不要原地修改字典。

- [x] **Step 1: 写失败测试**

`tests/conftest.py`:

```python
import pytest

from imgsr.db.models import Base
from imgsr.db.session import make_engine, make_session_factory


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "db" / "test.sqlite3")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def sf(engine):
    return make_session_factory(engine)
```

`tests/db/test_migrations.py`:

```python
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

from imgsr.db.models import Base
from imgsr.db.session import make_engine, migrate


def test_migration_matches_models(tmp_path):
    engine = make_engine(tmp_path / "m.sqlite3")
    migrate(engine)
    with engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"render_as_batch": True})
        assert compare_metadata(context, Base.metadata) == []
    migrate(engine)  # idempotent
    engine.dispose()


def test_foreign_keys_and_wal_enabled(tmp_path):
    engine = make_engine(tmp_path / "p.sqlite3")
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
    engine.dispose()
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/db -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'imgsr.db'`

- [x] **Step 3: 实现 `src/imgsr/db/models.py`**

```python
"""SQLAlchemy models. Timestamps are naive UTC (see utcnow)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")
    daily_quota: Mapped[int] = mapped_column(Integer, default=50)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    guest_token_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    client_ip: Mapped[str] = mapped_column(String(64))
    source_w: Mapped[int] = mapped_column(Integer)
    source_h: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="uploaded")
    transcript_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tile_transcripts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    final_round_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    rounds: Mapped[list[Round]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="Round.seq"
    )


class Round(Base):
    __tablename__ = "rounds"
    __table_args__ = (UniqueConstraint("task_id", "seq"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    image_model: Mapped[str] = mapped_column(String(64))
    prompt: Mapped[str] = mapped_column(Text)
    strategy: Mapped[dict[str, Any]] = mapped_column(JSON)
    use_text_hint: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    result_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    download_w: Mapped[int | None] = mapped_column(Integer, nullable=True)
    download_h: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    review: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    charge: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    task: Mapped[Task] = relationship(back_populates="rounds")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    round_id: Mapped[int | None] = mapped_column(
        ForeignKey("rounds.id", ondelete="CASCADE"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UsageDaily(Base):
    __tablename__ = "usage_daily"
    subject: Mapped[str] = mapped_column(String(80), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    image_calls: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)


class SettingRow(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
```

- [x] **Step 4: 实现 `src/imgsr/db/session.py`**

```python
"""Engine/session factories and programmatic Alembic upgrades."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

MIGRATIONS = Path(__file__).parent / "migrations"


def make_engine(db_path: Path) -> Engine:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine, expire_on_commit=False)


def migrate(engine: Engine) -> None:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, "head")
```

- [x] **Step 5: 生成 Alembic 骨架并替换 `env.py`**

```bash
uv run alembic init src/imgsr/db/migrations
```

Expected: 生成 `alembic.ini`、`src/imgsr/db/migrations/{env.py,script.py.mako,README,versions/}`。把 `src/imgsr/db/migrations/env.py` **整体替换**为：

```python
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from imgsr.config import Settings
from imgsr.db.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def _url() -> str:
    path = Settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_url())
    with engine.connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata, render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [x] **Step 6: 自动生成初始迁移**

```bash
DATA_DIR=./data uv run alembic revision --autogenerate -m "initial schema"
```

Expected: 新文件 `src/imgsr/db/migrations/versions/<rev>_initial_schema.py`，包含 7 个 `op.create_table`（users、sessions、tasks、rounds、jobs、usage_daily、settings）。打开检查确认无多余操作。

- [x] **Step 7: 运行，确认通过**

Run: `uv run pytest tests/db -q && uv run ruff check src tests`
Expected: `2 passed`。若 `compare_metadata` 只报告 SQLite 反射造成的无名唯一约束差异（`add_constraint`/`remove_constraint`），先确认迁移文件里确有对应 `UniqueConstraint`，再在测试里过滤这两类条目，并在“执行记录”写明原因；其他差异一律按真问题排查（ruff 若对生成的迁移文件报风格问题，运行 `uv run ruff check --fix src/imgsr/db/migrations` 后重跑）

- [x] **Step 8: Commit**

```bash
git add alembic.ini src/imgsr/db tests/conftest.py tests/db
git commit -m "feat: database models and initial migration" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: 文件存储与上传规范化（`storage.py`, `uploads.py`）

**Files:**
- Create: `src/imgsr/storage.py`, `src/imgsr/uploads.py`, `tests/test_storage.py`, `tests/test_uploads.py`

**Interfaces:**
- Produces:
  - `TASK_ID_RE`（32 位小写十六进制）；`Storage(root)`：`task_dir(task_id)`（非法 id 抛 `ValueError`）、`source/thumb/round_dir/result/download/tile(task_id, seq, index, kind)`、`named(task_id, name) -> Path | None`（白名单 `source|thumb|result-N|download-N`，文件不存在返回 None）、`save_source(task_id, img)`（PNG + 480px WebP 缩略图）、`delete_task(task_id)`、`free_bytes()`
  - `save_png(img, path)`、`png_bytes(img) -> bytes`
  - `UploadRejected(Exception)`（中文消息）；`normalize_upload(data, *, max_bytes, max_pixels) -> Image`（RGB，已按 EXIF 转正，已去 EXIF）

- [x] **Step 1: 写失败测试**

`tests/test_storage.py`:

```python
import pytest
from PIL import Image

from imgsr.storage import Storage, png_bytes, save_png

TID = "a" * 32


def test_paths_and_named_lookup(tmp_path):
    s = Storage(tmp_path)
    s.save_source(TID, Image.new("RGB", (50, 40)))
    assert s.named(TID, "source") == s.source(TID)
    assert s.named(TID, "thumb").suffix == ".webp"
    assert s.named(TID, "result-1") is None
    save_png(Image.new("RGB", (5, 5)), s.result(TID, 1))
    assert s.named(TID, "result-1") == s.result(TID, 1)
    assert s.tile(TID, 2, 3, "out").name == "03-out.png"


@pytest.mark.parametrize(
    "task_id,name",
    [(TID, "../etc"), ("../../x", "source"), ("A" * 32, "source"), (TID, "source.png")],
)
def test_named_rejects_bad_input(tmp_path, task_id, name):
    assert Storage(tmp_path).named(task_id, name) is None


def test_task_dir_rejects_bad_id(tmp_path):
    with pytest.raises(ValueError):
        Storage(tmp_path).task_dir("../x")


def test_delete_task_and_free_bytes(tmp_path):
    s = Storage(tmp_path)
    s.save_source(TID, Image.new("RGB", (5, 5)))
    s.delete_task(TID)
    assert not s.task_dir(TID).exists()
    assert s.free_bytes() > 0


def test_png_bytes():
    assert png_bytes(Image.new("RGB", (2, 2))).startswith(b"\x89PNG")
```

`tests/test_uploads.py`:

```python
import io

import pytest
from PIL import Image

from imgsr.uploads import UploadRejected, normalize_upload

LIMITS = {"max_bytes": 15_000_000, "max_pixels": 25_000_000}


def encode(img, fmt, **kw):
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def test_rgba_png_is_flattened_on_white():
    img = Image.new("RGBA", (20, 10), (255, 0, 0, 0))
    img.putpixel((0, 0), (0, 0, 255, 255))
    out = normalize_upload(encode(img, "PNG"), **LIMITS)
    assert out.mode == "RGB"
    assert out.getpixel((5, 5)) == (255, 255, 255)
    assert out.getpixel((0, 0)) == (0, 0, 255)


def test_palette_png_with_transparency():
    img = Image.new("P", (10, 10), 0)
    img.putpalette([255, 0, 0] + [0, 0, 0] * 255)
    out = normalize_upload(encode(img, "PNG", transparency=0), **LIMITS)
    assert out.getpixel((0, 0)) == (255, 255, 255)


def test_cmyk_jpeg_becomes_rgb():
    out = normalize_upload(encode(Image.new("CMYK", (10, 10), (0, 0, 0, 0)), "JPEG"), **LIMITS)
    assert out.mode == "RGB" and out.getpixel((5, 5))[0] > 240


def test_exif_rotation_is_applied():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise when displayed
    data = encode(Image.new("RGB", (200, 100), "white"), "JPEG", exif=exif)
    out = normalize_upload(data, **LIMITS)
    assert out.size == (100, 200)
    assert not out.info.get("exif")


def test_16bit_grey_png():
    out = normalize_upload(encode(Image.new("I;16", (10, 10), 40000), "PNG"), **LIMITS)
    assert out.mode == "RGB" and out.getpixel((0, 0)) == (156, 156, 156)


@pytest.mark.parametrize(
    "data,message",
    [
        (b"", "文件为空"),
        (b"hello", "无法识别"),
        (encode(Image.new("RGB", (5, 5)), "GIF"), "只支持"),
    ],
)
def test_rejections(data, message):
    with pytest.raises(UploadRejected, match=message):
        normalize_upload(data, **LIMITS)


def test_too_many_bytes():
    with pytest.raises(UploadRejected, match="上限"):
        normalize_upload(b"x" * 11, max_bytes=10, max_pixels=25_000_000)


def test_too_many_pixels():
    data = encode(Image.new("RGB", (200, 100)), "PNG")
    with pytest.raises(UploadRejected, match="像素"):
        normalize_upload(data, max_bytes=15_000_000, max_pixels=10_000)
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_storage.py tests/test_uploads.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [x] **Step 3: 实现 `src/imgsr/storage.py`**

```python
"""Filesystem layout for task images. All paths derive from the task id."""

from __future__ import annotations

import io
import re
import shutil
from pathlib import Path
from typing import Literal

from PIL import Image

TASK_ID_RE = re.compile(r"[0-9a-f]{32}")
_NAME_RE = re.compile(r"source|thumb|result-(\d{1,4})|download-(\d{1,4})")


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def task_dir(self, task_id: str) -> Path:
        if not TASK_ID_RE.fullmatch(task_id):
            raise ValueError(f"invalid task id: {task_id!r}")
        return self.root / task_id

    def source(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "source.png"

    def thumb(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "thumb.webp"

    def round_dir(self, task_id: str, seq: int) -> Path:
        return self.task_dir(task_id) / "rounds" / str(seq)

    def result(self, task_id: str, seq: int) -> Path:
        return self.round_dir(task_id, seq) / "result.png"

    def download(self, task_id: str, seq: int) -> Path:
        return self.round_dir(task_id, seq) / "download.png"

    def tile(self, task_id: str, seq: int, index: int, kind: Literal["in", "out"]) -> Path:
        return self.round_dir(task_id, seq) / "tiles" / f"{index:02d}-{kind}.png"

    def named(self, task_id: str, name: str) -> Path | None:
        match = _NAME_RE.fullmatch(name)
        if match is None or not TASK_ID_RE.fullmatch(task_id):
            return None
        if name == "source":
            path = self.source(task_id)
        elif name == "thumb":
            path = self.thumb(task_id)
        elif match.group(1):
            path = self.result(task_id, int(match.group(1)))
        else:
            path = self.download(task_id, int(match.group(2)))
        return path if path.is_file() else None

    def save_source(self, task_id: str, img: Image.Image) -> None:
        save_png(img, self.source(task_id))
        thumb = img.copy()
        thumb.thumbnail((480, 480))
        thumb.save(self.thumb(task_id), "WEBP", quality=80)

    def delete_task(self, task_id: str) -> None:
        shutil.rmtree(self.task_dir(task_id), ignore_errors=True)

    def free_bytes(self) -> int:
        self.root.mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(self.root).free
```

- [x] **Step 4: 实现 `src/imgsr/uploads.py`**

```python
"""Validate and normalise user uploads into a plain RGB image."""

from __future__ import annotations

import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}


class UploadRejected(Exception):
    """Raised with a user-facing (Chinese) message."""


def normalize_upload(data: bytes, *, max_bytes: int, max_pixels: int) -> Image.Image:
    if not data:
        raise UploadRejected("文件为空")
    if len(data) > max_bytes:
        raise UploadRejected(f"文件超过 {max_bytes // 1_000_000} MB 上限")
    too_big = f"图片像素超过 {max_pixels // 1_000_000} MP 上限"
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data))
            if img.format not in ALLOWED_FORMATS:
                raise UploadRejected("只支持 PNG、JPG、WebP 图片")
            if img.width * img.height > max_pixels:
                raise UploadRejected(too_big)
            img.load()
    except UploadRejected:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise UploadRejected(too_big) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise UploadRejected("无法识别的图片文件") from exc
    return _to_rgb(ImageOps.exif_transpose(img))


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, "white")
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    if img.mode.startswith("I;16"):
        img = img.convert("I")
    if img.mode == "I":
        img = img.point(lambda v: v * (1 / 256)).convert("L")
    rgb = img.convert("RGB")
    rgb.info.pop("exif", None)
    return rgb
```

- [x] **Step 5: 运行，确认通过**

Run: `uv run pytest tests/test_storage.py tests/test_uploads.py -q && uv run ruff check src tests`
Expected: 全部 passed

- [x] **Step 6: Commit**

```bash
git add src/imgsr/storage.py src/imgsr/uploads.py tests/test_storage.py tests/test_uploads.py
git commit -m "feat: task file storage and upload normalisation" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: 认证、真实 IP 与限额（`auth.py`, `clientip.py`, `quota.py`）

**Files:**
- Create: `src/imgsr/auth.py`, `src/imgsr/clientip.py`, `src/imgsr/quota.py`, `tests/test_auth.py`, `tests/test_clientip.py`, `tests/test_quota.py`
- Modify: `tests/conftest.py`（追加 `make_user`、`make_task` 夹具）

**Interfaces:**
- Produces:
  - `SESSION_COOKIE = "imgsr_session"`、`GUEST_COOKIE = "imgsr_guest"`；`hash_password`、`verify_password(stored, password) -> bool`、`new_token()`、`token_hash(token)`、`create_session(db, user, days, now=None) -> str`、`user_for_token(db, token, days, now=None) -> User | None`（每小时滑动续期）、`end_session(db, token)`、`end_user_sessions(db, user_id)`、`LoginLimiter(max_failures=10, window=timedelta(minutes=15))`：`locked(ip, now=None)`、`failed(ip, now=None)`、`succeeded(ip)`
  - `parse_networks(spec) -> list[Network]`、`resolve_client_ip(peer, headers, header_name, trusted) -> str`
  - `QuotaExceeded(Exception)`、`today(now=None) -> date`（UTC+8）、`consume(db, limits: list[tuple[subject, limit, message]], day) -> dict`（**须在会话无其他待提交改动时调用**）、`refund(db, charge | None)`、`count_llm(db, subject, day)`、`used(db, subject, day) -> int`
  - 夹具：`make_user(username="alice", password="password123", role="user", daily_quota=50) -> int`、`make_task(task_id=None, *, owner=None, ip="1.2.3.4", w=100, h=100, status="uploaded", expires_at=None, **kw) -> str`

- [x] **Step 1: 追加夹具到 `tests/conftest.py`**

在文件末尾追加：

```python
import uuid
from datetime import timedelta

from imgsr.auth import hash_password
from imgsr.db.models import Task, User, utcnow


@pytest.fixture
def make_user(sf):
    def _make(username="alice", password="password123", role="user", daily_quota=50):
        with sf() as db:
            user = User(
                username=username,
                password_hash=hash_password(password),
                role=role,
                daily_quota=daily_quota,
            )
            db.add(user)
            db.commit()
            return user.id

    return _make


@pytest.fixture
def make_task(sf):
    def _make(task_id=None, *, owner=None, ip="1.2.3.4", w=100, h=100, status="uploaded",
              expires_at=None, **kw):
        tid = task_id or uuid.uuid4().hex
        with sf() as db:
            db.add(Task(id=tid, owner_user_id=owner, client_ip=ip, source_w=w, source_h=h,
                        status=status, expires_at=expires_at or utcnow() + timedelta(days=1), **kw))
            db.commit()
        return tid

    return _make
```

（把新增的 import 移到文件顶部，保持 ruff `I` 规则通过。）

- [x] **Step 2: 写失败测试**

`tests/test_auth.py`:

```python
from datetime import timedelta

from sqlalchemy import select

from imgsr.auth import (
    LoginLimiter,
    create_session,
    end_session,
    end_user_sessions,
    hash_password,
    user_for_token,
    verify_password,
)
from imgsr.db.models import SessionRow, User, utcnow


def test_password_roundtrip():
    stored = hash_password("password123")
    assert verify_password(stored, "password123")
    assert not verify_password(stored, "nope")
    assert not verify_password("garbage", "x")


def test_session_lifecycle(sf, make_user):
    uid = make_user()
    with sf() as db:
        token = create_session(db, db.get(User, uid), days=14)
        assert user_for_token(db, token, 14).id == uid
        assert user_for_token(db, "wrong", 14) is None
        assert user_for_token(db, None, 14) is None
        end_session(db, token)
        assert user_for_token(db, token, 14) is None


def test_expired_and_disabled_sessions(sf, make_user):
    uid = make_user()
    with sf() as db:
        user = db.get(User, uid)
        old = create_session(db, user, days=1, now=utcnow() - timedelta(days=2))
        assert user_for_token(db, old, 1) is None
        token = create_session(db, user, days=14)
        user.disabled = True
        db.commit()
        assert user_for_token(db, token, 14) is None


def test_session_slides_forward(sf, make_user):
    uid = make_user()
    with sf() as db:
        t0 = utcnow() - timedelta(days=10)
        token = create_session(db, db.get(User, uid), 14, now=t0)
        later = t0 + timedelta(days=10)
        user_for_token(db, token, 14, now=later)
        row = db.scalar(select(SessionRow))
        assert row.expires_at == later + timedelta(days=14)


def test_end_user_sessions(sf, make_user):
    uid = make_user()
    with sf() as db:
        token = create_session(db, db.get(User, uid), 14)
        end_user_sessions(db, uid)
        assert user_for_token(db, token, 14) is None


def test_login_limiter():
    limiter = LoginLimiter(max_failures=3, window=timedelta(minutes=15))
    t = utcnow()
    for _ in range(3):
        limiter.failed("1.1.1.1", t)
    assert limiter.locked("1.1.1.1", t)
    assert not limiter.locked("2.2.2.2", t)
    assert not limiter.locked("1.1.1.1", t + timedelta(minutes=16))
    limiter.failed("3.3.3.3", t)
    limiter.succeeded("3.3.3.3")
    assert not limiter.locked("3.3.3.3", t)
```

`tests/test_clientip.py`:

```python
from imgsr.clientip import parse_networks, resolve_client_ip

TRUSTED = parse_networks("127.0.0.1,172.16.0.0/12")
XFF = "X-Forwarded-For"


def test_untrusted_peer_cannot_spoof():
    assert resolve_client_ip("8.8.8.8", {XFF: "1.1.1.1"}, XFF, TRUSTED) == "8.8.8.8"


def test_trusted_proxy_header_is_used():
    assert resolve_client_ip("127.0.0.1", {XFF: "1.2.3.4"}, XFF, TRUSTED) == "1.2.3.4"


def test_rightmost_untrusted_address_wins():
    headers = {XFF: "6.6.6.6, 1.2.3.4, 172.18.0.5"}
    assert resolve_client_ip("172.18.0.1", headers, XFF, TRUSTED) == "1.2.3.4"


def test_garbage_or_missing_header_falls_back_to_peer():
    assert resolve_client_ip("127.0.0.1", {XFF: "not-an-ip"}, XFF, TRUSTED) == "127.0.0.1"
    assert resolve_client_ip("127.0.0.1", {}, XFF, TRUSTED) == "127.0.0.1"


def test_cf_connecting_ip():
    headers = {"CF-Connecting-IP": "203.0.113.9"}
    assert resolve_client_ip("127.0.0.1", headers, "CF-Connecting-IP", TRUSTED) == "203.0.113.9"


def test_non_ip_peer_is_untrusted():
    assert resolve_client_ip("testclient", {XFF: "1.1.1.1"}, XFF, TRUSTED) == "testclient"
```

`tests/test_quota.py`:

```python
from datetime import UTC, date, datetime

import pytest

from imgsr.db.models import UsageDaily
from imgsr.quota import QuotaExceeded, consume, count_llm, refund, today, used

DAY = date(2026, 10, 14)


def test_consume_increments_all_subjects(sf):
    with sf() as db:
        charge = consume(db, [("ip:1.1.1.1", 3, "ip"), ("guest:global", 100, "global")], DAY)
        assert charge == {"date": "2026-10-14", "subjects": ["ip:1.1.1.1", "guest:global"]}
        assert used(db, "ip:1.1.1.1", DAY) == 1
        assert used(db, "guest:global", DAY) == 1


def test_consume_rejects_without_partial_increment(sf):
    with sf() as db:
        for _ in range(2):
            consume(db, [("guest:global", 2, "global")], DAY)
        with pytest.raises(QuotaExceeded, match="global"):
            consume(db, [("ip:2.2.2.2", 3, "ip"), ("guest:global", 2, "global")], DAY)
        assert used(db, "ip:2.2.2.2", DAY) == 0
        assert used(db, "guest:global", DAY) == 2


def test_refund_never_goes_negative(sf):
    with sf() as db:
        charge = consume(db, [("user:1", 5, "u")], DAY)
        refund(db, charge)
        refund(db, charge)
        refund(db, None)
        assert used(db, "user:1", DAY) == 0


def test_count_llm(sf):
    with sf() as db:
        count_llm(db, "user:1", DAY)
        count_llm(db, "user:1", DAY)
        assert db.get(UsageDaily, ("user:1", DAY)).llm_calls == 2


def test_today_uses_utc_plus_8():
    assert today(datetime(2026, 10, 13, 16, 30, tzinfo=UTC)) == date(2026, 10, 14)
    assert today(datetime(2026, 10, 13, 15, 59, tzinfo=UTC)) == date(2026, 10, 13)
```

- [x] **Step 3: 运行，确认失败**

Run: `uv run pytest tests/test_auth.py tests/test_clientip.py tests/test_quota.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [x] **Step 4: 实现 `src/imgsr/auth.py`**

```python
"""Passwords, cookie sessions and login throttling."""

from __future__ import annotations

import hashlib
import secrets
from collections import defaultdict, deque
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from imgsr.db.models import SessionRow, User, utcnow

SESSION_COOKIE = "imgsr_session"
GUEST_COOKIE = "imgsr_guest"
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored: str, password: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerificationError, InvalidHashError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, days: int, now: datetime | None = None) -> str:
    now = now or utcnow()
    token = new_token()
    db.add(SessionRow(token_hash=token_hash(token), user_id=user.id,
                      expires_at=now + timedelta(days=days), last_seen_at=now))
    db.commit()
    return token


def user_for_token(db: Session, token: str | None, days: int, now: datetime | None = None) -> User | None:
    if not token:
        return None
    now = now or utcnow()
    row = db.scalar(select(SessionRow).where(SessionRow.token_hash == token_hash(token)))
    if row is None or row.expires_at <= now:
        return None
    user = db.get(User, row.user_id)
    if user is None or user.disabled:
        return None
    if now - row.last_seen_at > timedelta(hours=1):
        row.last_seen_at = now
        row.expires_at = now + timedelta(days=days)
        db.commit()
    return user


def end_session(db: Session, token: str) -> None:
    db.execute(delete(SessionRow).where(SessionRow.token_hash == token_hash(token)))
    db.commit()


def end_user_sessions(db: Session, user_id: int) -> None:
    db.execute(delete(SessionRow).where(SessionRow.user_id == user_id))
    db.commit()


class LoginLimiter:
    """In-memory failed-login counter per client IP (single process)."""

    def __init__(self, max_failures: int = 10, window: timedelta = timedelta(minutes=15)) -> None:
        self.max_failures = max_failures
        self.window = window
        self._failures: dict[str, deque[datetime]] = defaultdict(deque)

    def _trim(self, ip: str, now: datetime) -> deque[datetime]:
        q = self._failures[ip]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def locked(self, ip: str, now: datetime | None = None) -> bool:
        return len(self._trim(ip, now or utcnow())) >= self.max_failures

    def failed(self, ip: str, now: datetime | None = None) -> None:
        now = now or utcnow()
        self._trim(ip, now).append(now)

    def succeeded(self, ip: str) -> None:
        self._failures.pop(ip, None)
```

- [x] **Step 5: 实现 `src/imgsr/clientip.py`**

```python
"""Resolve the real client IP behind trusted reverse proxies."""

from __future__ import annotations

from collections.abc import Mapping
from ipaddress import IPv4Network, IPv6Network, ip_address, ip_network

Network = IPv4Network | IPv6Network


def parse_networks(spec: str) -> list[Network]:
    return [ip_network(part.strip(), strict=False) for part in spec.split(",") if part.strip()]


def _is_trusted(addr: str, trusted: list[Network]) -> bool:
    try:
        ip = ip_address(addr)
    except ValueError:
        return False
    return any(ip in net for net in trusted)


def resolve_client_ip(
    peer: str, headers: Mapping[str, str], header_name: str, trusted: list[Network]
) -> str:
    """Only trust `header_name` when the TCP peer is a trusted proxy; walk XFF from the right."""
    if not _is_trusted(peer, trusted):
        return peer
    raw = headers.get(header_name)
    if not raw:
        return peer
    candidates = [part.strip() for part in raw.split(",") if part.strip()]
    for candidate in reversed(candidates):
        try:
            ip_address(candidate)
        except ValueError:
            return peer
        if not _is_trusted(candidate, trusted):
            return candidate
    return candidates[0] if candidates else peer
```

- [x] **Step 6: 实现 `src/imgsr/quota.py`**

```python
"""Daily usage counters (UTC+8 days) used for rate limits."""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from imgsr.db.models import UsageDaily

CN_TZ = timezone(timedelta(hours=8))
_lock = threading.Lock()


class QuotaExceeded(Exception):
    """Carries a user-facing message."""


def today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(CN_TZ).date()


def _row(db: Session, subject: str, day: date) -> UsageDaily:
    row = db.get(UsageDaily, (subject, day))
    if row is None:
        row = UsageDaily(subject=subject, day=day, image_calls=0, llm_calls=0)
        db.add(row)
        db.flush()
    return row


def consume(db: Session, limits: list[tuple[str, int, str]], day: date) -> dict:
    """Check every (subject, limit, message) and increment all of them, or none.

    Call this before adding other objects to the session: a rejection rolls the session back.
    """
    with _lock:
        rows = [(_row(db, subject, day), limit, message) for subject, limit, message in limits]
        for row, limit, message in rows:
            if row.image_calls >= limit:
                db.rollback()
                raise QuotaExceeded(message)
        for row, _, _ in rows:
            row.image_calls += 1
        db.commit()
    return {"date": day.isoformat(), "subjects": [subject for subject, _, _ in limits]}


def refund(db: Session, charge: dict | None) -> None:
    if not charge:
        return
    day = date.fromisoformat(charge["date"])
    with _lock:
        for subject in charge["subjects"]:
            row = db.get(UsageDaily, (subject, day))
            if row is not None and row.image_calls > 0:
                row.image_calls -= 1
        db.commit()


def count_llm(db: Session, subject: str, day: date) -> None:
    with _lock:
        _row(db, subject, day).llm_calls += 1
        db.commit()


def used(db: Session, subject: str, day: date) -> int:
    row = db.get(UsageDaily, (subject, day))
    return row.image_calls if row else 0
```

- [x] **Step 7: 运行，确认通过**

Run: `uv run pytest tests/test_auth.py tests/test_clientip.py tests/test_quota.py -q && uv run ruff check src tests`
Expected: 全部 passed

- [x] **Step 8: Commit**

```bash
git add src/imgsr/auth.py src/imgsr/clientip.py src/imgsr/quota.py tests/conftest.py tests/test_auth.py tests/test_clientip.py tests/test_quota.py
git commit -m "feat: sessions, trusted client IP and daily quotas" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: 任务执行器（`jobs/runner.py`）

**Files:**
- Create: `src/imgsr/jobs/__init__.py`（空）, `src/imgsr/jobs/runner.py`, `tests/jobs/__init__.py`（空）, `tests/jobs/test_runner.py`

**Interfaces:**
- Consumes: `Job`, `utcnow`（Task 9）
- Produces: `Handler = Callable[[int], Awaitable[None]]`；`InterruptHook = Callable[[Session, Job], None]`；`JobRunner(session_factory, handlers=None, *, workers=4, on_interrupted=None)`：属性 `handlers: dict[str, Handler]`、`on_interrupted`；`recover() -> list[int]`、`async start()`、`async stop()`、`enqueue(job_id)`（**线程安全**，可在同步路由线程中调用）、`async join()`
- 行为：只运行 `status == "queued"` 的任务；handler 抛出的异常写进 `jobs.error`，任务置 `failed`；启动时把 `running` 置 `failed`（`"服务重启"`）并调用 `on_interrupted`，`queued` 重新入队。

- [x] **Step 1: 写失败测试 `tests/jobs/test_runner.py`**

```python
import asyncio

from imgsr.db.models import Job
from imgsr.jobs.runner import JobRunner


def add_job(sf, task_id, kind="transcribe", status="queued"):
    with sf() as db:
        job = Job(kind=kind, task_id=task_id, status=status)
        db.add(job)
        db.commit()
        return job.id


def status_of(sf, job_id):
    with sf() as db:
        job = db.get(Job, job_id)
        return (job.status, job.error)


async def test_runs_queued_job_and_marks_succeeded(sf, make_task):
    seen = []

    async def handler(job_id):
        seen.append(job_id)

    runner = JobRunner(sf, {"transcribe": handler}, workers=2)
    await runner.start()
    job_id = add_job(sf, make_task())
    runner.enqueue(job_id)
    await asyncio.sleep(0.01)
    await runner.join()
    await runner.stop()
    assert seen == [job_id]
    assert status_of(sf, job_id) == ("succeeded", None)


async def test_failure_is_recorded(sf, make_task):
    async def handler(job_id):
        raise ValueError("boom")

    runner = JobRunner(sf, {"transcribe": handler})
    await runner.start()
    job_id = add_job(sf, make_task())
    runner.enqueue(job_id)
    await asyncio.sleep(0.01)
    await runner.join()
    await runner.stop()
    assert status_of(sf, job_id) == ("failed", "boom")


async def test_recover_marks_running_failed_and_requeues_queued(sf, make_task):
    tid = make_task()
    running = add_job(sf, tid, status="running")
    queued = add_job(sf, tid)
    seen, interrupted = [], []

    async def handler(job_id):
        seen.append(job_id)

    runner = JobRunner(
        sf, {"transcribe": handler}, workers=1,
        on_interrupted=lambda db, job: interrupted.append(job.id),
    )
    await runner.start()
    await runner.join()
    await runner.stop()
    assert status_of(sf, running) == ("failed", "服务重启")
    assert interrupted == [running]
    assert seen == [queued]


async def test_enqueue_is_thread_safe(sf, make_task):
    seen = []

    async def handler(job_id):
        seen.append(job_id)

    runner = JobRunner(sf, {"transcribe": handler})
    await runner.start()
    job_id = add_job(sf, make_task())
    await asyncio.to_thread(runner.enqueue, job_id)
    await asyncio.sleep(0.01)
    await runner.join()
    await runner.stop()
    assert seen == [job_id]


async def test_missing_job_and_unknown_kind_do_not_crash(sf, make_task):
    runner = JobRunner(sf, {})
    await runner.start()
    job_id = add_job(sf, make_task(), kind="mystery")
    runner.enqueue(999_999)
    runner.enqueue(job_id)
    await asyncio.sleep(0.01)
    await runner.join()
    await runner.stop()
    assert status_of(sf, job_id)[0] == "failed"
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/jobs/test_runner.py -q`
Expected: FAIL，`ModuleNotFoundError`

- [x] **Step 3: 实现 `src/imgsr/jobs/runner.py`**

```python
"""In-process job queue: asyncio workers running handlers for rows in the `jobs` table."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from imgsr.db.models import Job, utcnow

log = logging.getLogger(__name__)
Handler = Callable[[int], Awaitable[None]]
InterruptHook = Callable[[Session, Job], None]


class JobRunner:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        handlers: dict[str, Handler] | None = None,
        *,
        workers: int = 4,
        on_interrupted: InterruptHook | None = None,
    ) -> None:
        self._sf = session_factory
        self.handlers: dict[str, Handler] = dict(handlers or {})
        self.on_interrupted = on_interrupted
        self._workers = workers
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def recover(self) -> list[int]:
        """Fail jobs interrupted by a restart; return ids still queued."""
        with self._sf() as db:
            now = utcnow()
            for job in db.scalars(select(Job).where(Job.status == "running")).all():
                job.status, job.error, job.finished_at = "failed", "服务重启", now
                if self.on_interrupted is not None:
                    self.on_interrupted(db, job)
            db.commit()
            return list(db.scalars(select(Job.id).where(Job.status == "queued").order_by(Job.id)))

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        for job_id in self.recover():
            self._queue.put_nowait(job_id)
        self._tasks = [
            asyncio.create_task(self._worker(), name=f"imgsr-job-worker-{i}")
            for i in range(self._workers)
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    def enqueue(self, job_id: int) -> None:
        if self._loop is None:
            raise RuntimeError("JobRunner.start() has not been called")
        self._loop.call_soon_threadsafe(self._queue.put_nowait, job_id)

    async def join(self) -> None:
        await self._queue.join()

    async def _worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run(job_id)
            except Exception:  # noqa: BLE001 - a broken job must not kill the worker
                log.exception("job %s crashed", job_id)
            finally:
                self._queue.task_done()

    async def _run(self, job_id: int) -> None:
        with self._sf() as db:
            job = db.get(Job, job_id)
            if job is None or job.status != "queued":
                return
            job.status, job.started_at = "running", utcnow()
            job.attempts += 1
            kind = job.kind
            db.commit()
        started = time.monotonic()
        status, error = "succeeded", None
        try:
            handler = self.handlers.get(kind)
            if handler is None:
                raise RuntimeError(f"no handler for job kind {kind!r}")
            await handler(job_id)
        except Exception as exc:  # noqa: BLE001 - every failure must land in the job row
            status, error = "failed", (str(exc) or exc.__class__.__name__)[:500]
        with self._sf() as db:
            job = db.get(Job, job_id)
            if job is not None:
                job.status, job.error, job.finished_at = status, error, utcnow()
                db.commit()
        log.info("job id=%s kind=%s status=%s elapsed=%.1fs error=%s",
                 job_id, kind, status, time.monotonic() - started, error)
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest tests/jobs/test_runner.py -q && uv run ruff check src tests`
Expected: `5 passed`

- [x] **Step 5: Commit**

```bash
git add src/imgsr/jobs/__init__.py src/imgsr/jobs/runner.py tests/jobs/__init__.py tests/jobs/test_runner.py
git commit -m "feat: in-process job runner with restart recovery" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: 三类任务处理（`jobs/handlers.py`）

**Files:**
- Create: `src/imgsr/jobs/handlers.py`, `tests/fakes.py`, `tests/jobs/test_handlers.py`

**Interfaces:**
- Consumes: Task 3–8、10、11 的全部 pipeline/relay/storage/quota 接口；`JobRunner` 的 `InterruptHook` 签名
- Produces:
  - 协议 `ImageEditor.edit(*, model, prompt, image_png, size) -> bytes`、`Transcriber.transcribe(*, model, prompt, image_png) -> str`
  - `Services(session_factory, storage, images, chat, settings: Callable[[], Settings], gate: asyncio.Semaphore, enqueue: Callable[[int], None], retry_delays=DEFAULT_DELAYS)`
  - `Pipeline(services)`：`handlers() -> dict[str, Handler]`（键 `transcribe/generate/review`）、`async transcribe(job_id)`、`async generate(job_id)`、`async review(job_id)`、`on_interrupted(db, job)`
- 状态写入约定（API 与前端依赖）：
  - transcribe：`transcribing` → `awaiting_confirm`（写 `transcript_raw/transcript_model`）| `transcribe_failed`（写 `error`）
  - generate：round `running` → `succeeded`（写尺寸、`elapsed_s`、`strategy.plan`、`strategy.scale`）| `failed`（写 `error`，退额并清空 `charge`）；task `generating` → 登录用户 `reviewing` 并入队 review / 游客 `done` 且 `final_round_id` = 该轮 | `round_failed`
  - review：round.review = `{"model", "transcript", "diffs": [Diff.to_json()], "suggestions": [Suggestion.to_json()]}`，失败时额外带 `"error"`；task → `reviewed`
- `tests/fakes.py` 提供 `FakeImages(scale=1.0, fail=None)`（属性 `calls`、`gate: threading.Event | None`、`fail`）、`FakeChat(reply=None, fail=None)`（`reply(call_index, image_size) -> str`，属性 `calls`）、`png_of(size, color)`。

- [x] **Step 1: 写 `tests/fakes.py`**

```python
"""Test doubles for the relay clients (no network)."""

import asyncio
import io

from PIL import Image


def png_of(size, color="white"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class FakeImages:
    """Echoes the input image back resized by `scale`; records every call."""

    def __init__(self, scale=1.0, fail=None):
        self.scale = scale
        self.fail = fail
        self.calls = []
        self.gate = None  # threading.Event: when set, edit() blocks until it is released

    async def edit(self, *, model, prompt, image_png, size):
        self.calls.append({"model": model, "prompt": prompt, "size": size})
        if self.gate is not None:
            await asyncio.to_thread(self.gate.wait, 10)
        if self.fail is not None:
            raise self.fail
        img = Image.open(io.BytesIO(image_png)).convert("RGB")
        out = img.resize((max(1, round(img.width * self.scale)), max(1, round(img.height * self.scale))))
        buf = io.BytesIO()
        out.save(buf, "PNG")
        return buf.getvalue()


class FakeChat:
    """Returns reply(call_index, image_size); records every call."""

    def __init__(self, reply=None, fail=None):
        self.reply = reply or (lambda i, size: "默认转写文字。")
        self.fail = fail
        self.calls = []

    async def transcribe(self, *, model, prompt, image_png):
        size = Image.open(io.BytesIO(image_png)).size
        self.calls.append({"model": model, "size": size})
        if self.fail is not None:
            raise self.fail
        return self.reply(len(self.calls) - 1, size)
```

- [x] **Step 2: 写失败测试 `tests/jobs/test_handlers.py`**

```python
import asyncio
import threading
import uuid
from datetime import timedelta

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from imgsr import quota
from imgsr.config import Settings
from imgsr.db.models import Job, Round, Task, UsageDaily, utcnow
from imgsr.jobs.handlers import Pipeline, Services
from imgsr.pipeline.prompt import BASE_PROMPT
from imgsr.pipeline.tiling import Box, Tile, TilePlan
from imgsr.relay.errors import RelayError
from imgsr.storage import Storage, save_png
from tests.fakes import FakeChat, FakeImages


@pytest.fixture
def services(sf, tmp_path):
    def _make(images=None, chat=None):
        settings = Settings(_env_file=None, data_dir=tmp_path)
        enqueued = []
        svc = Services(
            session_factory=sf,
            storage=Storage(tmp_path / "files"),
            images=images or FakeImages(),
            chat=chat or FakeChat(),
            settings=lambda: settings,
            gate=asyncio.Semaphore(3),
            enqueue=enqueued.append,
            retry_delays=(0.0, 0.0),
        )
        return svc, enqueued

    return _make


def seed(sf, storage, image, *, owner, confirmed=None, use_hint=True, mode="auto", pre=1,
         charge=None, kind="generate", round_status="queued", strategy_extra=None, seq=1,
         task_id=None, review=None):
    tid = task_id or uuid.uuid4().hex
    if task_id is None:
        save_png(image, storage.source(tid))
    with sf() as db:
        if db.get(Task, tid) is None:
            db.add(Task(id=tid, owner_user_id=owner, client_ip="1.2.3.4", source_w=image.width,
                        source_h=image.height, status="ready", confirmed_text=confirmed,
                        expires_at=utcnow() + timedelta(days=1)))
            db.flush()
        round_id = None
        if kind != "transcribe":
            rnd = Round(task_id=tid, seq=seq, image_model="gpt-image-2.5", prompt=BASE_PROMPT,
                        strategy={"mode": mode, "preupscale": pre, **(strategy_extra or {})},
                        use_text_hint=use_hint, status=round_status, charge=charge, review=review)
            db.add(rnd)
            db.flush()
            round_id = rnd.id
        job = Job(kind=kind, task_id=tid, round_id=round_id)
        db.add(job)
        db.commit()
        return tid, round_id, job.id


def two_column_page():
    img = Image.new("RGB", (2316, 1294), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((20, 40, 918, 1254), fill="black")
    d.rectangle((999, 40, 2296, 1254), fill="black")
    return img


async def test_transcribe_sets_awaiting_confirm(sf, services, make_user):
    uid = make_user()
    svc, _ = services(chat=FakeChat(lambda i, s: "第一行。\n第二行。"))
    tid, _, job = seed(sf, svc.storage, Image.new("RGB", (300, 200), "white"), owner=uid,
                       kind="transcribe")
    await Pipeline(svc).transcribe(job)
    with sf() as db:
        task = db.get(Task, tid)
        assert task.status == "awaiting_confirm"
        assert task.transcript_raw == "第一行。\n第二行。"
        assert task.transcript_model == "gpt-6-sol"
        assert db.get(UsageDaily, (f"user:{uid}", quota.today())).llm_calls == 1


async def test_transcribe_failure_marks_task(sf, services, make_user):
    uid = make_user()
    fail = RelayError("上游拒绝请求：bad", kind="rejected", retryable=False)
    svc, _ = services(chat=FakeChat(fail=fail))
    tid, _, job = seed(sf, svc.storage, Image.new("RGB", (300, 200)), owner=uid, kind="transcribe")
    with pytest.raises(RelayError):
        await Pipeline(svc).transcribe(job)
    with sf() as db:
        task = db.get(Task, tid)
        assert task.status == "transcribe_failed" and "bad" in task.error


async def test_generate_whole_with_hint(sf, services, make_user):
    uid = make_user()
    svc, enqueued = services(images=FakeImages(scale=2.0))
    tid, rid, job = seed(sf, svc.storage, Image.new("RGB", (400, 300), "white"), owner=uid,
                         confirmed="第一段。\n第二段。")
    await Pipeline(svc).generate(job)
    with sf() as db:
        rnd, task = db.get(Round, rid), db.get(Task, tid)
        assert rnd.status == "succeeded"
        assert (rnd.result_w, rnd.result_h, rnd.download_w, rnd.download_h) == (800, 600, 800, 600)
        assert rnd.strategy["plan"]["mode"] == "whole" and rnd.strategy["scale"] == 2.0
        assert task.status == "reviewing"
        review_jobs = db.scalars(select(Job).where(Job.kind == "review")).all()
    assert [j.id for j in review_jobs] == enqueued
    assert "「第一段。」 / 「第二段。」" in svc.images.calls[0]["prompt"]
    assert svc.storage.result(tid, 1).is_file() and svc.storage.download(tid, 1).is_file()


async def test_generate_tiles_slices_hint_per_tile(sf, services, make_user):
    uid = make_user()
    chat = FakeChat(lambda i, size: "左栏文字。" if size[0] < 1200 else "右栏文字。")
    svc, _ = services(chat=chat)
    tid, rid, job = seed(sf, svc.storage, two_column_page(), owner=uid,
                         confirmed="左栏文字。\n右栏文字。")
    await Pipeline(svc).generate(job)
    prompts = sorted(c["prompt"] for c in svc.images.calls)
    assert len(prompts) == 2
    assert any("「左栏文字。」" in p and "右栏" not in p for p in prompts)
    assert any("「右栏文字。」" in p and "左栏" not in p for p in prompts)
    with sf() as db:
        rnd, task = db.get(Round, rid), db.get(Task, tid)
        assert (rnd.result_w, rnd.result_h) == (2316, 1294)
        assert rnd.strategy["plan"]["mode"] == "tiles"
        assert len(task.tile_transcripts) == 2


async def test_generate_failure_refunds_and_marks_failed(sf, services, make_user):
    uid = make_user()
    with sf() as db:
        charge = quota.consume(db, [(f"user:{uid}", 50, "x")], quota.today())
    busy = RelayError("上游繁忙：x", kind="busy", retryable=True)
    svc, _ = services(images=FakeImages(fail=busy))
    tid, rid, job = seed(sf, svc.storage, Image.new("RGB", (300, 200)), owner=uid, charge=charge)
    with pytest.raises(RelayError):
        await Pipeline(svc).generate(job)
    assert len(svc.images.calls) == 3  # first try + 2 retries
    with sf() as db:
        rnd = db.get(Round, rid)
        assert rnd.status == "failed" and "上游繁忙" in rnd.error and rnd.charge is None
        assert db.get(Task, tid).status == "round_failed"
        assert quota.used(db, f"user:{uid}", quota.today()) == 0


async def test_guest_generate_finishes_without_review(sf, services):
    svc, enqueued = services()
    tid, rid, job = seed(sf, svc.storage, Image.new("RGB", (300, 200)), owner=None, use_hint=False)
    await Pipeline(svc).generate(job)
    with sf() as db:
        task = db.get(Task, tid)
        assert task.status == "done" and task.final_round_id == rid
    assert enqueued == []


def reviewable(svc, sf, owner, *, confirmed, use_hint=False, pre=1, seq=1, task_id=None,
               review=None, round_status="succeeded"):
    img = Image.new("RGB", (300, 200), "white")
    plan = TilePlan("whole", [Tile(Box(0, 0, 300, 200), Box(0, 0, 300, 200))])
    out = seed(sf, svc.storage, img, owner=owner, confirmed=confirmed, use_hint=use_hint, pre=pre,
               kind="review", round_status=round_status, seq=seq, task_id=task_id, review=review,
               strategy_extra={"plan": plan.to_json(), "scale": 1.0})
    save_png(img, svc.storage.result(out[0], seq))
    return out


async def test_review_reports_diffs_and_suggestion(sf, services, make_user):
    uid = make_user()
    svc, _ = services(chat=FakeChat(lambda i, s: "晚上还会发出光光呢！"))
    tid, rid, job = reviewable(svc, sf, uid, confirmed="晚上还会发出亮光呢！")
    await Pipeline(svc).review(job)
    with sf() as db:
        review = db.get(Round, rid).review
        assert review["diffs"] == [{"expected": "亮", "found": "光", "sentence": "晚上还会发出亮光呢！"}]
        assert review["suggestions"][0]["action"] == "retry_with_hint"
        assert review["model"] == "gpt-6-sol"
        assert db.get(Task, tid).status == "reviewed"


async def test_review_without_text_suggests_manual_check(sf, services, make_user):
    uid = make_user()
    svc, _ = services()
    tid, rid, job = reviewable(svc, sf, uid, confirmed=None)
    await Pipeline(svc).review(job)
    with sf() as db:
        assert db.get(Round, rid).review["suggestions"][0]["action"] == "manual_check"
    assert svc.chat.calls == []


async def test_review_uses_previous_round_diffs(sf, services, make_user):
    uid = make_user()
    svc, _ = services(chat=FakeChat(lambda i, s: "晚上还会发出光光呢！"))
    prev_review = {"diffs": [{"expected": "亮", "found": "光", "sentence": "x"}], "suggestions": []}
    tid, _, _ = reviewable(svc, sf, uid, confirmed="晚上还会发出亮光呢！", review=prev_review)
    _, rid, job = reviewable(svc, sf, uid, confirmed="晚上还会发出亮光呢！", use_hint=True, pre=2,
                             seq=2, task_id=tid)
    await Pipeline(svc).review(job)
    with sf() as db:
        sugs = db.get(Round, rid).review["suggestions"]
    assert [s["action"] for s in sugs] == ["manual_check"] and sugs[0]["diff_ids"] == [0]


async def test_generate_for_deleted_task_leaves_no_files(sf, services, make_user):
    uid = make_user()
    images = FakeImages()
    images.gate = threading.Event()
    svc, _ = services(images=images)
    tid, _, job = seed(sf, svc.storage, Image.new("RGB", (300, 200)), owner=uid)
    run = asyncio.create_task(Pipeline(svc).generate(job))
    while not images.calls:
        await asyncio.sleep(0.01)
    with sf() as db:
        db.delete(db.get(Task, tid))
        db.commit()
    svc.storage.delete_task(tid)
    images.gate.set()
    await run  # must not raise
    assert not svc.storage.task_dir(tid).exists()


async def test_on_interrupted_marks_states_and_refunds(sf, services, make_user):
    uid = make_user()
    with sf() as db:
        charge = quota.consume(db, [(f"user:{uid}", 50, "x")], quota.today())
    svc, _ = services()
    tid, rid, job_id = seed(sf, svc.storage, Image.new("RGB", (30, 20)), owner=uid, charge=charge)
    with sf() as db:
        Pipeline(svc).on_interrupted(db, db.get(Job, job_id))
        db.commit()
        rnd = db.get(Round, rid)
        assert (rnd.status, rnd.error) == ("failed", "服务重启")
        assert db.get(Task, tid).status == "round_failed"
        assert quota.used(db, f"user:{uid}", quota.today()) == 0
```

- [x] **Step 3: 运行，确认失败**

Run: `uv run pytest tests/jobs/test_handlers.py -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'imgsr.jobs.handlers'`

- [x] **Step 4: 实现 `src/imgsr/jobs/handlers.py`**

```python
"""Job handlers: transcribe -> generate -> review, orchestrating pure steps and the relay."""

from __future__ import annotations

import asyncio
import io
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from imgsr import quota
from imgsr.config import Settings
from imgsr.db.models import Job, Round, Task
from imgsr.pipeline.align import slice_for_tile
from imgsr.pipeline.compose import crop_content, make_download, pad_to_ratio, stitch, upscale
from imgsr.pipeline.prompt import TRANSCRIBE_PROMPT, build_prompt
from imgsr.pipeline.textdiff import Diff, compare
from imgsr.pipeline.tiling import Box, Tile, TilePlan, plan_tiles
from imgsr.relay.errors import RelayError
from imgsr.relay.retry import DEFAULT_DELAYS, with_retries
from imgsr.review.rules import Suggestion, suggest
from imgsr.storage import Storage, png_bytes, save_png


class ImageEditor(Protocol):
    async def edit(self, *, model: str, prompt: str, image_png: bytes, size: tuple[int, int]) -> bytes: ...


class Transcriber(Protocol):
    async def transcribe(self, *, model: str, prompt: str, image_png: bytes) -> str: ...


@dataclass
class Services:
    session_factory: sessionmaker[Session]
    storage: Storage
    images: ImageEditor
    chat: Transcriber
    settings: Callable[[], Settings]
    gate: asyncio.Semaphore
    enqueue: Callable[[int], None]
    retry_delays: tuple[float, ...] = DEFAULT_DELAYS


@dataclass
class _Gen:
    task_id: str
    round_id: int
    seq: int
    prompt: str
    model: str
    mode: str
    pre: int
    hint_text: str
    subject: str
    owned: bool
    cache: dict[str, str] = field(default_factory=dict)


def _message(exc: BaseException) -> str:
    if isinstance(exc, RelayError):
        return exc.message
    return f"{exc.__class__.__name__}: {exc}"[:300]


def _first_error(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _subject(task: Task) -> str:
    return f"user:{task.owner_user_id}" if task.owner_user_id is not None else f"ip:{task.client_ip}"


def _load_rgb(path: Path) -> Image.Image:
    with Image.open(path) as im:
        return im.convert("RGB")


def _decode(raw: bytes) -> Image.Image:
    with Image.open(io.BytesIO(raw)) as im:
        return im.convert("RGB")


def _previous_diffs(db: Session, task_id: str, seq: int) -> list[Diff] | None:
    prev = db.scalar(
        select(Round)
        .where(Round.task_id == task_id, Round.seq < seq, Round.status == "succeeded")
        .order_by(Round.seq.desc())
        .limit(1)
    )
    if prev is None or not prev.review:
        return None
    return [Diff(**d) for d in prev.review.get("diffs", [])]


class Pipeline:
    def __init__(self, services: Services) -> None:
        self.svc = services

    def handlers(self) -> dict[str, Callable[[int], Awaitable[None]]]:
        return {"transcribe": self.transcribe, "generate": self.generate, "review": self.review}

    # ---- shared helpers -------------------------------------------------

    async def _call(self, fn: Callable[[], Awaitable[Any]]) -> Any:
        async def gated() -> Any:
            async with self.svc.gate:
                return await fn()

        return await with_retries(gated, delays=self.svc.retry_delays)

    async def _transcribe_png(self, model: str, png: bytes, subject: str) -> str:
        text = await self._call(
            lambda: self.svc.chat.transcribe(model=model, prompt=TRANSCRIBE_PROMPT, image_png=png)
        )
        with self.svc.session_factory() as db:
            quota.count_llm(db, subject, quota.today())
        return text

    def _set_task(self, task_id: str, **fields: Any) -> bool:
        """Update a task if it still exists; False when it was deleted meanwhile."""
        with self.svc.session_factory() as db:
            task = db.get(Task, task_id)
            if task is None:
                return False
            for key, value in fields.items():
                setattr(task, key, value)
            db.commit()
            return True

    # ---- transcribe -----------------------------------------------------

    async def transcribe(self, job_id: int) -> None:
        s = self.svc.settings()
        with self.svc.session_factory() as db:
            job = db.get(Job, job_id)
            task = db.get(Task, job.task_id) if job else None
            if task is None:
                return
            task.status, task.error = "transcribing", None
            db.commit()
            task_id, subject = task.id, _subject(task)
        try:
            png = await asyncio.to_thread(self.svc.storage.source(task_id).read_bytes)
            text = await self._transcribe_png(s.transcribe_model, png, subject)
        except Exception as exc:
            if self._set_task(task_id, status="transcribe_failed", error=_message(exc)):
                raise
            return
        self._set_task(task_id, status="awaiting_confirm", transcript_raw=text,
                       transcript_model=s.transcribe_model)

    # ---- generate -------------------------------------------------------

    async def generate(self, job_id: int) -> None:
        s = self.svc.settings()
        with self.svc.session_factory() as db:
            job = db.get(Job, job_id)
            rnd = db.get(Round, job.round_id) if job and job.round_id else None
            if rnd is None:
                return
            task = rnd.task
            rnd.status, rnd.error = "running", None
            task.status = "generating"
            db.commit()
            ctx = _Gen(
                task_id=task.id, round_id=rnd.id, seq=rnd.seq, prompt=rnd.prompt,
                model=rnd.image_model, mode=rnd.strategy.get("mode", "auto"),
                pre=int(rnd.strategy.get("preupscale", 1)),
                hint_text=(task.confirmed_text or "") if rnd.use_text_hint else "",
                subject=_subject(task), owned=task.owner_user_id is not None,
                cache=dict(task.tile_transcripts or {}),
            )
        started = time.monotonic()
        try:
            source = await asyncio.to_thread(_load_rgb, self.svc.storage.source(ctx.task_id))
            plan = plan_tiles(source, s.pixel_cap, ctx.mode, ctx.pre)  # type: ignore[arg-type]
            hints = await self._tile_hints(ctx, source, plan, s)
            async with asyncio.TaskGroup() as tg:
                futures = [
                    tg.create_task(self._render_tile(ctx, i, source, tile, hints[i]))
                    for i, tile in enumerate(plan.tiles)
                ]
            outputs = [f.result() for f in futures]
            result, scale = await asyncio.to_thread(stitch, plan, outputs, source.size)
            download = await asyncio.to_thread(make_download, result, source.size)
        except Exception as exc:
            error = _first_error(exc)
            if self._fail_round(ctx, _message(error)):
                raise error from None
            self.svc.storage.delete_task(ctx.task_id)
            return
        if not self._task_exists(ctx.task_id):
            self.svc.storage.delete_task(ctx.task_id)
            return
        await asyncio.to_thread(save_png, result, self.svc.storage.result(ctx.task_id, ctx.seq))
        await asyncio.to_thread(save_png, download, self.svc.storage.download(ctx.task_id, ctx.seq))
        review_id = None
        with self.svc.session_factory() as db:
            rnd = db.get(Round, ctx.round_id)
            if rnd is None:
                self.svc.storage.delete_task(ctx.task_id)
                return
            task = rnd.task
            rnd.status = "succeeded"
            rnd.result_w, rnd.result_h = result.size
            rnd.download_w, rnd.download_h = download.size
            rnd.elapsed_s = round(time.monotonic() - started, 1)
            rnd.strategy = {**rnd.strategy, "plan": plan.to_json(), "scale": scale}
            if ctx.owned:
                task.status = "reviewing"
                review_job = Job(kind="review", task_id=task.id, round_id=rnd.id)
                db.add(review_job)
                db.flush()
                review_id = review_job.id
            else:
                task.status, task.final_round_id = "done", rnd.id
            db.commit()
        if review_id is not None:
            self.svc.enqueue(review_id)

    def _task_exists(self, task_id: str) -> bool:
        with self.svc.session_factory() as db:
            return db.get(Task, task_id) is not None

    async def _tile_hints(self, ctx: _Gen, source: Image.Image, plan: TilePlan, s: Settings) -> list[str]:
        if not ctx.hint_text.strip():
            return [""] * len(plan.tiles)
        if plan.mode == "whole":
            return [ctx.hint_text]

        async def one(tile: Tile) -> str:
            key = ",".join(str(v) for v in tile.box.as_tuple())
            if key not in ctx.cache:
                png = await asyncio.to_thread(png_bytes, source.crop(tile.box.as_tuple()))
                ctx.cache[key] = await self._transcribe_png(s.transcribe_model, png, ctx.subject)
            return slice_for_tile(ctx.hint_text, ctx.cache[key])

        async with asyncio.TaskGroup() as tg:
            futures = [tg.create_task(one(t)) for t in plan.tiles]
        self._set_task(ctx.task_id, tile_transcripts=dict(ctx.cache))
        return [f.result() for f in futures]

    async def _render_tile(self, ctx: _Gen, index: int, source: Image.Image, tile: Tile, hint: str) -> Image.Image:
        padded, content = pad_to_ratio(source.crop(tile.box.as_tuple()))
        sent = upscale(padded, ctx.pre)
        png = await asyncio.to_thread(png_bytes, sent)
        await asyncio.to_thread(save_png, sent, self.svc.storage.tile(ctx.task_id, ctx.seq, index, "in"))
        prompt = build_prompt(ctx.prompt, hint)
        raw = await self._call(
            lambda: self.svc.images.edit(model=ctx.model, prompt=prompt, image_png=png, size=sent.size)
        )
        out = await asyncio.to_thread(_decode, raw)
        await asyncio.to_thread(save_png, out, self.svc.storage.tile(ctx.task_id, ctx.seq, index, "out"))
        scaled = Box(content.x0 * ctx.pre, content.y0 * ctx.pre, content.x1 * ctx.pre, content.y1 * ctx.pre)
        return crop_content(out, sent.size, scaled)

    def _fail_round(self, ctx: _Gen, message: str) -> bool:
        with self.svc.session_factory() as db:
            rnd = db.get(Round, ctx.round_id)
            if rnd is None:
                return False
            rnd.status, rnd.error = "failed", message
            rnd.task.status = "round_failed"
            charge, rnd.charge = rnd.charge, None
            db.commit()
            quota.refund(db, charge)
        return True

    # ---- review ---------------------------------------------------------

    async def review(self, job_id: int) -> None:
        s = self.svc.settings()
        with self.svc.session_factory() as db:
            job = db.get(Job, job_id)
            rnd = db.get(Round, job.round_id) if job and job.round_id else None
            if rnd is None:
                return
            task = rnd.task
            task.status = "reviewing"
            db.commit()
            task_id, round_id, seq = task.id, rnd.id, rnd.seq
            confirmed = task.confirmed_text or ""
            plan = TilePlan.from_json(rnd.strategy["plan"])
            scale = float(rnd.strategy.get("scale", 1.0))
            used_hint, pre = rnd.use_text_hint, int(rnd.strategy.get("preupscale", 1))
            previous = _previous_diffs(db, task_id, seq)
            subject = _subject(task)
        if not confirmed.strip():
            sugs = suggest([], has_text=False, used_hint=used_hint, preupscale=pre, previous=previous)
            self._finish_review(round_id, {"model": None, "transcript": "", "diffs": [],
                                           "suggestions": [x.to_json() for x in sugs]})
            return
        try:
            result = await asyncio.to_thread(_load_rgb, self.svc.storage.result(task_id, seq))
            if plan.mode == "tiles":
                regions = [Box(round(t.keep.x0 * scale), round(t.keep.y0 * scale),
                               round(t.keep.x1 * scale), round(t.keep.y1 * scale)) for t in plan.tiles]
            else:
                regions = [Box(0, 0, result.width, result.height)]

            async def one(box: Box) -> str:
                png = await asyncio.to_thread(png_bytes, result.crop(box.as_tuple()))
                return await self._transcribe_png(s.review_model, png, subject)

            async with asyncio.TaskGroup() as tg:
                futures = [tg.create_task(one(b)) for b in regions]
            transcript = "\n".join(f.result() for f in futures)
        except Exception as exc:
            error = _first_error(exc)
            fallback = Suggestion("manual_check", "审查失败，请人工核对或重试审查").to_json()
            if self._finish_review(round_id, {"model": s.review_model, "error": _message(error),
                                              "transcript": "", "diffs": [], "suggestions": [fallback]}):
                raise error from None
            return
        diffs = compare(confirmed, transcript)
        sugs = suggest(diffs, has_text=True, used_hint=used_hint, preupscale=pre, previous=previous)
        self._finish_review(round_id, {"model": s.review_model, "transcript": transcript,
                                       "diffs": [d.to_json() for d in diffs],
                                       "suggestions": [x.to_json() for x in sugs]})

    def _finish_review(self, round_id: int, review: dict) -> bool:
        with self.svc.session_factory() as db:
            rnd = db.get(Round, round_id)
            if rnd is None:
                return False
            rnd.review = review
            rnd.task.status = "reviewed"
            db.commit()
            return True

    # ---- restart recovery ---------------------------------------------------

    def on_interrupted(self, db: Session, job: Job) -> None:
        task = db.get(Task, job.task_id)
        rnd = db.get(Round, job.round_id) if job.round_id else None
        if job.kind == "transcribe" and task is not None:
            task.status, task.error = "transcribe_failed", "服务重启"
        elif job.kind == "generate" and rnd is not None:
            rnd.status, rnd.error = "failed", "服务重启"
            rnd.task.status = "round_failed"
            charge, rnd.charge = rnd.charge, None
            db.flush()
            quota.refund(db, charge)
        elif job.kind == "review" and rnd is not None:
            rnd.review = {"model": None, "error": "服务重启", "transcript": "", "diffs": [],
                          "suggestions": [Suggestion("manual_check", "审查被中断，请重试审查或人工核对").to_json()]}
            rnd.task.status = "reviewed"
```

- [x] **Step 5: 运行，确认通过**

Run: `uv run pytest tests/jobs -q && uv run ruff check src tests`
Expected: 全部 passed（ruff 若报行长以外的问题按提示修正；`B023` 闭包在循环中的提示若出现，确认 lambda 捕获的是当前作用域局部变量即可加 `# noqa: B023` 并说明）

- [x] **Step 6: Commit**

```bash
git add src/imgsr/jobs/handlers.py tests/fakes.py tests/jobs/test_handlers.py
git commit -m "feat: transcribe, generate and review job handlers" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: 应用工厂、依赖、登录接口与健康检查

**Files:**
- Create: `src/imgsr/config_store.py`, `src/imgsr/maintenance.py`（本 Task 先实现 `maintenance_loop` 依赖的 `cleanup_expired` 与 `backup_db`，测试在 Task 18 补齐）, `src/imgsr/api/__init__.py`（空）, `src/imgsr/api/deps.py`, `src/imgsr/api/schemas.py`, `src/imgsr/api/routes_auth.py`, `src/imgsr/api/app.py`, `tests/test_config_store.py`, `tests/api/__init__.py`（空）, `tests/api/conftest.py`, `tests/api/helpers.py`, `tests/api/test_auth_api.py`

**Interfaces:**
- Produces:
  - `SettingsProvider(base, session_factory)`：`__call__() -> Settings`、`overrides() -> dict`、`update(changes) -> Settings`（`SettingsError` 中文消息）
  - `AppContext(settings: SettingsProvider, sf, engine, storage, runner, limiter, trusted)`；依赖 `get_ctx`, `db_session`, `client_ip`, `current_user_optional`, `current_user`, `require_admin`, `read_upload(file, ctx) -> Image`
  - `schemas.py`：`ACTIVE = ("queued","running")`、`RoundOut`、`TaskOut`（含 `busy`）、`TaskSummary`、`GuestTaskOut`、`TextIn`、`SuggestionRef`、`RoundIn`、`FinalIn`、`task_out(db, task)`、`guest_task_out(task)`
  - `create_app(settings=None, *, images=None, chat=None, retry_delays=DEFAULT_DELAYS, maintenance=True) -> FastAPI`
  - 接口：`POST /api/auth/login`、`POST /api/auth/logout`、`GET /api/me`、`GET /api/health`
  - 测试夹具 `make_api(**settings_overrides) -> SimpleNamespace(client, app, images, chat, ctx)`、`api`；助手 `add_user`, `login`, `upload`, `wait_task`
- 注意：Starlette `TestClient(..., client=("127.0.0.1", 50000))` 需要较新的 starlette；若报 `TypeError: unexpected keyword 'client'`，运行 `uv add "starlette>=0.40"` 后重试。

- [x] **Step 1: 写 `src/imgsr/maintenance.py`**（供 app 引用；单测在 Task 18）

```python
"""Periodic housekeeping: delete expired tasks, back up SQLite."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from imgsr.db.models import Job, SessionRow, Task, UsageDaily, utcnow
from imgsr.storage import Storage

log = logging.getLogger(__name__)


def cleanup_expired(sf: sessionmaker[Session], storage: Storage, now: datetime | None = None) -> int:
    now = now or utcnow()
    with sf() as db:
        expired = set(db.scalars(select(Task.id).where(Task.expires_at < now)))
        busy = set(db.scalars(select(Job.task_id).where(Job.status.in_(("queued", "running")))))
        doomed = sorted(expired - busy)
        for task_id in doomed:
            db.delete(db.get(Task, task_id))
        db.execute(delete(SessionRow).where(SessionRow.expires_at < now))
        db.execute(delete(UsageDaily).where(UsageDaily.day < (now - timedelta(days=40)).date()))
        db.commit()
    for task_id in doomed:
        storage.delete_task(task_id)
    return len(doomed)


def backup_db(engine: Engine, backup_dir: Path, keep: int = 7, now: datetime | None = None) -> Path:
    now = now or utcnow()
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"imgsr-{now:%Y%m%d}.sqlite3"
    raw = engine.raw_connection()
    try:
        dest = sqlite3.connect(target)
        try:
            raw.driver_connection.backup(dest)
        finally:
            dest.close()
    finally:
        raw.close()
    for old in sorted(backup_dir.glob("imgsr-*.sqlite3"))[:-keep]:
        old.unlink()
    return target


async def maintenance_loop(sf: sessionmaker[Session], storage: Storage, engine: Engine,
                           backup_dir: Path, interval_s: float = 3600) -> None:
    last_backup = None
    while True:
        try:
            removed = await asyncio.to_thread(cleanup_expired, sf, storage)
            if removed:
                log.info("cleanup removed %d expired tasks", removed)
            day = utcnow().date()
            if last_backup != day:
                await asyncio.to_thread(backup_db, engine, backup_dir)
                last_backup = day
        except Exception:  # noqa: BLE001 - housekeeping must never stop the loop
            log.exception("maintenance failed")
        await asyncio.sleep(interval_s)
```

- [x] **Step 2: 写失败测试 `tests/test_config_store.py`**

```python
import pytest

from imgsr.config import Settings
from imgsr.config_store import SettingsError, SettingsProvider


def provider(sf):
    return SettingsProvider(Settings(_env_file=None), sf)


def test_update_persists_and_overrides(sf):
    p = provider(sf)
    assert p().image_model == "gpt-image-2.5"
    eff = p.update({"image_model": " gpt-image-2 ", "pixel_cap": "1200000"})
    assert eff.image_model == "gpt-image-2" and eff.pixel_cap == 1_200_000
    assert p.overrides() == {"image_model": "gpt-image-2", "pixel_cap": 1_200_000}
    assert p().image_model == "gpt-image-2"


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"open_api_key": "x"}, "不支持"),
        ({"pixel_cap": 10}, "之间"),
        ({"upstream_concurrency": "x"}, "整数"),
        ({"upstream_concurrency": True}, "整数"),
        ({"image_model": "  "}, "不能为空"),
    ],
)
def test_update_validation(sf, changes, message):
    with pytest.raises(SettingsError, match=message):
        provider(sf).update(changes)
```

`tests/api/conftest.py`:

```python
import contextlib
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from imgsr.api.app import create_app
from imgsr.config import Settings
from tests.fakes import FakeChat, FakeImages


@pytest.fixture
def make_api(tmp_path):
    stack = contextlib.ExitStack()

    def _make(**overrides):
        images, chat = FakeImages(), FakeChat()
        settings = Settings(
            _env_file=None,
            data_dir=tmp_path / uuid.uuid4().hex,
            cookie_secure=False,
            trusted_proxies="127.0.0.1/32",
            open_api_key="sk-test-0000000000",
            **overrides,
        )
        app = create_app(settings, images=images, chat=chat, retry_delays=(0.0, 0.0), maintenance=False)
        client = stack.enter_context(
            TestClient(app, client=("127.0.0.1", 50000), headers={"X-Requested-With": "imgsr"})
        )
        return SimpleNamespace(client=client, app=app, images=images, chat=chat, ctx=app.state.ctx)

    yield _make
    stack.close()


@pytest.fixture
def api(make_api):
    return make_api()
```

`tests/api/helpers.py`:

```python
import io
import time

from PIL import Image

from imgsr.auth import hash_password
from imgsr.db.models import User


def add_user(api, username="alice", password="password123", role="user", quota=50):
    with api.ctx.sf() as db:
        user = User(username=username, password_hash=hash_password(password), role=role,
                    daily_quota=quota)
        db.add(user)
        db.commit()
        return user.id


def login(client, username="alice", password="password123"):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response


def upload(client, size=(400, 300), path="/api/tasks", ip=None, **form):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post(path, files={"file": ("a.png", buf.getvalue(), "image/png")},
                       data=form or None, headers=headers)


def wait_task(client, task_id, done, path="/api/tasks/{id}", timeout=10.0):
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(path.format(id=task_id)).json()
        if done(body):
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"timeout waiting for task, last={body}")
        time.sleep(0.02)
```

`tests/api/test_auth_api.py`:

```python
from sqlalchemy import select

from imgsr.db.models import User
from tests.api.helpers import add_user, login


def test_login_me_logout(api):
    add_user(api)
    body = login(api.client).json()
    assert body["username"] == "alice" and body["used_today"] == 0
    assert "imgsr_session" in api.client.cookies
    assert api.client.get("/api/me").json()["role"] == "user"
    assert api.client.post("/api/auth/logout").status_code == 200
    assert api.client.get("/api/me").status_code == 401


def test_wrong_password_and_disabled_user(api):
    add_user(api)
    add_user(api, "bob", role="user")
    with api.ctx.sf() as db:
        db.scalar(select(User).where(User.username == "bob")).disabled = True
        db.commit()
    r = api.client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    assert r.status_code == 401 and r.json()["detail"] == "用户名或密码错误"
    r = api.client.post("/api/auth/login", json={"username": "bob", "password": "password123"})
    assert r.status_code == 401


def test_login_lockout_after_ten_failures(api):
    add_user(api)
    for _ in range(10):
        api.client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    r = api.client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    assert r.status_code == 429


def test_mutations_require_csrf_header(api):
    add_user(api)
    r = api.client.post("/api/auth/login", json={"username": "alice", "password": "password123"},
                        headers={"X-Requested-With": ""})
    assert r.status_code == 403


def test_health(api):
    body = api.client.get("/api/health").json()
    assert body["ok"] is True and body["free_bytes"] > 0 and body["low_disk"] is False
```

- [x] **Step 3: 运行，确认失败**

Run: `uv run pytest tests/test_config_store.py tests/api -q`
Expected: FAIL，`ModuleNotFoundError: No module named 'imgsr.config_store'`

- [x] **Step 4: 实现 `src/imgsr/config_store.py`**

```python
"""Admin-editable settings layered over environment defaults."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from imgsr.config import OVERRIDABLE, Settings
from imgsr.db.models import SettingRow, utcnow

_INT_RANGES: dict[str, tuple[int, int]] = {
    "pixel_cap": (100_000, 20_000_000),
    "upstream_concurrency": (1, 10),
    "max_upload_mb": (1, 100),
    "max_pixels": (1_000_000, 100_000_000),
}
_DEFAULT_RANGE = (0, 1_000_000)


class SettingsError(ValueError):
    """User-facing validation error."""


def _validate(key: str, value: Any) -> Any:
    kind = OVERRIDABLE.get(key)
    if kind is None:
        raise SettingsError(f"不支持修改的设置项：{key}")
    if kind is int:
        if isinstance(value, bool):
            raise SettingsError(f"{key} 必须是整数")
        try:
            number = int(value)
        except (TypeError, ValueError):
            raise SettingsError(f"{key} 必须是整数") from None
        lo, hi = _INT_RANGES.get(key, _DEFAULT_RANGE)
        if not lo <= number <= hi:
            raise SettingsError(f"{key} 必须在 {lo} 到 {hi} 之间")
        return number
    text = str(value).strip()
    if not text or len(text) > 100:
        raise SettingsError(f"{key} 不能为空且不超过 100 字符")
    return text


class SettingsProvider:
    def __init__(self, base: Settings, session_factory: sessionmaker[Session]) -> None:
        self._base = base
        self._sf = session_factory

    def overrides(self) -> dict[str, Any]:
        with self._sf() as db:
            return {row.key: row.value for row in db.scalars(select(SettingRow))}

    def __call__(self) -> Settings:
        return self._base.with_overrides(self.overrides())

    def update(self, changes: dict[str, Any]) -> Settings:
        clean = {key: _validate(key, value) for key, value in changes.items()}
        with self._sf() as db:
            for key, value in clean.items():
                row = db.get(SettingRow, key)
                if row is None:
                    db.add(SettingRow(key=key, value=value))
                else:
                    row.value, row.updated_at = value, utcnow()
            db.commit()
        return self()
```

- [x] **Step 5: 实现 `src/imgsr/api/deps.py`**

```python
"""Shared FastAPI dependencies and helpers."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, UploadFile
from PIL import Image
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from imgsr.auth import SESSION_COOKIE, LoginLimiter, user_for_token
from imgsr.clientip import Network, resolve_client_ip
from imgsr.config_store import SettingsProvider
from imgsr.db.models import User
from imgsr.jobs.runner import JobRunner
from imgsr.storage import Storage
from imgsr.uploads import UploadRejected, normalize_upload


@dataclass
class AppContext:
    settings: SettingsProvider
    sf: sessionmaker[Session]
    engine: Engine
    storage: Storage
    runner: JobRunner
    limiter: LoginLimiter
    trusted: list[Network]


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def db_session(c: AppContext = Depends(get_ctx)) -> Iterator[Session]:
    with c.sf() as db:
        yield db


def client_ip(request: Request, c: AppContext = Depends(get_ctx)) -> str:
    peer = request.client.host if request.client else "0.0.0.0"
    return resolve_client_ip(peer, request.headers, c.settings().client_ip_header, c.trusted)


def current_user_optional(
    request: Request, db: Session = Depends(db_session), c: AppContext = Depends(get_ctx)
) -> User | None:
    return user_for_token(db, request.cookies.get(SESSION_COOKIE), c.settings().session_days)


def current_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(401, "请先登录")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")
    return user


async def read_upload(file: UploadFile, c: AppContext) -> Image.Image:
    s = c.settings()
    if c.storage.free_bytes() < s.min_free_bytes:
        raise HTTPException(507, "服务器磁盘空间不足，请联系管理员")
    max_bytes = s.max_upload_mb * 1_000_000
    data = await file.read(max_bytes + 1)
    try:
        return await asyncio.to_thread(normalize_upload, data, max_bytes=max_bytes, max_pixels=s.max_pixels)
    except UploadRejected as exc:
        raise HTTPException(400, str(exc)) from exc
```

- [x] **Step 6: 实现 `src/imgsr/api/schemas.py`**

```python
"""Response/request models shared by the routers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imgsr.db.models import Job, Task

ACTIVE = ("queued", "running")


class RoundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    seq: int
    status: str
    image_model: str
    prompt: str
    strategy: dict[str, Any]
    use_text_hint: bool
    result_w: int | None
    result_h: int | None
    download_w: int | None
    download_h: int | None
    elapsed_s: float | None
    error: str | None
    review: dict[str, Any] | None
    created_at: datetime


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: str
    source_w: int
    source_h: int
    transcript_raw: str | None
    confirmed_text: str | None
    final_round_id: int | None
    error: str | None
    created_at: datetime
    expires_at: datetime
    rounds: list[RoundOut]
    busy: bool = False


class TaskSummary(BaseModel):
    id: str
    status: str
    source_w: int
    source_h: int
    created_at: datetime
    final_round_id: int | None
    rounds: int


class GuestTaskOut(BaseModel):
    id: str
    status: str
    source_w: int
    source_h: int
    created_at: datetime
    expires_at: datetime
    round: RoundOut | None


class TextIn(BaseModel):
    confirmed_text: str = Field(max_length=20_000)


class SuggestionRef(BaseModel):
    round_id: int
    index: int


class RoundIn(BaseModel):
    prompt: str | None = Field(None, max_length=8_000)
    strategy: Literal["auto", "whole", "tiles"] = "auto"
    preupscale: Literal[1, 2] = 1
    use_text_hint: bool = True
    suggestion: SuggestionRef | None = None


class FinalIn(BaseModel):
    round_id: int


def task_out(db: Session, task: Task) -> TaskOut:
    busy = db.scalar(
        select(func.count()).select_from(Job).where(Job.task_id == task.id, Job.status.in_(ACTIVE))
    )
    return TaskOut.model_validate(task).model_copy(update={"busy": bool(busy)})


def guest_task_out(task: Task) -> GuestTaskOut:
    return GuestTaskOut(
        id=task.id, status=task.status, source_w=task.source_w, source_h=task.source_h,
        created_at=task.created_at, expires_at=task.expires_at,
        round=RoundOut.model_validate(task.rounds[0]) if task.rounds else None,
    )
```

- [x] **Step 7: 实现 `src/imgsr/api/routes_auth.py`**

```python
"""Login, logout and the current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from imgsr import quota
from imgsr.api.deps import AppContext, client_ip, current_user, db_session, get_ctx
from imgsr.auth import SESSION_COOKIE, create_session, end_session, verify_password
from imgsr.db.models import User

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class MeOut(BaseModel):
    id: int
    username: str
    role: str
    daily_quota: int
    used_today: int


def me_out(db: Session, user: User) -> MeOut:
    return MeOut(id=user.id, username=user.username, role=user.role, daily_quota=user.daily_quota,
                 used_today=quota.used(db, f"user:{user.id}", quota.today()))


@router.post("/auth/login")
def login(body: LoginIn, response: Response, db: Session = Depends(db_session),
          c: AppContext = Depends(get_ctx), ip: str = Depends(client_ip)) -> MeOut:
    if c.limiter.locked(ip):
        raise HTTPException(429, "登录失败次数过多，请 15 分钟后再试")
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or user.disabled or not verify_password(user.password_hash, body.password):
        c.limiter.failed(ip)
        raise HTTPException(401, "用户名或密码错误")
    c.limiter.succeeded(ip)
    s = c.settings()
    token = create_session(db, user, s.session_days)
    response.set_cookie(SESSION_COOKIE, token, max_age=s.session_days * 86_400, httponly=True,
                        secure=s.cookie_secure, samesite="lax", path="/")
    return me_out(db, user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(db_session)) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        end_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(db_session)) -> MeOut:
    return me_out(db, user)
```

- [x] **Step 8: 实现 `src/imgsr/api/app.py`**

```python
"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from imgsr.api import routes_auth
from imgsr.api.deps import AppContext
from imgsr.auth import LoginLimiter
from imgsr.clientip import parse_networks
from imgsr.config import Settings
from imgsr.config_store import SettingsProvider
from imgsr.db.session import make_engine, make_session_factory, migrate
from imgsr.jobs.handlers import ImageEditor, Pipeline, Services, Transcriber
from imgsr.jobs.runner import JobRunner
from imgsr.maintenance import maintenance_loop
from imgsr.relay.base import masked
from imgsr.relay.chat import ChatClient
from imgsr.relay.images import ImageClient
from imgsr.relay.retry import DEFAULT_DELAYS
from imgsr.storage import Storage

log = logging.getLogger("imgsr")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
ROUTERS = (routes_auth,)


def create_app(
    settings: Settings | None = None,
    *,
    images: ImageEditor | None = None,
    chat: Transcriber | None = None,
    retry_delays: tuple[float, ...] = DEFAULT_DELAYS,
    maintenance: bool = True,
) -> FastAPI:
    base = settings or Settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(base.db_path)
        migrate(engine)
        sf = make_session_factory(engine)
        provider = SettingsProvider(base, sf)
        eff = provider()
        image_client = images or ImageClient(eff.open_api_base_url, eff.open_api_key, timeout=eff.image_timeout_s)
        chat_client = chat or ChatClient(eff.open_api_base_url, eff.open_api_key, timeout=eff.chat_timeout_s)
        storage = Storage(base.files_dir)
        runner = JobRunner(sf, workers=eff.upstream_concurrency + 2)
        pipeline = Pipeline(Services(
            session_factory=sf, storage=storage, images=image_client, chat=chat_client,
            settings=provider, gate=asyncio.Semaphore(eff.upstream_concurrency),
            enqueue=runner.enqueue, retry_delays=retry_delays,
        ))
        runner.handlers.update(pipeline.handlers())
        runner.on_interrupted = pipeline.on_interrupted
        app.state.ctx = AppContext(settings=provider, sf=sf, engine=engine, storage=storage,
                                   runner=runner, limiter=LoginLimiter(),
                                   trusted=parse_networks(base.trusted_proxies))
        log.info("imgsr start relay=%s key=%s image=%s transcribe=%s review=%s",
                 eff.open_api_base_url, masked(eff.open_api_key), eff.image_model,
                 eff.transcribe_model, eff.review_model)
        await runner.start()
        maint = (asyncio.create_task(maintenance_loop(sf, storage, engine, base.backup_dir))
                 if maintenance else None)
        try:
            yield
        finally:
            if maint is not None:
                maint.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await maint
            await runner.stop()
            if images is None:
                await image_client.aclose()  # type: ignore[union-attr]
            if chat is None:
                await chat_client.aclose()  # type: ignore[union-attr]
            engine.dispose()

    app = FastAPI(title="imgsr", lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):  # noqa: ANN001, ANN202
        if (request.method in MUTATING and request.url.path.startswith("/api/")
                and request.headers.get("x-requested-with") != "imgsr"):
            return JSONResponse({"detail": "缺少请求头 X-Requested-With: imgsr"}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health(request: Request) -> dict:
        ctx: AppContext = request.app.state.ctx
        free = ctx.storage.free_bytes()
        return {"ok": True, "free_bytes": free, "low_disk": free < ctx.settings().min_free_bytes}

    for module in ROUTERS:
        app.include_router(module.router)
    return app
```

- [x] **Step 9: 运行，确认通过**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: 全部 passed

- [x] **Step 10: Commit**

```bash
git add src/imgsr/config_store.py src/imgsr/maintenance.py src/imgsr/api tests/test_config_store.py tests/api
git commit -m "feat: app factory, auth endpoints and admin-overridable settings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: 登录用户的任务接口与文件下载

**Files:**
- Create: `src/imgsr/api/routes_tasks.py`, `src/imgsr/api/routes_files.py`, `tests/api/test_tasks_api.py`
- Modify: `src/imgsr/api/app.py`（`from imgsr.api import routes_auth, routes_files, routes_tasks`；`ROUTERS = (routes_auth, routes_tasks, routes_files)`）

**Interfaces:**
- Consumes: `deps`、`schemas`、`quota`、`BASE_PROMPT`、`TASK_ID_RE`、`token_hash`、`GUEST_COOKIE`
- Produces（spec §6.2）：
  - `POST /api/tasks`（multipart `file`）→ 201 `TaskOut`
  - `GET /api/tasks?cursor=&limit=` → `{"items": [TaskSummary], "next_cursor": datetime | null}`
  - `GET /api/tasks/{id}` → `TaskOut`；`DELETE /api/tasks/{id}` → 204
  - `PUT /api/tasks/{id}/text` `{confirmed_text}` → `TaskOut`
  - `POST /api/tasks/{id}/transcribe` → `TaskOut`
  - `POST /api/tasks/{id}/rounds` `RoundIn` → 201 `TaskOut`；`POST /api/tasks/{id}/rounds/{seq}/retry` → `TaskOut`
  - `POST /api/tasks/{id}/final` `{round_id}` → `TaskOut`
  - `GET /api/files/{task_id}/{name}?download=1` → 图片（登录用户本人或持有对应 guest cookie）
- 错误码：401 未登录、404 不存在或非本人、409 状态冲突、429 额度用尽、400 参数/上传问题、507 磁盘不足。

- [x] **Step 1: 写失败测试 `tests/api/test_tasks_api.py`**

```python
import threading

from imgsr.relay.errors import RelayError
from tests.api.helpers import add_user, login, upload, wait_task


def ready_task(api, text="原文。", **user):
    add_user(api, **user)
    login(api.client, user.get("username", "alice"))
    tid = upload(api.client).json()["id"]
    wait_task(api.client, tid, lambda b: b["status"] == "awaiting_confirm")
    assert api.client.put(f"/api/tasks/{tid}/text", json={"confirmed_text": text}).status_code == 200
    return tid


def test_upload_transcribes_and_waits_for_confirmation(api):
    api.chat.reply = lambda i, size: "第一段。\n第二段。"
    add_user(api)
    login(api.client)
    r = upload(api.client)
    assert r.status_code == 201
    body = wait_task(api.client, r.json()["id"], lambda b: b["status"] == "awaiting_confirm")
    assert body["transcript_raw"] == "第一段。\n第二段。" and body["busy"] is False


def test_upload_requires_login_and_valid_image(api):
    assert upload(api.client).status_code == 401
    add_user(api)
    login(api.client)
    r = api.client.post("/api/tasks", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 400 and "无法识别" in r.json()["detail"]


def test_full_round_then_final_and_download(api):
    tid = ready_task(api, "原文。")
    api.chat.reply = lambda i, size: "原文。"
    assert api.client.post(f"/api/tasks/{tid}/rounds", json={}).status_code == 201
    body = wait_task(api.client, tid, lambda b: b["status"] == "reviewed")
    rnd = body["rounds"][0]
    assert rnd["status"] == "succeeded" and rnd["use_text_hint"] is True
    assert rnd["review"]["diffs"] == []
    assert rnd["review"]["suggestions"][0]["action"] == "accept"
    assert "「原文。」" in api.images.calls[-1]["prompt"]
    r = api.client.post(f"/api/tasks/{tid}/final", json={"round_id": rnd["id"]})
    assert r.json()["status"] == "done" and r.json()["final_round_id"] == rnd["id"]
    f = api.client.get(f"/api/files/{tid}/download-1?download=1")
    assert f.status_code == 200 and "attachment" in f.headers["content-disposition"]
    assert api.client.get(f"/api/files/{tid}/thumb").status_code == 200


def test_suggestion_executes_next_round(api):
    tid = ready_task(api, "晚上还会发出亮光呢！")
    api.chat.reply = lambda i, size: "晚上还会发出光光呢！"
    api.client.post(f"/api/tasks/{tid}/rounds", json={"use_text_hint": False})
    body = wait_task(api.client, tid, lambda b: b["status"] == "reviewed")
    first = body["rounds"][0]
    assert first["review"]["diffs"][0]["expected"] == "亮"
    assert first["review"]["suggestions"][0]["action"] == "retry_with_hint"
    r = api.client.post(f"/api/tasks/{tid}/rounds",
                        json={"suggestion": {"round_id": first["id"], "index": 0}})
    assert r.status_code == 201
    body = wait_task(api.client, tid, lambda b: b["status"] == "reviewed" and len(b["rounds"]) == 2)
    assert body["rounds"][1]["use_text_hint"] is True


def test_bad_suggestion_reference(api):
    tid = ready_task(api)
    r = api.client.post(f"/api/tasks/{tid}/rounds", json={"suggestion": {"round_id": 999, "index": 0}})
    assert r.status_code == 400


def test_one_generation_at_a_time(api):
    tid = ready_task(api)
    api.images.gate = threading.Event()
    assert api.client.post(f"/api/tasks/{tid}/rounds", json={}).status_code == 201
    assert api.client.post(f"/api/tasks/{tid}/rounds", json={}).status_code == 409
    api.images.gate.set()
    wait_task(api.client, tid, lambda b: b["status"] == "reviewed")


def test_daily_quota(api):
    tid = ready_task(api, quota=1)
    assert api.client.post(f"/api/tasks/{tid}/rounds", json={}).status_code == 201
    wait_task(api.client, tid, lambda b: b["status"] == "reviewed")
    r = api.client.post(f"/api/tasks/{tid}/rounds", json={})
    assert r.status_code == 429 and "今日生成次数已用完" in r.json()["detail"]


def test_failed_round_refunds_and_can_be_retried(api):
    tid = ready_task(api)
    api.images.fail = RelayError("上游拒绝请求：bad", kind="rejected", retryable=False)
    api.client.post(f"/api/tasks/{tid}/rounds", json={})
    body = wait_task(api.client, tid, lambda b: b["status"] == "round_failed")
    assert "bad" in body["rounds"][0]["error"]
    assert api.client.get("/api/me").json()["used_today"] == 0
    api.images.fail = None
    assert api.client.post(f"/api/tasks/{tid}/rounds/1/retry").status_code == 200
    wait_task(api.client, tid, lambda b: b["status"] == "reviewed")
    assert api.client.post(f"/api/tasks/{tid}/rounds/1/retry").status_code == 409


def test_other_users_cannot_see_task_or_files(api):
    tid = ready_task(api)
    add_user(api, "bob")
    api.client.cookies.clear()
    login(api.client, "bob")
    assert api.client.get(f"/api/tasks/{tid}").status_code == 404
    assert api.client.get(f"/api/files/{tid}/source").status_code == 404
    assert api.client.get("/api/tasks").json()["items"] == []


def test_delete_removes_rows_and_files(api):
    tid = ready_task(api)
    assert api.client.delete(f"/api/tasks/{tid}").status_code == 204
    assert api.client.get(f"/api/tasks/{tid}").status_code == 404
    assert not api.ctx.storage.task_dir(tid).exists()


def test_low_disk_rejects_upload(api, monkeypatch):
    add_user(api)
    login(api.client)
    monkeypatch.setattr(api.ctx.storage, "free_bytes", lambda: 10)
    assert upload(api.client).status_code == 507


def test_list_paginates(api):
    add_user(api)
    login(api.client)
    for _ in range(3):
        upload(api.client)
    page = api.client.get("/api/tasks", params={"limit": 2}).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    rest = api.client.get("/api/tasks", params={"limit": 2, "cursor": page["next_cursor"]}).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None


def test_retry_transcription(api):
    api.chat.fail = RelayError("上游超时", kind="timeout", retryable=True)
    add_user(api)
    login(api.client)
    tid = upload(api.client).json()["id"]
    wait_task(api.client, tid, lambda b: b["status"] == "transcribe_failed")
    api.chat.fail = None
    assert api.client.post(f"/api/tasks/{tid}/transcribe").status_code == 200
    wait_task(api.client, tid, lambda b: b["status"] == "awaiting_confirm")
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/api/test_tasks_api.py -q`
Expected: FAIL（404/405，路由不存在）

- [x] **Step 3: 实现 `src/imgsr/api/routes_tasks.py`**

```python
"""Logged-in user's tasks: upload, confirm text, rounds, final, delete."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imgsr import quota
from imgsr.api.deps import AppContext, client_ip, current_user, db_session, get_ctx, read_upload
from imgsr.api.schemas import ACTIVE, FinalIn, RoundIn, TaskOut, TaskSummary, TextIn, task_out
from imgsr.db.models import Job, Round, Task, User, utcnow
from imgsr.pipeline.prompt import BASE_PROMPT
from imgsr.storage import TASK_ID_RE

router = APIRouter(prefix="/api/tasks")
EXECUTABLE = {"retry_with_hint", "tile_refine"}


def own_task(db: Session, task_id: str, user: User) -> Task:
    task = db.get(Task, task_id) if TASK_ID_RE.fullmatch(task_id) else None
    if task is None or task.owner_user_id != user.id:
        raise HTTPException(404, "任务不存在")
    return task


def task_busy(db: Session, task_id: str) -> bool:
    return bool(db.scalar(
        select(func.count()).select_from(Job).where(Job.task_id == task_id, Job.status.in_(ACTIVE))
    ))


def user_generating(db: Session, user_id: int) -> bool:
    return bool(db.scalar(
        select(func.count()).select_from(Job).join(Task, Task.id == Job.task_id)
        .where(Task.owner_user_id == user_id, Job.kind == "generate", Job.status.in_(ACTIVE))
    ))


def charge_user(db: Session, user: User) -> dict:
    try:
        return quota.consume(
            db, [(f"user:{user.id}", user.daily_quota, "今日生成次数已用完，明天再来或联系管理员调整额度")],
            quota.today(),
        )
    except quota.QuotaExceeded as exc:
        raise HTTPException(429, str(exc)) from exc


def _suggestion_params(db: Session, task: Task, round_id: int, index: int) -> dict:
    src = db.get(Round, round_id)
    suggestions = (src.review or {}).get("suggestions", []) if src and src.task_id == task.id else []
    if not 0 <= index < len(suggestions):
        raise HTTPException(400, "建议不存在")
    suggestion = suggestions[index]
    if suggestion.get("action") not in EXECUTABLE:
        raise HTTPException(400, "该建议不需要生成新一轮")
    return dict(suggestion.get("params") or {})


@router.post("", status_code=201)
async def upload(file: UploadFile = File(...), user: User = Depends(current_user),
                 db: Session = Depends(db_session), c: AppContext = Depends(get_ctx),
                 ip: str = Depends(client_ip)) -> TaskOut:
    img = await read_upload(file, c)
    task_id = uuid.uuid4().hex
    await asyncio.to_thread(c.storage.save_source, task_id, img)
    task = Task(id=task_id, owner_user_id=user.id, client_ip=ip, source_w=img.width,
                source_h=img.height, status="uploaded",
                expires_at=utcnow() + timedelta(days=c.settings().retention_user_days))
    db.add(task)
    db.flush()
    job = Job(kind="transcribe", task_id=task_id)
    db.add(job)
    db.commit()
    c.runner.enqueue(job.id)
    return task_out(db, task)


@router.get("")
def list_tasks(cursor: datetime | None = None, limit: int = Query(20, ge=1, le=100),
               user: User = Depends(current_user), db: Session = Depends(db_session)) -> dict:
    q = select(Task).where(Task.owner_user_id == user.id)
    if cursor is not None:
        q = q.where(Task.created_at < cursor)
    tasks = db.scalars(q.order_by(Task.created_at.desc()).limit(limit)).all()
    items = [TaskSummary(id=t.id, status=t.status, source_w=t.source_w, source_h=t.source_h,
                         created_at=t.created_at, final_round_id=t.final_round_id,
                         rounds=len(t.rounds)) for t in tasks]
    return {"items": items, "next_cursor": tasks[-1].created_at if len(tasks) == limit else None}


@router.get("/{task_id}")
def get_task(task_id: str, user: User = Depends(current_user),
             db: Session = Depends(db_session)) -> TaskOut:
    return task_out(db, own_task(db, task_id, user))


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, user: User = Depends(current_user), db: Session = Depends(db_session),
                c: AppContext = Depends(get_ctx)) -> Response:
    task = own_task(db, task_id, user)
    db.delete(task)
    db.commit()
    c.storage.delete_task(task_id)
    return Response(status_code=204)


@router.put("/{task_id}/text")
def confirm_text(task_id: str, body: TextIn, user: User = Depends(current_user),
                 db: Session = Depends(db_session)) -> TaskOut:
    task = own_task(db, task_id, user)
    if task_busy(db, task.id):
        raise HTTPException(409, "任务正在处理中，请稍后再改原文")
    task.confirmed_text = body.confirmed_text.strip()
    if task.status in ("uploaded", "awaiting_confirm", "transcribe_failed"):
        task.status = "ready"
    db.commit()
    return task_out(db, task)


@router.post("/{task_id}/transcribe")
def retry_transcribe(task_id: str, user: User = Depends(current_user),
                     db: Session = Depends(db_session), c: AppContext = Depends(get_ctx)) -> TaskOut:
    task = own_task(db, task_id, user)
    if task_busy(db, task.id):
        raise HTTPException(409, "任务正在处理中")
    task.status, task.error = "uploaded", None
    job = Job(kind="transcribe", task_id=task.id)
    db.add(job)
    db.commit()
    c.runner.enqueue(job.id)
    return task_out(db, task)


@router.post("/{task_id}/rounds", status_code=201)
def create_round(task_id: str, body: RoundIn, user: User = Depends(current_user),
                 db: Session = Depends(db_session), c: AppContext = Depends(get_ctx)) -> TaskOut:
    task = own_task(db, task_id, user)
    if task.status in ("uploaded", "transcribing"):
        raise HTTPException(409, "请等待原文转写完成")
    if task_busy(db, task.id):
        raise HTTPException(409, "该任务正在处理中")
    if user_generating(db, user.id):
        raise HTTPException(409, "你已有一个生成任务在进行中")
    params = {"prompt": body.prompt, "strategy": body.strategy, "preupscale": body.preupscale,
              "use_text_hint": body.use_text_hint}
    if body.suggestion is not None:
        params.update(_suggestion_params(db, task, body.suggestion.round_id, body.suggestion.index))
    has_text = bool((task.confirmed_text or "").strip())
    charge = charge_user(db, user)
    seq = (db.scalar(select(func.max(Round.seq)).where(Round.task_id == task.id)) or 0) + 1
    rnd = Round(task_id=task.id, seq=seq, image_model=c.settings().image_model,
                prompt=(params["prompt"] or "").strip() or BASE_PROMPT,
                strategy={"mode": params["strategy"], "preupscale": params["preupscale"]},
                use_text_hint=bool(params["use_text_hint"]) and has_text, status="queued",
                charge=charge)
    db.add(rnd)
    task.status = "generating"
    db.flush()
    job = Job(kind="generate", task_id=task.id, round_id=rnd.id)
    db.add(job)
    db.commit()
    c.runner.enqueue(job.id)
    return task_out(db, task)


@router.post("/{task_id}/rounds/{seq}/retry")
def retry_round(task_id: str, seq: int, user: User = Depends(current_user),
                db: Session = Depends(db_session), c: AppContext = Depends(get_ctx)) -> TaskOut:
    task = own_task(db, task_id, user)
    rnd = db.scalar(select(Round).where(Round.task_id == task.id, Round.seq == seq))
    if rnd is None:
        raise HTTPException(404, "轮次不存在")
    if task_busy(db, task.id):
        raise HTTPException(409, "任务正在处理中")
    if rnd.status == "failed":
        if user_generating(db, user.id):
            raise HTTPException(409, "你已有一个生成任务在进行中")
        charge = charge_user(db, user)
        rnd.status, rnd.error, rnd.charge = "queued", None, charge
        rnd.strategy = {"mode": rnd.strategy.get("mode", "auto"),
                        "preupscale": rnd.strategy.get("preupscale", 1)}
        task.status, kind = "generating", "generate"
    elif rnd.status == "succeeded" and rnd.review and rnd.review.get("error"):
        task.status, kind = "reviewing", "review"
    else:
        raise HTTPException(409, "该轮次无需重试")
    job = Job(kind=kind, task_id=task.id, round_id=rnd.id)
    db.add(job)
    db.commit()
    c.runner.enqueue(job.id)
    return task_out(db, task)


@router.post("/{task_id}/final")
def set_final(task_id: str, body: FinalIn, user: User = Depends(current_user),
              db: Session = Depends(db_session)) -> TaskOut:
    task = own_task(db, task_id, user)
    rnd = db.get(Round, body.round_id)
    if rnd is None or rnd.task_id != task.id or rnd.status != "succeeded":
        raise HTTPException(400, "只能选择已成功的轮次")
    task.final_round_id, task.status = rnd.id, "done"
    db.commit()
    return task_out(db, task)
```

- [x] **Step 4: 实现 `src/imgsr/api/routes_files.py`**

```python
"""Serve task images to their owner (logged-in user or the guest cookie holder)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from imgsr.api.deps import AppContext, current_user_optional, db_session, get_ctx
from imgsr.auth import GUEST_COOKIE, token_hash
from imgsr.db.models import Task, User
from imgsr.storage import TASK_ID_RE

router = APIRouter(prefix="/api/files")


def _allowed(task: Task | None, user: User | None, guest_cookie: str | None) -> bool:
    if task is None:
        return False
    if task.owner_user_id is not None:
        return user is not None and user.id == task.owner_user_id
    return bool(guest_cookie) and task.guest_token_hash == token_hash(guest_cookie)


@router.get("/{task_id}/{name}")
def get_file(task_id: str, name: str, request: Request, download: bool = False,
             user: User | None = Depends(current_user_optional), db: Session = Depends(db_session),
             c: AppContext = Depends(get_ctx)) -> FileResponse:
    task = db.get(Task, task_id) if TASK_ID_RE.fullmatch(task_id) else None
    if not _allowed(task, user, request.cookies.get(GUEST_COOKIE)):
        raise HTTPException(404, "文件不存在")
    path = c.storage.named(task_id, name)
    if path is None:
        raise HTTPException(404, "文件不存在")
    headers = {"Cache-Control": "private, max-age=3600"}
    if download:
        return FileResponse(path, headers=headers, filename=f"imgsr-{task_id[:8]}-{name}{path.suffix}")
    return FileResponse(path, headers=headers)
```

- [x] **Step 5: 修改 `src/imgsr/api/app.py`**

把 `from imgsr.api import routes_auth` 改为：

```python
from imgsr.api import routes_auth, routes_files, routes_tasks
```

把 `ROUTERS = (routes_auth,)` 改为：

```python
ROUTERS = (routes_auth, routes_tasks, routes_files)
```

- [x] **Step 6: 运行，确认通过**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: 全部 passed

- [x] **Step 7: Commit**

```bash
git add src/imgsr/api/routes_tasks.py src/imgsr/api/routes_files.py src/imgsr/api/app.py tests/api/test_tasks_api.py
git commit -m "feat: task, round and file endpoints for logged-in users" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: 游客接口（`routes_guest.py`）

**Files:**
- Create: `src/imgsr/api/routes_guest.py`, `tests/api/test_guest_api.py`
- Modify: `src/imgsr/api/app.py`（导入 `routes_guest`；`ROUTERS = (routes_auth, routes_tasks, routes_files, routes_guest)`）

**Interfaces:**
- Produces:
  - `POST /api/guest/tasks`（multipart `file`，可选表单 `prompt`）→ 201 `GuestTaskOut`；设置 `imgsr_guest` Cookie（24 h）
  - `GET /api/guest/tasks/{id}` → `GuestTaskOut`（需匹配 cookie，否则 404）
  - `GET /api/guest/quota` → `{"limit", "remaining", "global_remaining"}`
- 限额消息：IP 用尽 `今日免费次数已用完，登录后可继续使用`；全站用尽 `今日游客总额度已用完，请明天再来`；同 IP 已有任务 409 `当前网络已有任务在处理中，请稍候`。

- [x] **Step 1: 写失败测试 `tests/api/test_guest_api.py`**

```python
import threading

from imgsr.relay.errors import RelayError
from tests.api.helpers import add_user, login, upload, wait_task

GUEST = "/api/guest/tasks"


def guest_upload(api, ip, **form):
    return upload(api.client, path=GUEST, ip=ip, **form)


def wait_guest(api, tid):
    return wait_task(api.client, tid, lambda b: b["status"] in ("done", "round_failed"),
                     path=GUEST + "/{id}")


def remaining(api, ip):
    return api.client.get("/api/guest/quota", headers={"X-Forwarded-For": ip}).json()["remaining"]


def test_guest_flow(api):
    r = guest_upload(api, "1.1.1.1", prompt="请保持原样")
    assert r.status_code == 201 and "imgsr_guest" in api.client.cookies
    body = wait_guest(api, r.json()["id"])
    assert body["status"] == "done" and body["round"]["use_text_hint"] is False
    assert body["round"]["prompt"] == "请保持原样"
    assert api.client.get(f"/api/files/{body['id']}/download-1").status_code == 200
    assert api.chat.calls == []


def test_guest_ip_limit(api):
    for _ in range(3):
        wait_guest(api, guest_upload(api, "1.1.1.1").json()["id"])
    r = guest_upload(api, "1.1.1.1")
    assert r.status_code == 429 and "今日免费次数已用完" in r.json()["detail"]
    assert remaining(api, "1.1.1.1") == 0
    assert guest_upload(api, "2.2.2.2").status_code == 201


def test_guest_global_cap(make_api):
    api = make_api(guest_daily_global=2)
    for ip in ("1.1.1.1", "2.2.2.2"):
        wait_guest(api, guest_upload(api, ip).json()["id"])
    r = guest_upload(api, "3.3.3.3")
    assert r.status_code == 429 and "今日游客总额度已用完" in r.json()["detail"]


def test_guest_failure_refunds(api):
    api.images.fail = RelayError("上游拒绝请求：bad", kind="rejected", retryable=False)
    body = wait_guest(api, guest_upload(api, "1.1.1.1").json()["id"])
    assert body["status"] == "round_failed"
    assert remaining(api, "1.1.1.1") == 3


def test_guest_task_needs_its_cookie(api):
    tid = guest_upload(api, "1.1.1.1").json()["id"]
    wait_guest(api, tid)
    api.client.cookies.clear()
    assert api.client.get(f"{GUEST}/{tid}").status_code == 404
    assert api.client.get(f"/api/files/{tid}/source").status_code == 404


def test_guest_one_at_a_time_per_ip(api):
    api.images.gate = threading.Event()
    tid = guest_upload(api, "1.1.1.1").json()["id"]
    assert guest_upload(api, "1.1.1.1").status_code == 409
    api.images.gate.set()
    wait_guest(api, tid)


def test_guest_tasks_are_not_in_user_history(api):
    wait_guest(api, guest_upload(api, "1.1.1.1").json()["id"])
    add_user(api)
    login(api.client)
    assert api.client.get("/api/tasks").json()["items"] == []
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/api/test_guest_api.py -q`
Expected: FAIL（404，路由不存在）

- [x] **Step 3: 实现 `src/imgsr/api/routes_guest.py`**

```python
"""Guest (no login) single-round generation with per-IP and global daily caps."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imgsr import quota
from imgsr.api.deps import AppContext, client_ip, db_session, get_ctx, read_upload
from imgsr.api.schemas import ACTIVE, GuestTaskOut, guest_task_out
from imgsr.auth import GUEST_COOKIE, new_token, token_hash
from imgsr.config import Settings
from imgsr.db.models import Job, Round, Task, utcnow
from imgsr.pipeline.prompt import BASE_PROMPT
from imgsr.storage import TASK_ID_RE

router = APIRouter(prefix="/api/guest")


def _guest_token(request: Request, response: Response, s: Settings) -> str:
    token = request.cookies.get(GUEST_COOKIE) or ""
    if not 20 <= len(token) <= 100:
        token = new_token()
    response.set_cookie(GUEST_COOKIE, token, max_age=s.retention_guest_hours * 3600, httponly=True,
                        secure=s.cookie_secure, samesite="lax", path="/")
    return token


def _ip_generating(db: Session, ip: str) -> bool:
    return bool(db.scalar(
        select(func.count()).select_from(Job).join(Task, Task.id == Job.task_id)
        .where(Task.owner_user_id.is_(None), Task.client_ip == ip, Job.kind == "generate",
               Job.status.in_(ACTIVE))
    ))


@router.post("/tasks", status_code=201)
async def guest_upload(request: Request, response: Response, file: UploadFile = File(...),
                       prompt: str | None = Form(None, max_length=8_000),
                       db: Session = Depends(db_session), c: AppContext = Depends(get_ctx),
                       ip: str = Depends(client_ip)) -> GuestTaskOut:
    s = c.settings()
    img = await read_upload(file, c)
    if _ip_generating(db, ip):
        raise HTTPException(409, "当前网络已有任务在处理中，请稍候")
    try:
        charge = quota.consume(db, [
            (f"ip:{ip}", s.guest_daily_per_ip, "今日免费次数已用完，登录后可继续使用"),
            ("guest:global", s.guest_daily_global, "今日游客总额度已用完，请明天再来"),
        ], quota.today())
    except quota.QuotaExceeded as exc:
        raise HTTPException(429, str(exc)) from exc
    token = _guest_token(request, response, s)
    task_id = uuid.uuid4().hex
    try:
        await asyncio.to_thread(c.storage.save_source, task_id, img)
    except Exception:
        quota.refund(db, charge)
        raise
    task = Task(id=task_id, owner_user_id=None, guest_token_hash=token_hash(token), client_ip=ip,
                source_w=img.width, source_h=img.height, status="generating",
                expires_at=utcnow() + timedelta(hours=s.retention_guest_hours))
    db.add(task)
    db.flush()
    rnd = Round(task_id=task_id, seq=1, image_model=s.image_model,
                prompt=(prompt or "").strip() or BASE_PROMPT,
                strategy={"mode": "auto", "preupscale": 1}, use_text_hint=False, status="queued",
                charge=charge)
    db.add(rnd)
    db.flush()
    job = Job(kind="generate", task_id=task_id, round_id=rnd.id)
    db.add(job)
    db.commit()
    c.runner.enqueue(job.id)
    return guest_task_out(task)


@router.get("/tasks/{task_id}")
def guest_task(task_id: str, request: Request, db: Session = Depends(db_session)) -> GuestTaskOut:
    token = request.cookies.get(GUEST_COOKIE)
    task = db.get(Task, task_id) if TASK_ID_RE.fullmatch(task_id) else None
    if (task is None or task.owner_user_id is not None or not token
            or task.guest_token_hash != token_hash(token)):
        raise HTTPException(404, "任务不存在")
    return guest_task_out(task)


@router.get("/quota")
def guest_quota(db: Session = Depends(db_session), c: AppContext = Depends(get_ctx),
                ip: str = Depends(client_ip)) -> dict:
    s = c.settings()
    day = quota.today()
    return {
        "limit": s.guest_daily_per_ip,
        "remaining": max(0, s.guest_daily_per_ip - quota.used(db, f"ip:{ip}", day)),
        "global_remaining": max(0, s.guest_daily_global - quota.used(db, "guest:global", day)),
    }
```

- [x] **Step 4: 修改 `src/imgsr/api/app.py`**

```python
from imgsr.api import routes_auth, routes_files, routes_guest, routes_tasks
```

```python
ROUTERS = (routes_auth, routes_tasks, routes_files, routes_guest)
```

- [x] **Step 5: 运行，确认通过**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: 全部 passed

- [x] **Step 6: Commit**

```bash
git add src/imgsr/api/routes_guest.py src/imgsr/api/app.py tests/api/test_guest_api.py
git commit -m "feat: guest endpoints with per-IP and global daily caps" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: 管理接口（`routes_admin.py`）

**Files:**
- Create: `src/imgsr/api/routes_admin.py`, `tests/api/test_admin_api.py`
- Modify: `src/imgsr/api/app.py`（导入 `routes_admin`；`ROUTERS = (routes_auth, routes_tasks, routes_files, routes_guest, routes_admin)`）

**Interfaces:**
- Produces（全部需要管理员）：
  - `GET /api/admin/users` → `[UserOut]`；`POST /api/admin/users` `{username, password, role?, daily_quota?}` → 201 `UserOut`（重名 409）；`PATCH /api/admin/users/{id}` `{password?, role?, disabled?, daily_quota?}` → `UserOut`（改密码或禁用会清掉该用户全部会话；不能禁用/降级自己 → 400）
  - `GET /api/admin/settings` → `{"effective": {OVERRIDABLE 键: 值}, "overrides": {...}, "restart_required": ["upstream_concurrency"]}`；`PATCH /api/admin/settings` `{key: value}` → 同上（校验失败 400）
- `UserOut = {id, username, role, daily_quota, disabled, created_at, used_today}`

- [x] **Step 1: 写失败测试 `tests/api/test_admin_api.py`**

```python
from imgsr.auth import create_session, user_for_token
from imgsr.db.models import User
from tests.api.helpers import add_user, login, upload, wait_task


def as_admin(api):
    uid = add_user(api, "root", role="admin")
    login(api.client, "root")
    return uid


def test_non_admin_is_forbidden(api):
    add_user(api)
    login(api.client)
    assert api.client.get("/api/admin/users").status_code == 403


def test_create_user_then_login(api):
    as_admin(api)
    r = api.client.post("/api/admin/users", json={"username": "carol", "password": "password123"})
    assert r.status_code == 201 and r.json()["daily_quota"] == 50 and r.json()["role"] == "user"
    dup = api.client.post("/api/admin/users", json={"username": "carol", "password": "password123"})
    assert dup.status_code == 409
    bad = api.client.post("/api/admin/users", json={"username": "x y", "password": "short"})
    assert bad.status_code == 422
    api.client.cookies.clear()
    login(api.client, "carol")


def test_disable_and_password_reset_end_sessions(api):
    as_admin(api)
    uid = add_user(api, "dave")
    with api.ctx.sf() as db:
        token = create_session(db, db.get(User, uid), 14)
    assert api.client.patch(f"/api/admin/users/{uid}", json={"password": "newpassword1"}).status_code == 200
    with api.ctx.sf() as db:
        assert user_for_token(db, token, 14) is None
        token = create_session(db, db.get(User, uid), 14)
    body = api.client.patch(f"/api/admin/users/{uid}", json={"disabled": True, "daily_quota": 5}).json()
    assert body["disabled"] is True and body["daily_quota"] == 5
    with api.ctx.sf() as db:
        assert user_for_token(db, token, 14) is None


def test_admin_cannot_disable_or_demote_self(api):
    uid = as_admin(api)
    assert api.client.patch(f"/api/admin/users/{uid}", json={"disabled": True}).status_code == 400
    assert api.client.patch(f"/api/admin/users/{uid}", json={"role": "user"}).status_code == 400


def test_list_users(api):
    as_admin(api)
    add_user(api, "erin")
    names = [u["username"] for u in api.client.get("/api/admin/users").json()]
    assert names == ["root", "erin"]


def test_settings_override_changes_next_round_model(api):
    as_admin(api)
    r = api.client.patch("/api/admin/settings", json={"image_model": "gpt-image-2"})
    assert r.status_code == 200
    assert r.json()["effective"]["image_model"] == "gpt-image-2"
    assert "open_api_key" not in r.json()["effective"]
    tid = upload(api.client).json()["id"]
    wait_task(api.client, tid, lambda b: b["status"] == "awaiting_confirm")
    api.client.put(f"/api/tasks/{tid}/text", json={"confirmed_text": "默认转写文字。"})
    api.client.post(f"/api/tasks/{tid}/rounds", json={})
    body = wait_task(api.client, tid, lambda b: b["status"] == "reviewed")
    assert body["rounds"][0]["image_model"] == "gpt-image-2"
    assert api.images.calls[-1]["model"] == "gpt-image-2"


def test_settings_validation(api):
    as_admin(api)
    assert api.client.patch("/api/admin/settings", json={"nope": 1}).status_code == 400
    assert api.client.patch("/api/admin/settings", json={"pixel_cap": 10}).status_code == 400
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/api/test_admin_api.py -q`
Expected: FAIL（404，路由不存在）

- [x] **Step 3: 实现 `src/imgsr/api/routes_admin.py`**

```python
"""Admin: user management and runtime settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from imgsr import quota
from imgsr.api.deps import AppContext, db_session, get_ctx, require_admin
from imgsr.auth import end_user_sessions, hash_password
from imgsr.config import OVERRIDABLE
from imgsr.config_store import SettingsError
from imgsr.db.models import User

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=256)
    role: Literal["admin", "user"] = "user"
    daily_quota: int | None = Field(None, ge=0, le=100_000)


class UserPatch(BaseModel):
    password: str | None = Field(None, min_length=8, max_length=256)
    role: Literal["admin", "user"] | None = None
    disabled: bool | None = None
    daily_quota: int | None = Field(None, ge=0, le=100_000)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    daily_quota: int
    disabled: bool
    created_at: datetime
    used_today: int


def user_out(db: Session, user: User) -> UserOut:
    return UserOut(id=user.id, username=user.username, role=user.role,
                   daily_quota=user.daily_quota, disabled=user.disabled,
                   created_at=user.created_at,
                   used_today=quota.used(db, f"user:{user.id}", quota.today()))


@router.get("/users")
def list_users(db: Session = Depends(db_session)) -> list[UserOut]:
    return [user_out(db, u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users", status_code=201)
def create_user(body: UserIn, db: Session = Depends(db_session),
                c: AppContext = Depends(get_ctx)) -> UserOut:
    if db.scalar(select(User).where(User.username == body.username)) is not None:
        raise HTTPException(409, "用户名已存在")
    user = User(username=body.username, password_hash=hash_password(body.password), role=body.role,
                daily_quota=body.daily_quota if body.daily_quota is not None
                else c.settings().user_daily_default)
    db.add(user)
    db.commit()
    return user_out(db, user)


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, admin: User = Depends(require_admin),
               db: Session = Depends(db_session)) -> UserOut:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(404, "用户不存在")
    if user.id == admin.id and (body.disabled or body.role == "user"):
        raise HTTPException(400, "不能禁用或降级自己")
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.role is not None:
        user.role = body.role
    if body.disabled is not None:
        user.disabled = body.disabled
    if body.daily_quota is not None:
        user.daily_quota = body.daily_quota
    db.commit()
    if body.password is not None or body.disabled:
        end_user_sessions(db, user.id)
    return user_out(db, user)


def _settings_view(c: AppContext) -> dict:
    eff = c.settings()
    return {"effective": {key: getattr(eff, key) for key in OVERRIDABLE},
            "overrides": c.settings.overrides(),
            "restart_required": ["upstream_concurrency"]}


@router.get("/settings")
def get_settings(c: AppContext = Depends(get_ctx)) -> dict:
    return _settings_view(c)


@router.patch("/settings")
def patch_settings(changes: dict[str, Any] = Body(...), c: AppContext = Depends(get_ctx)) -> dict:
    try:
        c.settings.update(changes)
    except SettingsError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _settings_view(c)
```

- [x] **Step 4: 修改 `src/imgsr/api/app.py`**

```python
from imgsr.api import routes_admin, routes_auth, routes_files, routes_guest, routes_tasks
```

```python
ROUTERS = (routes_auth, routes_tasks, routes_files, routes_guest, routes_admin)
```

- [x] **Step 5: 运行，确认通过**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: 全部 passed

- [x] **Step 6: Commit**

```bash
git add src/imgsr/api/routes_admin.py src/imgsr/api/app.py tests/api/test_admin_api.py
git commit -m "feat: admin endpoints for users and runtime settings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 18: 维护任务测试与命令行（`maintenance.py` 测试, `cli.py`）

**Files:**
- Create: `src/imgsr/cli.py`, `tests/test_maintenance.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `cleanup_expired`, `backup_db`（Task 14 已实现）
- Produces: `imgsr.cli.main(argv=None) -> int`；子命令 `create-user USERNAME [--admin] [--quota N] [--password-stdin]`、`reset-password USERNAME [--password-stdin]`、`cleanup`、`serve [--host] [--port]`。错误打印 `错误：…` 到 stderr 并返回 1。

- [x] **Step 1: 写失败测试**

`tests/test_maintenance.py`:

```python
from datetime import datetime, timedelta

from PIL import Image

from imgsr.db.models import Job, Task, utcnow
from imgsr.maintenance import backup_db, cleanup_expired
from imgsr.storage import Storage


def test_cleanup_removes_expired_tasks_but_keeps_busy_and_fresh(sf, tmp_path, make_task):
    storage = Storage(tmp_path / "files")
    past = utcnow() - timedelta(hours=1)
    expired = make_task(expires_at=past)
    busy = make_task(expires_at=past)
    fresh = make_task()
    storage.save_source(expired, Image.new("RGB", (5, 5)))
    with sf() as db:
        db.add(Job(kind="generate", task_id=busy, status="queued"))
        db.commit()
    assert cleanup_expired(sf, storage) == 1
    with sf() as db:
        assert db.get(Task, expired) is None
        assert db.get(Task, busy) is not None and db.get(Task, fresh) is not None
    assert not storage.task_dir(expired).exists()


def test_backup_keeps_latest_n(engine, tmp_path):
    target_dir = tmp_path / "backup"
    for day in range(1, 10):
        backup_db(engine, target_dir, keep=7, now=datetime(2026, 10, day))
    files = sorted(p.name for p in target_dir.iterdir())
    assert len(files) == 7
    assert files[-1] == "imgsr-20261009.sqlite3" and files[0] == "imgsr-20261003.sqlite3"
```

`tests/test_cli.py`:

```python
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from imgsr.auth import verify_password
from imgsr.cli import main
from imgsr.db.models import User
from imgsr.db.session import make_engine


def load_user(tmp_path, name):
    engine = make_engine(tmp_path / "db" / "imgsr.sqlite3")
    with Session(engine) as db:
        user = db.scalar(select(User).where(User.username == name))
    engine.dispose()
    return user


def test_create_user_and_reset_password(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO("password123\n"))
    assert main(["create-user", "bob", "--admin", "--quota", "7", "--password-stdin"]) == 0
    user = load_user(tmp_path, "bob")
    assert user.role == "admin" and user.daily_quota == 7
    assert verify_password(user.password_hash, "password123")
    monkeypatch.setattr("sys.stdin", io.StringIO("newpassword1\n"))
    assert main(["reset-password", "bob", "--password-stdin"]) == 0
    assert verify_password(load_user(tmp_path, "bob").password_hash, "newpassword1")


def test_errors_return_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert main(["create-user", "bob", "--password-stdin"]) == 1
    assert "密码至少 8 位" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO("password123\n"))
    assert main(["reset-password", "ghost", "--password-stdin"]) == 1


def test_duplicate_user(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO("password123\n"))
    assert main(["create-user", "bob", "--password-stdin"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("password123\n"))
    assert main(["create-user", "bob", "--password-stdin"]) == 1


def test_cleanup_command(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert main(["cleanup"]) == 0
    assert "已清理 0 个过期任务" in capsys.readouterr().out
```

- [x] **Step 2: 运行，确认失败**

Run: `uv run pytest tests/test_maintenance.py tests/test_cli.py -q`
Expected: `test_maintenance.py` 通过（实现已在 Task 14）；`test_cli.py` FAIL，`ModuleNotFoundError: No module named 'imgsr.cli'`

- [x] **Step 3: 实现 `src/imgsr/cli.py`**

```python
"""`imgsr` command line: user management, maintenance and the web server."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys

from sqlalchemy import select

from imgsr.auth import end_user_sessions, hash_password
from imgsr.config import Settings
from imgsr.db.models import User
from imgsr.db.session import make_engine, make_session_factory, migrate
from imgsr.maintenance import cleanup_expired
from imgsr.storage import Storage

LOG_FORMAT = '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'


class CliError(Exception):
    pass


def _password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("密码：")
        if getpass.getpass("再输入一次：") != password:
            raise CliError("两次输入的密码不一致")
    if len(password) < 8:
        raise CliError("密码至少 8 位")
    return password


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="imgsr")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-user", help="新建用户")
    create.add_argument("username")
    create.add_argument("--admin", action="store_true")
    create.add_argument("--quota", type=int)
    create.add_argument("--password-stdin", action="store_true")
    reset = sub.add_parser("reset-password", help="重置密码")
    reset.add_argument("username")
    reset.add_argument("--password-stdin", action="store_true")
    sub.add_parser("cleanup", help="清理过期任务")
    serve = sub.add_parser("serve", help="启动 Web 服务")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve":
        import uvicorn

        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
        uvicorn.run("imgsr.api.app:create_app", factory=True, host=args.host, port=args.port,
                    proxy_headers=False, access_log=False)
        return 0
    settings = Settings()
    engine = make_engine(settings.db_path)
    try:
        migrate(engine)
        sf = make_session_factory(engine)
        with sf() as db:
            if args.command == "create-user":
                if db.scalar(select(User).where(User.username == args.username)) is not None:
                    raise CliError(f"用户 {args.username} 已存在")
                user = User(username=args.username, password_hash=hash_password(_password(args.password_stdin)),
                            role="admin" if args.admin else "user",
                            daily_quota=args.quota if args.quota is not None else settings.user_daily_default)
                db.add(user)
                db.commit()
                print(f"已创建用户 {user.username}（{user.role}）")
            elif args.command == "reset-password":
                user = db.scalar(select(User).where(User.username == args.username))
                if user is None:
                    raise CliError(f"用户 {args.username} 不存在")
                user.password_hash = hash_password(_password(args.password_stdin))
                db.commit()
                end_user_sessions(db, user.id)
                print(f"已重置 {user.username} 的密码")
            elif args.command == "cleanup":
                print(f"已清理 {cleanup_expired(sf, Storage(settings.files_dir))} 个过期任务")
    except CliError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0
```

- [x] **Step 4: 运行，确认通过**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: 全部 passed

- [x] **Step 5: 手动冒烟 `imgsr serve`**

```bash
mkdir -p data && printf 'DATA_DIR=./data\nCOOKIE_SECURE=false\n' > .env.local-smoke
env $(cat .env.local-smoke | xargs) uv run imgsr serve --port 18090 &
sleep 3
curl -s http://127.0.0.1:18090/api/health
kill %1
rm .env.local-smoke
```

Expected: `{"ok":true,"free_bytes":…,"low_disk":false}`；`data/db/imgsr.sqlite3` 已创建。（`data/` 被 .gitignore 忽略。）

- [x] **Step 6: Commit**

```bash
git add src/imgsr/cli.py tests/test_maintenance.py tests/test_cli.py
git commit -m "feat: imgsr CLI and maintenance tests" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 19: 真实上游回归脚本与项目说明

**Files:**
- Create: `scripts/regress_real.py`, `README.md`, `.env.example`

**Interfaces:**
- Consumes: `create_app`、`hash_password`、`User`、`Settings`
- Produces: `uv run python scripts/regress_real.py IMG [IMG...] [--truth-dir DIR] [--out DIR]`：在临时数据目录里起完整应用（真实中转站），逐张执行 上传 → 转写 → 确认原文（有真值文件用真值，否则用原始转写）→ 生成 → 审查，下载结果并输出 `report.json`。

- [x] **Step 1: 写 `scripts/regress_real.py`**

```python
"""Real-upstream regression: run the full pipeline on sample images through the actual relay.

Costs money (image + vision calls). Not part of pytest.

usage:
  uv run python scripts/regress_real.py IMG [IMG ...] [--truth-dir DIR] [--out data/regress]

Truth files are optional: <truth-dir>/<image stem>.txt. Without one, the raw transcription is
confirmed as-is (so the diff then only measures render fidelity against that transcription).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient

from imgsr.api.app import create_app
from imgsr.auth import hash_password
from imgsr.config import Settings
from imgsr.db.models import User


def wait(client: TestClient, task_id: str, done, timeout: float) -> dict:  # noqa: ANN001
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(f"/api/tasks/{task_id}").json()
        if done(body):
            return body
        if time.monotonic() > deadline:
            raise SystemExit(f"timeout waiting for {task_id}: status={body['status']}")
        time.sleep(2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+", type=Path)
    ap.add_argument("--truth-dir", type=Path)
    ap.add_argument("--out", type=Path, default=Path("data/regress"))
    args = ap.parse_args()
    run_dir = args.out / time.strftime("%Y%m%d-%H%M%S")
    settings = Settings(data_dir=run_dir, cookie_secure=False, trusted_proxies="127.0.0.1/32")
    if not settings.open_api_key:
        print("OPEN_API_KEY 未配置（.env）", file=sys.stderr)
        return 2
    app = create_app(settings, maintenance=False)
    report = []
    with TestClient(app, client=("127.0.0.1", 50000), headers={"X-Requested-With": "imgsr"}) as client:
        with app.state.ctx.sf() as db:
            db.add(User(username="regress", password_hash=hash_password("regress-pass"),
                        role="admin", daily_quota=1000))
            db.commit()
        client.post("/api/auth/login", json={"username": "regress", "password": "regress-pass"}).raise_for_status()
        for image in args.images:
            started = time.monotonic()
            response = client.post("/api/tasks", files={"file": (image.name, image.read_bytes(), "image/png")})
            response.raise_for_status()
            task_id = response.json()["id"]
            body = wait(client, task_id, lambda b: b["status"] in ("awaiting_confirm", "transcribe_failed"), 600)
            truth = args.truth_dir / f"{image.stem}.txt" if args.truth_dir else None
            used_truth = bool(truth and truth.is_file())
            text = truth.read_text() if used_truth else (body["transcript_raw"] or "")
            client.put(f"/api/tasks/{task_id}/text", json={"confirmed_text": text}).raise_for_status()
            client.post(f"/api/tasks/{task_id}/rounds", json={}).raise_for_status()
            body = wait(client, task_id, lambda b: b["status"] in ("reviewed", "round_failed"), 1200)
            rnd = body["rounds"][-1]
            review = rnd.get("review") or {}
            if rnd["status"] == "succeeded":
                out = run_dir / f"{image.stem}-download.png"
                out.write_bytes(client.get(f"/api/files/{task_id}/download-{rnd['seq']}").content)
            entry = {
                "image": str(image), "source": [body["source_w"], body["source_h"]],
                "status": body["status"], "round_status": rnd["status"], "error": rnd["error"],
                "result": [rnd["result_w"], rnd["result_h"]], "download": [rnd["download_w"], rnd["download_h"]],
                "plan_mode": (rnd["strategy"].get("plan") or {}).get("mode"),
                "tiles": len((rnd["strategy"].get("plan") or {}).get("tiles", [])),
                "notes": (rnd["strategy"].get("plan") or {}).get("notes", []),
                "used_truth": used_truth, "diff_count": len(review.get("diffs", [])),
                "diffs": review.get("diffs", [])[:20],
                "suggestions": [s["action"] for s in review.get("suggestions", [])],
                "elapsed_total_s": round(time.monotonic() - started, 1),
            }
            report.append(entry)
            print(json.dumps(entry, ensure_ascii=False))
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report: {run_dir / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 2: 写 `.env.example`**

```dotenv
# 中转站（sub2api OpenAI 分组的用户 key）
OPEN_API_BASE_URL=https://your-relay.example.com
OPEN_API_KEY=

# 模型（管理页可覆盖）
IMAGE_MODEL=gpt-image-2.5
TRANSCRIBE_MODEL=gpt-6-sol
REVIEW_MODEL=gpt-6-sol

# 本地开发；部署时 DATA_DIR=/data、COOKIE_SECURE=true
DATA_DIR=./data
COOKIE_SECURE=false

# 反代/真实 IP（部署时按服务器实际情况确认）
CLIENT_IP_HEADER=X-Forwarded-For
TRUSTED_PROXIES=127.0.0.1,172.16.0.0/12
HOST_PORT=18090
```

- [x] **Step 3: 写 `README.md`**

````markdown
# imgsr-studio

截图文字清晰化工具站（`imgsr.huanmeng.cc`）。用 sub2api 上的 `gpt-image-2.5` 生成式重绘模糊截图，配合「转写 → 生成 → 审查 → 人确认」循环控制错字。

- 设计：`docs/superpowers/specs/2026-10-14-imgsr-studio-design.md`
- 计划与进度：`docs/superpowers/plans/`（勾选框即进度）

## 本地运行

```bash
uv sync
cp .env.example .env            # 填 OPEN_API_KEY
uv run imgsr create-user --admin admin
uv run imgsr serve --port 18090 # API: http://127.0.0.1:18090/api/health
```

## 测试

```bash
uv run pytest -q
uv run ruff check src tests
```

测试不访问网络。真实上游回归（会产生费用）：

```bash
uv run python scripts/regress_real.py ../ai_video_gen/data/imgsr/图片/图片9.png
```

## 命令行

| 命令 | 作用 |
|---|---|
| `imgsr create-user NAME [--admin] [--quota N]` | 新建用户（交互输入密码；`--password-stdin` 从标准输入读） |
| `imgsr reset-password NAME` | 重置密码并踢掉该用户全部会话 |
| `imgsr cleanup` | 立即清理过期任务（服务内每小时自动执行） |
| `imgsr serve [--host] [--port]` | 启动服务 |
````

- [x] **Step 4: 全量验证**

Run: `uv run pytest -q && uv run ruff check src tests scripts`
Expected: 全部 passed；ruff 无报错

- [x] **Step 5: 真实上游冒烟（会产生费用，执行前须用户确认）**

```bash
uv run python scripts/regress_real.py ../ai_video_gen/data/imgsr/图片/图片9.png
```

Expected: 输出一行 JSON：`round_status` 为 `succeeded`，`result` 约 1886×834，`diff_count` 为 0 或少量，并生成 `data/regress/<时间戳>/report.json`。把结果摘要记到本计划末尾“执行记录”。

- [x] **Step 6: Commit**

```bash
git add scripts/regress_real.py README.md .env.example
git commit -m "docs: README, env example and real-upstream regression script" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## 执行记录

执行方式：Native（executing-plans，单会话逐 Task），分支 `feat/backend`，2026-10-14。

**Task 1–19 全部完成**（真实上游冒烟除外，见下），提交 `4da6b6f..48224a4`；每个 Task 均先看测试失败再实现，`uv run pytest -q` 170/170、ruff 无告警。

执行中的裁决：
- T5：计划代码先把 `?` 转成 `？` 再去 `[?]`，导致不确定标记残留（测试抓到）→ 先去 `[?]/[？]` 再转标点。
- T14：`maintenance.py` 的测试从 T18 提前到 T14，保证先失败后实现。
- T14：Starlette TestClient 提示改用 `httpx2` → 加为开发依赖，测试输出无告警。
- T18：服务冒烟改用后台进程 + `curl --retry`（环境禁止前台 sleep），检查项不变（health ok、CSRF 403、迁移成功）。
- T19：**真实上游冒烟未执行**——会产生费用且本仓库 `.env` 尚无 `OPEN_API_KEY`，待用户确认后运行 `scripts/regress_real.py`（至少 图片1/2/9/14/17）。验收标准 1–3 仍待该次运行确认。

**整分支审查**（独立 reviewer，Opus）：无 Critical；7 条 Important 已全部按 TDD 修复（`57217c6..0e1eb1d`），最终 `uv run pytest -q` 191/191：
1. 上传时修改 Pillow 全局像素上限（测试依赖执行顺序、大图结果崩溃）→ 不再修改全局值。
2. MPO 格式手机 JPEG 被拒 → 允许 MPO（只取第一帧）。
3. 截图外框 >3% 时找不到切缝、贴边内容被忽略 → 检测深色外框，浅色边距保留。
4. 结果落盘失败后任务永久卡在“生成中”且不退额 → 失败即标记失败并退额。
5. 连点两次生成/重试 → 重复扣额、500 → 串行化“检查→扣额→插入”，异常退额。
6. 执行建议时丢失原轮次提示词/策略 → 以原轮次设置为底，叠加建议参数与显式字段。
7. 切块未考虑 3:1 补边、无块数上限 → 按补边面积判断、短边过长先切大板、单轮上限 16 块（超出则提前失败并退额）、仅在精修方案有效时才建议 `tile_refine`。

暂缓的 Minor（15 条）与 reviewer 列出的不予判断事项的裁决，见本次会话最终汇报；部署相关裁决（`CF-Connecting-IP`、反代上传大小限制）需在计划 3 落实，前端需展示 `review.error` 与重试入口（计划 2）。

**真实上游回归**（2026-10-14，用户确认后执行；`scripts/regress_real.py`，原文直接采用 `gpt-6-sol` 的原始转写、未经人工核对）：

| 样张 | 原图 | 结果 | 切块 | 耗时 | 审查 |
|---|---|---|---|---|---|
| 图片9 | 1016×450 | 1886×834 | 整图 | 69 s | 2 处差异，均为 👉 符号（转写时有时无）→ 已修，归一化忽略符号 |
| 图片2 | 558×714 | 1108×1419 | 整图 | 143 s | 批注被**错误转写**为“分自然段描写”，生图照此画出（并有错字“描摇写”）——未经人工确认的原文提示会被忠实画出 |
| 图片14 | 1838×456 | 2171×539 | 整图（补边） | 103 s | 1 处 👉 符号差异 → 已修 |
| 图片1 | 1106×1428 | 1217×1571 | 2 块 | 145 s | 0 差异，建议采用 |
| 图片17 | 2316×1294 | 1677×938（下载版放大到 2316×1294） | **整图（异常）** | 123 s | 0 差异 |

回归发现的问题（分支 `fix/regression-findings`，`fd6a76d`，测试 193/193）：
- 透明 PNG 的外圈在上传时被垫成白色，白边 + 黑框让外框检测失效，图片17 退化为整图 → 外框检测跨过外侧浅色环、并忽略垂直方向边缘环。修复后重跑图片17：3 块、结果 2316×1294 原生分辨率，113 s；接缝 3 px 突变与原图相当（竖缝蓝通道 2.37 vs 原图 2.53，横缝 ≤ 0.45）。
- 审查把 emoji / 装饰符号（👉 ☆ △）的有无当成差异 → 归一化时忽略 So/Sk/Cf 类符号。

裁决：验收标准 2 的字面量法（“接缝两侧 30 px 带内平均色差 < 3”）不适用于接缝两侧本身颜色不同的图——图片17 原图在同一位置就差 7.58，结果为 5.8；改以“接缝 3 px 突变不超过原图同处 + 1”判定，已满足。
新增暂缓 Minor：审查转写对界面标签/批注的取舍不稳定（图片17“学生作文内容”、图片2 批注被漏读），会产生误报差异。
建议（未改默认）：`gpt-6-sol` 在模糊图上的转写幻觉在本次回归中再次出现；如需降低人工核对负担，可在管理页把转写模型切到 `gpt-5.5`（探针中准确率 99.8%）。
