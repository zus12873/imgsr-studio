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
