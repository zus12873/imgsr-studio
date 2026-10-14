"""Serve task images to their owner (logged-in user or the guest cookie holder)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from imgsr.api.deps import AppContext, current_user_optional, db_session, get_ctx
from imgsr.auth import GUEST_COOKIE, token_hash
from imgsr.db.models import Task, User
from imgsr.storage import TASK_ID_RE

router = APIRouter(prefix="/api/files")


def _allowed(task: Task | None, user: User | None, guest_cookie: str | None) -> bool:
    if task is None:
        return False
    if task.owner_user_id is not None:
        return user is not None and user.id == task.owner_user_id
    return bool(guest_cookie) and task.guest_token_hash == token_hash(guest_cookie)


@router.get("/{task_id}/{name}")
def get_file(task_id: str, name: str, request: Request, download: bool = False,
             user: User | None = Depends(current_user_optional), db: Session = Depends(db_session),
             c: AppContext = Depends(get_ctx)) -> FileResponse:
    task = db.get(Task, task_id) if TASK_ID_RE.fullmatch(task_id) else None
    if not _allowed(task, user, request.cookies.get(GUEST_COOKIE)):
        raise HTTPException(404, "文件不存在")
    path = c.storage.named(task_id, name)
    if path is None:
        raise HTTPException(404, "文件不存在")
    headers = {"Cache-Control": "private, max-age=3600"}
    if download:
        return FileResponse(path, headers=headers, filename=f"imgsr-{task_id[:8]}-{name}{path.suffix}")
    return FileResponse(path, headers=headers)
