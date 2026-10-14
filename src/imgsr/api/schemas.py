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
