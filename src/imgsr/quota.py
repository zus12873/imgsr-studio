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
