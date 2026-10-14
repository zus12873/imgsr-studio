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
