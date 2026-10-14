"""Guest (no login) single-round generation with per-IP and global daily caps."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imgsr import quota
from imgsr.api.deps import AppContext, client_ip, db_session, get_ctx, read_upload
from imgsr.api.schemas import ACTIVE, GuestTaskOut, guest_task_out
from imgsr.auth import GUEST_COOKIE, new_token, token_hash
from imgsr.config import Settings
from imgsr.db.models import Job, Round, Task, utcnow
from imgsr.pipeline.prompt import BASE_PROMPT
from imgsr.storage import TASK_ID_RE

router = APIRouter(prefix="/api/guest")


def _guest_token(request: Request, response: Response, s: Settings) -> str:
    token = request.cookies.get(GUEST_COOKIE) or ""
    if not 20 <= len(token) <= 100:
        token = new_token()
    response.set_cookie(GUEST_COOKIE, token, max_age=s.retention_guest_hours * 3600, httponly=True,
                        secure=s.cookie_secure, samesite="lax", path="/")
    return token


def _ip_generating(db: Session, ip: str) -> bool:
    return bool(db.scalar(
        select(func.count()).select_from(Job).join(Task, Task.id == Job.task_id)
        .where(Task.owner_user_id.is_(None), Task.client_ip == ip, Job.kind == "generate",
               Job.status.in_(ACTIVE))
    ))


@router.post("/tasks", status_code=201)
async def guest_upload(request: Request, response: Response, file: UploadFile = File(...),
                       prompt: str | None = Form(None, max_length=8_000),
                       db: Session = Depends(db_session), c: AppContext = Depends(get_ctx),
                       ip: str = Depends(client_ip)) -> GuestTaskOut:
    s = c.settings()
    img = await read_upload(file, c)
    if _ip_generating(db, ip):
        raise HTTPException(409, "当前网络已有任务在处理中，请稍候")
    try:
        charge = quota.consume(db, [
            (f"ip:{ip}", s.guest_daily_per_ip, "今日免费次数已用完，登录后可继续使用"),
            ("guest:global", s.guest_daily_global, "今日游客总额度已用完，请明天再来"),
        ], quota.today())
    except quota.QuotaExceeded as exc:
        raise HTTPException(429, str(exc)) from exc
    token = _guest_token(request, response, s)
    task_id = uuid.uuid4().hex
    try:
        await asyncio.to_thread(c.storage.save_source, task_id, img)
    except Exception:
        quota.refund(db, charge)
        raise
    task = Task(id=task_id, owner_user_id=None, guest_token_hash=token_hash(token), client_ip=ip,
                source_w=img.width, source_h=img.height, status="generating",
                expires_at=utcnow() + timedelta(hours=s.retention_guest_hours))
    db.add(task)
    db.flush()
    rnd = Round(task_id=task_id, seq=1, image_model=s.image_model,
                prompt=(prompt or "").strip() or BASE_PROMPT,
                strategy={"mode": "auto", "preupscale": 1}, use_text_hint=False, status="queued",
                charge=charge)
    db.add(rnd)
    db.flush()
    job = Job(kind="generate", task_id=task_id, round_id=rnd.id)
    db.add(job)
    db.commit()
    c.runner.enqueue(job.id)
    return guest_task_out(task)


@router.get("/tasks/{task_id}")
def guest_task(task_id: str, request: Request, db: Session = Depends(db_session)) -> GuestTaskOut:
    token = request.cookies.get(GUEST_COOKIE)
    task = db.get(Task, task_id) if TASK_ID_RE.fullmatch(task_id) else None
    if (task is None or task.owner_user_id is not None or not token
            or task.guest_token_hash != token_hash(token)):
        raise HTTPException(404, "任务不存在")
    return guest_task_out(task)


@router.get("/quota")
def guest_quota(db: Session = Depends(db_session), c: AppContext = Depends(get_ctx),
                ip: str = Depends(client_ip)) -> dict:
    s = c.settings()
    day = quota.today()
    return {
        "limit": s.guest_daily_per_ip,
        "remaining": max(0, s.guest_daily_per_ip - quota.used(db, f"ip:{ip}", day)),
        "global_remaining": max(0, s.guest_daily_global - quota.used(db, "guest:global", day)),
    }
