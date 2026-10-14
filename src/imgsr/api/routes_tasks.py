"""Logged-in user's tasks: upload, confirm text, rounds, final, delete."""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from imgsr import quota
from imgsr.api.deps import AppContext, client_ip, current_user, db_session, get_ctx, read_upload
from imgsr.api.schemas import ACTIVE, FinalIn, RoundIn, TaskOut, TaskSummary, TextIn, task_out
from imgsr.db.models import Job, Round, Task, User, utcnow
from imgsr.pipeline.prompt import BASE_PROMPT
from imgsr.storage import TASK_ID_RE

router = APIRouter(prefix="/api/tasks")
# Serialises check → charge → insert so a double-clicked submit cannot charge twice or race
# on (task_id, seq). Sync endpoints run in the threadpool, so a thread lock is enough here.
_ROUND_LOCK = threading.Lock()
EXECUTABLE = {"retry_with_hint", "tile_refine"}


def own_task(db: Session, task_id: str, user: User) -> Task:
    task = db.get(Task, task_id) if TASK_ID_RE.fullmatch(task_id) else None
    if task is None or task.owner_user_id != user.id:
        raise HTTPException(404, "任务不存在")
    return task


def task_busy(db: Session, task_id: str) -> bool:
    return bool(db.scalar(
        select(func.count()).select_from(Job).where(Job.task_id == task_id, Job.status.in_(ACTIVE))
    ))


def user_generating(db: Session, user_id: int) -> bool:
    return bool(db.scalar(
        select(func.count()).select_from(Job).join(Task, Task.id == Job.task_id)
        .where(Task.owner_user_id == user_id, Job.kind == "generate", Job.status.in_(ACTIVE))
    ))


def charge_user(db: Session, user: User) -> dict:
    try:
        return quota.consume(
            db, [(f"user:{user.id}", user.daily_quota, "今日生成次数已用完，明天再来或联系管理员调整额度")],
            quota.today(),
        )
    except quota.QuotaExceeded as exc:
        raise HTTPException(429, str(exc)) from exc


def _suggestion_params(db: Session, task: Task, round_id: int, index: int) -> dict:
    """Settings for executing a suggestion: the source round's settings, overlaid with the
    suggestion's params ("其余沿用", spec §6.5)."""
    src = db.get(Round, round_id)
    suggestions = (src.review or {}).get("suggestions", []) if src and src.task_id == task.id else []
    if not 0 <= index < len(suggestions):
        raise HTTPException(400, "建议不存在")
    suggestion = suggestions[index]
    if suggestion.get("action") not in EXECUTABLE:
        raise HTTPException(400, "该建议不需要生成新一轮")
    base = {"prompt": src.prompt, "strategy": src.strategy.get("mode", "auto"),
            "preupscale": src.strategy.get("preupscale", 1), "use_text_hint": src.use_text_hint}
    return {**base, **(suggestion.get("params") or {})}


@router.post("", status_code=201)
async def upload(file: UploadFile = File(...), user: User = Depends(current_user),
                 db: Session = Depends(db_session), c: AppContext = Depends(get_ctx),
                 ip: str = Depends(client_ip)) -> TaskOut:
    img = await read_upload(file, c)
    task_id = uuid.uuid4().hex
    await asyncio.to_thread(c.storage.save_source, task_id, img)
    task = Task(id=task_id, owner_user_id=user.id, client_ip=ip, source_w=img.width,
                source_h=img.height, status="uploaded",
                expires_at=utcnow() + timedelta(days=c.settings().retention_user_days))
    db.add(task)
    db.flush()
    job = Job(kind="transcribe", task_id=task_id)
    db.add(job)
    db.commit()
    c.runner.enqueue(job.id)
    return task_out(db, task)


@router.get("")
def list_tasks(cursor: datetime | None = None, limit: int = Query(20, ge=1, le=100),
               user: User = Depends(current_user), db: Session = Depends(db_session)) -> dict:
    q = select(Task).where(Task.owner_user_id == user.id)
    if cursor is not None:
        q = q.where(Task.created_at < cursor)
    tasks = db.scalars(q.order_by(Task.created_at.desc()).limit(limit)).all()
    items = [TaskSummary(id=t.id, status=t.status, source_w=t.source_w, source_h=t.source_h,
                         created_at=t.created_at, final_round_id=t.final_round_id,
                         rounds=len(t.rounds)) for t in tasks]
    return {"items": items, "next_cursor": tasks[-1].created_at if len(tasks) == limit else None}


@router.get("/{task_id}")
def get_task(task_id: str, user: User = Depends(current_user),
             db: Session = Depends(db_session)) -> TaskOut:
    return task_out(db, own_task(db, task_id, user))


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, user: User = Depends(current_user), db: Session = Depends(db_session),
                c: AppContext = Depends(get_ctx)) -> Response:
    task = own_task(db, task_id, user)
    db.delete(task)
    db.commit()
    c.storage.delete_task(task_id)
    return Response(status_code=204)


@router.put("/{task_id}/text")
def confirm_text(task_id: str, body: TextIn, user: User = Depends(current_user),
                 db: Session = Depends(db_session)) -> TaskOut:
    task = own_task(db, task_id, user)
    if task_busy(db, task.id):
        raise HTTPException(409, "任务正在处理中，请稍后再改原文")
    task.confirmed_text = body.confirmed_text.strip()
    if task.status in ("uploaded", "awaiting_confirm", "transcribe_failed"):
        task.status = "ready"
    db.commit()
    return task_out(db, task)


@router.post("/{task_id}/transcribe")
def retry_transcribe(task_id: str, user: User = Depends(current_user),
                     db: Session = Depends(db_session), c: AppContext = Depends(get_ctx)) -> TaskOut:
    task = own_task(db, task_id, user)
    if task_busy(db, task.id):
        raise HTTPException(409, "任务正在处理中")
    task.status, task.error = "uploaded", None
    job = Job(kind="transcribe", task_id=task.id)
    db.add(job)
    db.commit()
    c.runner.enqueue(job.id)
    return task_out(db, task)


@router.post("/{task_id}/rounds", status_code=201)
def create_round(task_id: str, body: RoundIn, user: User = Depends(current_user),
                 db: Session = Depends(db_session), c: AppContext = Depends(get_ctx)) -> TaskOut:
    with _ROUND_LOCK:
        task = own_task(db, task_id, user)
        if task.status in ("uploaded", "transcribing"):
            raise HTTPException(409, "请等待原文转写完成")
        if task_busy(db, task.id):
            raise HTTPException(409, "该任务正在处理中")
        if user_generating(db, user.id):
            raise HTTPException(409, "你已有一个生成任务在进行中")
        params = {"prompt": body.prompt, "strategy": body.strategy, "preupscale": body.preupscale,
                  "use_text_hint": body.use_text_hint}
        if body.suggestion is not None:
            explicit = {k: params[k] for k in body.model_fields_set if k in params}
            params = {**_suggestion_params(db, task, body.suggestion.round_id, body.suggestion.index),
                      **explicit}
        has_text = bool((task.confirmed_text or "").strip())
        charge = charge_user(db, user)
        try:
            seq = (db.scalar(select(func.max(Round.seq)).where(Round.task_id == task.id)) or 0) + 1
            rnd = Round(task_id=task.id, seq=seq, image_model=c.settings().image_model,
                        prompt=(params["prompt"] or "").strip() or BASE_PROMPT,
                        strategy={"mode": params["strategy"], "preupscale": params["preupscale"]},
                        use_text_hint=bool(params["use_text_hint"]) and has_text, status="queued",
                        charge=charge)
            db.add(rnd)
            task.status = "generating"
            db.flush()
            job = Job(kind="generate", task_id=task.id, round_id=rnd.id)
            db.add(job)
            db.commit()
        except Exception:
            db.rollback()
            quota.refund(db, charge)
            raise
    c.runner.enqueue(job.id)
    return task_out(db, task)


@router.post("/{task_id}/rounds/{seq}/retry")
def retry_round(task_id: str, seq: int, user: User = Depends(current_user),
                db: Session = Depends(db_session), c: AppContext = Depends(get_ctx)) -> TaskOut:
    with _ROUND_LOCK:
        task = own_task(db, task_id, user)
        rnd = db.scalar(select(Round).where(Round.task_id == task.id, Round.seq == seq))
        if rnd is None:
            raise HTTPException(404, "轮次不存在")
        if task_busy(db, task.id):
            raise HTTPException(409, "任务正在处理中")
        charge = None
        if rnd.status == "failed":
            if user_generating(db, user.id):
                raise HTTPException(409, "你已有一个生成任务在进行中")
            charge = charge_user(db, user)
            kind = "generate"
        elif rnd.status == "succeeded" and rnd.review and rnd.review.get("error"):
            kind = "review"
        else:
            raise HTTPException(409, "该轮次无需重试")
        try:
            if kind == "generate":
                rnd.status, rnd.error, rnd.charge = "queued", None, charge
                rnd.strategy = {"mode": rnd.strategy.get("mode", "auto"),
                                "preupscale": rnd.strategy.get("preupscale", 1)}
                task.status = "generating"
            else:
                task.status = "reviewing"
            job = Job(kind=kind, task_id=task.id, round_id=rnd.id)
            db.add(job)
            db.commit()
        except Exception:
            db.rollback()
            quota.refund(db, charge)
            raise
    c.runner.enqueue(job.id)
    return task_out(db, task)


@router.post("/{task_id}/final")
def set_final(task_id: str, body: FinalIn, user: User = Depends(current_user),
              db: Session = Depends(db_session)) -> TaskOut:
    task = own_task(db, task_id, user)
    rnd = db.get(Round, body.round_id)
    if rnd is None or rnd.task_id != task.id or rnd.status != "succeeded":
        raise HTTPException(400, "只能选择已成功的轮次")
    task.final_round_id, task.status = rnd.id, "done"
    db.commit()
    return task_out(db, task)
