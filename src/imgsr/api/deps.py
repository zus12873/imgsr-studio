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
