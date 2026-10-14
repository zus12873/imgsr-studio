from sqlalchemy import select

from imgsr.db.models import User
from tests.api.helpers import add_user, login


def test_login_me_logout(api):
    add_user(api)
    body = login(api.client).json()
    assert body["username"] == "alice" and body["used_today"] == 0
    assert "imgsr_session" in api.client.cookies
    assert api.client.get("/api/me").json()["role"] == "user"
    assert api.client.post("/api/auth/logout").status_code == 200
    assert api.client.get("/api/me").status_code == 401


def test_wrong_password_and_disabled_user(api):
    add_user(api)
    add_user(api, "bob", role="user")
    with api.ctx.sf() as db:
        db.scalar(select(User).where(User.username == "bob")).disabled = True
        db.commit()
    r = api.client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    assert r.status_code == 401 and r.json()["detail"] == "用户名或密码错误"
    r = api.client.post("/api/auth/login", json={"username": "bob", "password": "password123"})
    assert r.status_code == 401


def test_login_lockout_after_ten_failures(api):
    add_user(api)
    for _ in range(10):
        api.client.post("/api/auth/login", json={"username": "alice", "password": "nope"})
    r = api.client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
    assert r.status_code == 429


def test_mutations_require_csrf_header(api):
    add_user(api)
    r = api.client.post("/api/auth/login", json={"username": "alice", "password": "password123"},
                        headers={"X-Requested-With": ""})
    assert r.status_code == 403


def test_health(api):
    body = api.client.get("/api/health").json()
    assert body["ok"] is True and body["free_bytes"] > 0 and body["low_disk"] is False
