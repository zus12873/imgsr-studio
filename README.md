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
