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
