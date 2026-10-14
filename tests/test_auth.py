from datetime import timedelta

from sqlalchemy import select

from imgsr.auth import (
    LoginLimiter,
    create_session,
    end_session,
    end_user_sessions,
    hash_password,
    user_for_token,
    verify_password,
)
from imgsr.db.models import SessionRow, User, utcnow


def test_password_roundtrip():
    stored = hash_password("password123")
    assert verify_password(stored, "password123")
    assert not verify_password(stored, "nope")
    assert not verify_password("garbage", "x")


def test_session_lifecycle(sf, make_user):
    uid = make_user()
    with sf() as db:
        token = create_session(db, db.get(User, uid), days=14)
        assert user_for_token(db, token, 14).id == uid
        assert user_for_token(db, "wrong", 14) is None
        assert user_for_token(db, None, 14) is None
        end_session(db, token)
        assert user_for_token(db, token, 14) is None


def test_expired_and_disabled_sessions(sf, make_user):
    uid = make_user()
    with sf() as db:
        user = db.get(User, uid)
        old = create_session(db, user, days=1, now=utcnow() - timedelta(days=2))
        assert user_for_token(db, old, 1) is None
        token = create_session(db, user, days=14)
        user.disabled = True
        db.commit()
        assert user_for_token(db, token, 14) is None


def test_session_slides_forward(sf, make_user):
    uid = make_user()
    with sf() as db:
        t0 = utcnow() - timedelta(days=10)
        token = create_session(db, db.get(User, uid), 14, now=t0)
        later = t0 + timedelta(days=10)
        user_for_token(db, token, 14, now=later)
        row = db.scalar(select(SessionRow))
        assert row.expires_at == later + timedelta(days=14)


def test_end_user_sessions(sf, make_user):
    uid = make_user()
    with sf() as db:
        token = create_session(db, db.get(User, uid), 14)
        end_user_sessions(db, uid)
        assert user_for_token(db, token, 14) is None


def test_login_limiter():
    limiter = LoginLimiter(max_failures=3, window=timedelta(minutes=15))
    t = utcnow()
    for _ in range(3):
        limiter.failed("1.1.1.1", t)
    assert limiter.locked("1.1.1.1", t)
    assert not limiter.locked("2.2.2.2", t)
    assert not limiter.locked("1.1.1.1", t + timedelta(minutes=16))
    limiter.failed("3.3.3.3", t)
    limiter.succeeded("3.3.3.3")
    assert not limiter.locked("3.3.3.3", t)
