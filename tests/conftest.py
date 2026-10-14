import uuid
from datetime import timedelta

import pytest

from imgsr.auth import hash_password
from imgsr.db.models import Base, Task, User, utcnow
from imgsr.db.session import make_engine, make_session_factory


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "db" / "test.sqlite3")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def sf(engine):
    return make_session_factory(engine)


@pytest.fixture
def make_user(sf):
    def _make(username="alice", password="password123", role="user", daily_quota=50):
        with sf() as db:
            user = User(
                username=username,
                password_hash=hash_password(password),
                role=role,
                daily_quota=daily_quota,
            )
            db.add(user)
            db.commit()
            return user.id

    return _make


@pytest.fixture
def make_task(sf):
    def _make(task_id=None, *, owner=None, ip="1.2.3.4", w=100, h=100, status="uploaded",
              expires_at=None, **kw):
        tid = task_id or uuid.uuid4().hex
        with sf() as db:
            db.add(Task(id=tid, owner_user_id=owner, client_ip=ip, source_w=w, source_h=h,
                        status=status, expires_at=expires_at or utcnow() + timedelta(days=1), **kw))
            db.commit()
        return tid

    return _make
