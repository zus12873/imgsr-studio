import threading

from imgsr.relay.errors import RelayError
from tests.api.helpers import add_user, login, upload, wait_task

GUEST = "/api/guest/tasks"


def guest_upload(api, ip, **form):
    return upload(api.client, path=GUEST, ip=ip, **form)


def wait_guest(api, tid):
    return wait_task(api.client, tid, lambda b: b["status"] in ("done", "round_failed"),
                     path=GUEST + "/{id}")


def remaining(api, ip):
    return api.client.get("/api/guest/quota", headers={"X-Forwarded-For": ip}).json()["remaining"]


def test_guest_flow(api):
    r = guest_upload(api, "1.1.1.1", prompt="请保持原样")
    assert r.status_code == 201 and "imgsr_guest" in api.client.cookies
    body = wait_guest(api, r.json()["id"])
    assert body["status"] == "done" and body["round"]["use_text_hint"] is False
    assert body["round"]["prompt"] == "请保持原样"
    assert api.client.get(f"/api/files/{body['id']}/download-1").status_code == 200
    assert api.chat.calls == []


def test_guest_ip_limit(api):
    for _ in range(3):
        wait_guest(api, guest_upload(api, "1.1.1.1").json()["id"])
    r = guest_upload(api, "1.1.1.1")
    assert r.status_code == 429 and "今日免费次数已用完" in r.json()["detail"]
    assert remaining(api, "1.1.1.1") == 0
    assert guest_upload(api, "2.2.2.2").status_code == 201


def test_guest_global_cap(make_api):
    api = make_api(guest_daily_global=2)
    for ip in ("1.1.1.1", "2.2.2.2"):
        wait_guest(api, guest_upload(api, ip).json()["id"])
    r = guest_upload(api, "3.3.3.3")
    assert r.status_code == 429 and "今日游客总额度已用完" in r.json()["detail"]


def test_guest_failure_refunds(api):
    api.images.fail = RelayError("上游拒绝请求：bad", kind="rejected", retryable=False)
    body = wait_guest(api, guest_upload(api, "1.1.1.1").json()["id"])
    assert body["status"] == "round_failed"
    assert remaining(api, "1.1.1.1") == 3


def test_guest_task_needs_its_cookie(api):
    tid = guest_upload(api, "1.1.1.1").json()["id"]
    wait_guest(api, tid)
    api.client.cookies.clear()
    assert api.client.get(f"{GUEST}/{tid}").status_code == 404
    assert api.client.get(f"/api/files/{tid}/source").status_code == 404


def test_guest_one_at_a_time_per_ip(api):
    api.images.gate = threading.Event()
    tid = guest_upload(api, "1.1.1.1").json()["id"]
    assert guest_upload(api, "1.1.1.1").status_code == 409
    api.images.gate.set()
    wait_guest(api, tid)


def test_guest_tasks_are_not_in_user_history(api):
    wait_guest(api, guest_upload(api, "1.1.1.1").json()["id"])
    add_user(api)
    login(api.client)
    assert api.client.get("/api/tasks").json()["items"] == []
