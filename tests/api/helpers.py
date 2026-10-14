import io
import time

from PIL import Image

from imgsr.auth import hash_password
from imgsr.db.models import User


def add_user(api, username="alice", password="password123", role="user", quota=50):
    with api.ctx.sf() as db:
        user = User(username=username, password_hash=hash_password(password), role=role,
                    daily_quota=quota)
        db.add(user)
        db.commit()
        return user.id


def login(client, username="alice", password="password123"):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response


def upload(client, size=(400, 300), path="/api/tasks", ip=None, **form):
    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    headers = {"X-Forwarded-For": ip} if ip else {}
    return client.post(path, files={"file": ("a.png", buf.getvalue(), "image/png")},
                       data=form or None, headers=headers)


def wait_task(client, task_id, done, path="/api/tasks/{id}", timeout=10.0):
    deadline = time.monotonic() + timeout
    while True:
        body = client.get(path.format(id=task_id)).json()
        if done(body):
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"timeout waiting for task, last={body}")
        time.sleep(0.02)
