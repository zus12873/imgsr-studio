"""Login, logout and the current user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from imgsr import quota
from imgsr.api.deps import AppContext, client_ip, current_user, db_session, get_ctx
from imgsr.auth import SESSION_COOKIE, create_session, end_session, verify_password
from imgsr.db.models import User

router = APIRouter(prefix="/api")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class MeOut(BaseModel):
    id: int
    username: str
    role: str
    daily_quota: int
    used_today: int


def me_out(db: Session, user: User) -> MeOut:
    return MeOut(id=user.id, username=user.username, role=user.role, daily_quota=user.daily_quota,
                 used_today=quota.used(db, f"user:{user.id}", quota.today()))


@router.post("/auth/login")
def login(body: LoginIn, response: Response, db: Session = Depends(db_session),
          c: AppContext = Depends(get_ctx), ip: str = Depends(client_ip)) -> MeOut:
    if c.limiter.locked(ip):
        raise HTTPException(429, "登录失败次数过多，请 15 分钟后再试")
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or user.disabled or not verify_password(user.password_hash, body.password):
        c.limiter.failed(ip)
        raise HTTPException(401, "用户名或密码错误")
    c.limiter.succeeded(ip)
    s = c.settings()
    token = create_session(db, user, s.session_days)
    response.set_cookie(SESSION_COOKIE, token, max_age=s.session_days * 86_400, httponly=True,
                        secure=s.cookie_secure, samesite="lax", path="/")
    return me_out(db, user)


@router.post("/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(db_session)) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        end_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(db_session)) -> MeOut:
    return me_out(db, user)
