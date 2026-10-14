from imgsr.auth import create_session, user_for_token
from imgsr.db.models import User
from tests.api.helpers import add_user, login, upload, wait_task


def as_admin(api):
    uid = add_user(api, "root", role="admin")
    login(api.client, "root")
    return uid


def test_non_admin_is_forbidden(api):
    add_user(api)
    login(api.client)
    assert api.client.get("/api/admin/users").status_code == 403


def test_create_user_then_login(api):
    as_admin(api)
    r = api.client.post("/api/admin/users", json={"username": "carol", "password": "password123"})
    assert r.status_code == 201 and r.json()["daily_quota"] == 50 and r.json()["role"] == "user"
    dup = api.client.post("/api/admin/users", json={"username": "carol", "password": "password123"})
    assert dup.status_code == 409
    bad = api.client.post("/api/admin/users", json={"username": "x y", "password": "short"})
    assert bad.status_code == 422
    api.client.cookies.clear()
    login(api.client, "carol")


def test_disable_and_password_reset_end_sessions(api):
    as_admin(api)
    uid = add_user(api, "dave")
    with api.ctx.sf() as db:
        token = create_session(db, db.get(User, uid), 14)
    assert api.client.patch(f"/api/admin/users/{uid}", json={"password": "newpassword1"}).status_code == 200
    with api.ctx.sf() as db:
        assert user_for_token(db, token, 14) is None
        token = create_session(db, db.get(User, uid), 14)
    body = api.client.patch(f"/api/admin/users/{uid}", json={"disabled": True, "daily_quota": 5}).json()
    assert body["disabled"] is True and body["daily_quota"] == 5
    with api.ctx.sf() as db:
        assert user_for_token(db, token, 14) is None


def test_admin_cannot_disable_or_demote_self(api):
    uid = as_admin(api)
    assert api.client.patch(f"/api/admin/users/{uid}", json={"disabled": True}).status_code == 400
    assert api.client.patch(f"/api/admin/users/{uid}", json={"role": "user"}).status_code == 400


def test_list_users(api):
    as_admin(api)
    add_user(api, "erin")
    names = [u["username"] for u in api.client.get("/api/admin/users").json()]
    assert names == ["root", "erin"]


def test_settings_override_changes_next_round_model(api):
    as_admin(api)
    r = api.client.patch("/api/admin/settings", json={"image_model": "gpt-image-2"})
    assert r.status_code == 200
    assert r.json()["effective"]["image_model"] == "gpt-image-2"
    assert "open_api_key" not in r.json()["effective"]
    tid = upload(api.client).json()["id"]
    wait_task(api.client, tid, lambda b: b["status"] == "awaiting_confirm")
    api.client.put(f"/api/tasks/{tid}/text", json={"confirmed_text": "默认转写文字。"})
    api.client.post(f"/api/tasks/{tid}/rounds", json={})
    body = wait_task(api.client, tid, lambda b: b["status"] == "reviewed")
    assert body["rounds"][0]["image_model"] == "gpt-image-2"
    assert api.images.calls[-1]["model"] == "gpt-image-2"


def test_settings_validation(api):
    as_admin(api)
    assert api.client.patch("/api/admin/settings", json={"nope": 1}).status_code == 400
    assert api.client.patch("/api/admin/settings", json={"pixel_cap": 10}).status_code == 400
