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
