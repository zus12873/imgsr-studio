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
from imgsr.pipeline.tiling import MAX_TILES, Box, PlanTooLarge, Tile, TilePlan, plan_tiles
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
    if isinstance(exc, PlanTooLarge):
        return str(exc)
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
            if len(plan.tiles) > MAX_TILES:
                raise PlanTooLarge(f"需要切 {len(plan.tiles)} 块，超过单轮上限 {MAX_TILES} 块。"
                                   "请关闭预放大，或裁剪图片后再试")
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
        try:
            review_id = await self._store_round(ctx, plan, result, download, scale, started)
        except Exception as exc:
            # Without this the round stays "running" and the task "generating" forever.
            if self._fail_round(ctx, _message(exc)):
                raise
            self.svc.storage.delete_task(ctx.task_id)
            return
        if review_id is not None:
            self.svc.enqueue(review_id)

    async def _store_round(self, ctx: _Gen, plan: TilePlan, result: Image.Image,
                           download: Image.Image, scale: float, started: float) -> int | None:
        """Persist a rendered round; returns the review job id to enqueue (None if not needed)."""
        if not self._task_exists(ctx.task_id):
            self.svc.storage.delete_task(ctx.task_id)
            return None
        await asyncio.to_thread(save_png, result, self.svc.storage.result(ctx.task_id, ctx.seq))
        await asyncio.to_thread(save_png, download, self.svc.storage.download(ctx.task_id, ctx.seq))
        with self.svc.session_factory() as db:
            rnd = db.get(Round, ctx.round_id)
            if rnd is None:
                self.svc.storage.delete_task(ctx.task_id)
                return None
            task = rnd.task
            rnd.status = "succeeded"
            rnd.result_w, rnd.result_h = result.size
            rnd.download_w, rnd.download_h = download.size
            rnd.elapsed_s = round(time.monotonic() - started, 1)
            rnd.strategy = {**rnd.strategy, "plan": plan.to_json(), "scale": scale}
            review_id = None
            if ctx.owned:
                task.status = "reviewing"
                review_job = Job(kind="review", task_id=task.id, round_id=rnd.id)
                db.add(review_job)
                db.flush()
                review_id = review_job.id
            else:
                task.status, task.final_round_id = "done", rnd.id
            db.commit()
            return review_id

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
            source = await asyncio.to_thread(_load_rgb, self.svc.storage.source(task_id))
            refine_plan = await asyncio.to_thread(plan_tiles, source, s.pixel_cap, "tiles", 2)
            can_refine = refine_plan.mode == "tiles" and len(refine_plan.tiles) <= MAX_TILES
        except Exception as exc:
            error = _first_error(exc)
            fallback = Suggestion("manual_check", "审查失败，请人工核对或重试审查").to_json()
            if self._finish_review(round_id, {"model": s.review_model, "error": _message(error),
                                              "transcript": "", "diffs": [], "suggestions": [fallback]}):
                raise error from None
            return
        diffs = compare(confirmed, transcript)
        sugs = suggest(diffs, has_text=True, used_hint=used_hint, preupscale=pre, previous=previous,
                       can_refine=can_refine)
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
