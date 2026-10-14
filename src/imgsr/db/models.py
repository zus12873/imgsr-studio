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
