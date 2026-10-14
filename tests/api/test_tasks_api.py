import threading

from imgsr.relay.errors import RelayError
from tests.api.helpers import add_user, login, upload, wait_task


def ready_task(api, text="原文。", **user):
    add_user(api, **user)
    login(api.client, user.get("username", "alice"))
    tid = upload(api.client).json()["id"]
    wait_task(api.client, tid, lambda b: b["status"] == "awaiting_confirm")
    assert api.client.put(f"/api/tasks/{tid}/text", json={"confirmed_text": text}).status_code == 200
    return tid


def test_upload_transcribes_and_waits_for_confirmation(api):
    api.chat.reply = lambda i, size: "第一段。\n第二段。"
    add_user(api)
    login(api.client)
    r = upload(api.client)
    assert r.status_code == 201
    body = wait_task(api.client, r.json()["id"], lambda b: b["status"] == "awaiting_confirm")
    assert body["transcript_raw"] == "第一段。\n第二段。" and body["busy"] is False


def test_upload_requires_login_and_valid_image(api):
    assert upload(api.client).status_code == 401
    add_user(api)
    login(api.client)
    r = api.client.post("/api/tasks", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 400 and "无法识别" in r.json()["detail"]


def test_full_round_then_final_and_download(api):
    tid = ready_task(api, "原文。")
    api.chat.reply = lambda i, size: "原文。"
    assert api.client.post(f"/api/tasks/{tid}/rounds", json={}).status_code == 201
    body = wait_task(api.client, tid, lambda b: b["status"] == "reviewed")
    rnd = body["rounds"][0]
    assert rnd["status"] == "succeeded" and rnd["use_text_hint"] is True
    assert rnd["review"]["diffs"] == []
    assert rnd["review"]["suggestions"][0]["action"] == "accept"
    assert "「原文。」" in api.images.calls[-1]["prompt"]
    r = api.client.post(f"/api/tasks/{tid}/final", json={"round_id": rnd["id"]})
    assert r.json()["status"] == "done" and r.json()["final_round_id"] == rnd["id"]
    f = api.client.get(f"/api/files/{tid}/download-1?download=1")
    assert f.status_code == 200 and "attachment" in f.headers["content-disposition"]
    assert api.client.get(f"/api/files/{tid}/thumb").status_code == 200


def test_suggestion_executes_next_round(api):
    tid = ready_task(api, "晚上还会发出亮光呢！")
    api.chat.reply = lambda i, size: "晚上还会发出光光呢！"
    api.client.post(f"/api/tasks/{tid}/rounds", json={"use_text_hint": False})
    body = wait_task(api.client, tid, lambda b: b["status"] == "reviewed")
    first = body["rounds"][0]
    assert first["review"]["diffs"][0]["expected"] == "亮"
    assert first["review"]["suggestions"][0]["action"] == "retry_with_hint"
    r = api.client.post(f"/api/tasks/{tid}/rounds",
                        json={"suggestion": {"round_id": first["id"], "index": 0}})
    assert r.status_code == 201
    body = wait_task(api.client, tid, lambda b: b["status"] == "reviewed" and len(b["rounds"]) == 2)
    assert body["rounds"][1]["use_text_hint"] is True


def test_bad_suggestion_reference(api):
    tid = ready_task(api)
    r = api.client.post(f"/api/tasks/{tid}/rounds", json={"suggestion": {"round_id": 999, "index": 0}})
    assert r.status_code == 400


def test_one_generation_at_a_time(api):
    tid = ready_task(api)
    api.images.gate = threading.Event()
    assert api.client.post(f"/api/tasks/{tid}/rounds", json={}).status_code == 201
    assert api.client.post(f"/api/tasks/{tid}/rounds", json={}).status_code == 409
    api.images.gate.set()
    wait_task(api.client, tid, lambda b: b["status"] == "reviewed")


def test_daily_quota(api):
    tid = ready_task(api, quota=1)
    assert api.client.post(f"/api/tasks/{tid}/rounds", json={}).status_code == 201
    wait_task(api.client, tid, lambda b: b["status"] == "reviewed")
    r = api.client.post(f"/api/tasks/{tid}/rounds", json={})
    assert r.status_code == 429 and "今日生成次数已用完" in r.json()["detail"]


def test_failed_round_refunds_and_can_be_retried(api):
    tid = ready_task(api)
    api.images.fail = RelayError("上游拒绝请求：bad", kind="rejected", retryable=False)
    api.client.post(f"/api/tasks/{tid}/rounds", json={})
    body = wait_task(api.client, tid, lambda b: b["status"] == "round_failed")
    assert "bad" in body["rounds"][0]["error"]
    assert api.client.get("/api/me").json()["used_today"] == 0
    api.images.fail = None
    assert api.client.post(f"/api/tasks/{tid}/rounds/1/retry").status_code == 200
    wait_task(api.client, tid, lambda b: b["status"] == "reviewed")
    assert api.client.post(f"/api/tasks/{tid}/rounds/1/retry").status_code == 409


def test_other_users_cannot_see_task_or_files(api):
    tid = ready_task(api)
    add_user(api, "bob")
    api.client.cookies.clear()
    login(api.client, "bob")
    assert api.client.get(f"/api/tasks/{tid}").status_code == 404
    assert api.client.get(f"/api/files/{tid}/source").status_code == 404
    assert api.client.get("/api/tasks").json()["items"] == []


def test_delete_removes_rows_and_files(api):
    tid = ready_task(api)
    assert api.client.delete(f"/api/tasks/{tid}").status_code == 204
    assert api.client.get(f"/api/tasks/{tid}").status_code == 404
    assert not api.ctx.storage.task_dir(tid).exists()


def test_low_disk_rejects_upload(api, monkeypatch):
    add_user(api)
    login(api.client)
    monkeypatch.setattr(api.ctx.storage, "free_bytes", lambda: 10)
    assert upload(api.client).status_code == 507


def test_list_paginates(api):
    add_user(api)
    login(api.client)
    for _ in range(3):
        upload(api.client)
    page = api.client.get("/api/tasks", params={"limit": 2}).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    rest = api.client.get("/api/tasks", params={"limit": 2, "cursor": page["next_cursor"]}).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None


def test_retry_transcription(api):
    api.chat.fail = RelayError("上游超时", kind="timeout", retryable=True)
    add_user(api)
    login(api.client)
    tid = upload(api.client).json()["id"]
    wait_task(api.client, tid, lambda b: b["status"] == "transcribe_failed")
    api.chat.fail = None
    assert api.client.post(f"/api/tasks/{tid}/transcribe").status_code == 200
    wait_task(api.client, tid, lambda b: b["status"] == "awaiting_confirm")
