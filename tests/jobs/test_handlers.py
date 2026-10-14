import asyncio
import threading
import uuid
from datetime import timedelta

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

import imgsr.jobs.handlers as handlers_mod
from imgsr import quota
from imgsr.config import Settings
from imgsr.db.models import Job, Round, Task, UsageDaily, utcnow
from imgsr.jobs.handlers import Pipeline, Services
from imgsr.pipeline.prompt import BASE_PROMPT
from imgsr.pipeline.tiling import Box, Tile, TilePlan
from imgsr.relay.errors import RelayError
from imgsr.storage import Storage, save_png
from tests.fakes import FakeChat, FakeImages


@pytest.fixture
def services(sf, tmp_path):
    def _make(images=None, chat=None):
        settings = Settings(_env_file=None, data_dir=tmp_path)
        enqueued = []
        svc = Services(
            session_factory=sf,
            storage=Storage(tmp_path / "files"),
            images=images or FakeImages(),
            chat=chat or FakeChat(),
            settings=lambda: settings,
            gate=asyncio.Semaphore(3),
            enqueue=enqueued.append,
            retry_delays=(0.0, 0.0),
        )
        return svc, enqueued

    return _make


def seed(sf, storage, image, *, owner, confirmed=None, use_hint=True, mode="auto", pre=1,
         charge=None, kind="generate", round_status="queued", strategy_extra=None, seq=1,
         task_id=None, review=None):
    tid = task_id or uuid.uuid4().hex
    if task_id is None:
        save_png(image, storage.source(tid))
    with sf() as db:
        if db.get(Task, tid) is None:
            db.add(Task(id=tid, owner_user_id=owner, client_ip="1.2.3.4", source_w=image.width,
                        source_h=image.height, status="ready", confirmed_text=confirmed,
                        expires_at=utcnow() + timedelta(days=1)))
            db.flush()
        round_id = None
        if kind != "transcribe":
            rnd = Round(task_id=tid, seq=seq, image_model="gpt-image-2.5", prompt=BASE_PROMPT,
                        strategy={"mode": mode, "preupscale": pre, **(strategy_extra or {})},
                        use_text_hint=use_hint, status=round_status, charge=charge, review=review)
            db.add(rnd)
            db.flush()
            round_id = rnd.id
        job = Job(kind=kind, task_id=tid, round_id=round_id)
        db.add(job)
        db.commit()
        return tid, round_id, job.id


def two_column_page():
    img = Image.new("RGB", (2316, 1294), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((20, 40, 918, 1254), fill="black")
    d.rectangle((999, 40, 2296, 1254), fill="black")
    return img


async def test_transcribe_sets_awaiting_confirm(sf, services, make_user):
    uid = make_user()
    svc, _ = services(chat=FakeChat(lambda i, s: "第一行。\n第二行。"))
    tid, _, job = seed(sf, svc.storage, Image.new("RGB", (300, 200), "white"), owner=uid,
                       kind="transcribe")
    await Pipeline(svc).transcribe(job)
    with sf() as db:
        task = db.get(Task, tid)
        assert task.status == "awaiting_confirm"
        assert task.transcript_raw == "第一行。\n第二行。"
        assert task.transcript_model == "gpt-6-sol"
        assert db.get(UsageDaily, (f"user:{uid}", quota.today())).llm_calls == 1


async def test_transcribe_failure_marks_task(sf, services, make_user):
    uid = make_user()
    fail = RelayError("上游拒绝请求：bad", kind="rejected", retryable=False)
    svc, _ = services(chat=FakeChat(fail=fail))
    tid, _, job = seed(sf, svc.storage, Image.new("RGB", (300, 200)), owner=uid, kind="transcribe")
    with pytest.raises(RelayError):
        await Pipeline(svc).transcribe(job)
    with sf() as db:
        task = db.get(Task, tid)
        assert task.status == "transcribe_failed" and "bad" in task.error


async def test_generate_whole_with_hint(sf, services, make_user):
    uid = make_user()
    svc, enqueued = services(images=FakeImages(scale=2.0))
    tid, rid, job = seed(sf, svc.storage, Image.new("RGB", (400, 300), "white"), owner=uid,
                         confirmed="第一段。\n第二段。")
    await Pipeline(svc).generate(job)
    with sf() as db:
        rnd, task = db.get(Round, rid), db.get(Task, tid)
        assert rnd.status == "succeeded"
        assert (rnd.result_w, rnd.result_h, rnd.download_w, rnd.download_h) == (800, 600, 800, 600)
        assert rnd.strategy["plan"]["mode"] == "whole" and rnd.strategy["scale"] == 2.0
        assert task.status == "reviewing"
        review_jobs = db.scalars(select(Job).where(Job.kind == "review")).all()
    assert [j.id for j in review_jobs] == enqueued
    assert "「第一段。」 / 「第二段。」" in svc.images.calls[0]["prompt"]
    assert svc.storage.result(tid, 1).is_file() and svc.storage.download(tid, 1).is_file()


async def test_generate_tiles_slices_hint_per_tile(sf, services, make_user):
    uid = make_user()
    chat = FakeChat(lambda i, size: "左栏文字。" if size[0] < 1200 else "右栏文字。")
    svc, _ = services(chat=chat)
    tid, rid, job = seed(sf, svc.storage, two_column_page(), owner=uid,
                         confirmed="左栏文字。\n右栏文字。")
    await Pipeline(svc).generate(job)
    prompts = sorted(c["prompt"] for c in svc.images.calls)
    assert len(prompts) == 2
    assert any("「左栏文字。」" in p and "右栏" not in p for p in prompts)
    assert any("「右栏文字。」" in p and "左栏" not in p for p in prompts)
    with sf() as db:
        rnd, task = db.get(Round, rid), db.get(Task, tid)
        assert (rnd.result_w, rnd.result_h) == (2316, 1294)
        assert rnd.strategy["plan"]["mode"] == "tiles"
        assert len(task.tile_transcripts) == 2


async def test_generate_failure_refunds_and_marks_failed(sf, services, make_user):
    uid = make_user()
    with sf() as db:
        charge = quota.consume(db, [(f"user:{uid}", 50, "x")], quota.today())
    busy = RelayError("上游繁忙：x", kind="busy", retryable=True)
    svc, _ = services(images=FakeImages(fail=busy))
    tid, rid, job = seed(sf, svc.storage, Image.new("RGB", (300, 200)), owner=uid, charge=charge)
    with pytest.raises(RelayError):
        await Pipeline(svc).generate(job)
    assert len(svc.images.calls) == 3  # first try + 2 retries
    with sf() as db:
        rnd = db.get(Round, rid)
        assert rnd.status == "failed" and "上游繁忙" in rnd.error and rnd.charge is None
        assert db.get(Task, tid).status == "round_failed"
        assert quota.used(db, f"user:{uid}", quota.today()) == 0


async def test_guest_generate_finishes_without_review(sf, services):
    svc, enqueued = services()
    tid, rid, job = seed(sf, svc.storage, Image.new("RGB", (300, 200)), owner=None, use_hint=False)
    await Pipeline(svc).generate(job)
    with sf() as db:
        task = db.get(Task, tid)
        assert task.status == "done" and task.final_round_id == rid
    assert enqueued == []


def reviewable(svc, sf, owner, *, confirmed, use_hint=False, pre=1, seq=1, task_id=None,
               review=None, round_status="succeeded"):
    img = Image.new("RGB", (300, 200), "white")
    plan = TilePlan("whole", [Tile(Box(0, 0, 300, 200), Box(0, 0, 300, 200))])
    out = seed(sf, svc.storage, img, owner=owner, confirmed=confirmed, use_hint=use_hint, pre=pre,
               kind="review", round_status=round_status, seq=seq, task_id=task_id, review=review,
               strategy_extra={"plan": plan.to_json(), "scale": 1.0})
    save_png(img, svc.storage.result(out[0], seq))
    return out


async def test_review_reports_diffs_and_suggestion(sf, services, make_user):
    uid = make_user()
    svc, _ = services(chat=FakeChat(lambda i, s: "晚上还会发出光光呢！"))
    tid, rid, job = reviewable(svc, sf, uid, confirmed="晚上还会发出亮光呢！")
    await Pipeline(svc).review(job)
    with sf() as db:
        review = db.get(Round, rid).review
        assert review["diffs"] == [{"expected": "亮", "found": "光", "sentence": "晚上还会发出亮光呢！"}]
        assert review["suggestions"][0]["action"] == "retry_with_hint"
        assert review["model"] == "gpt-6-sol"
        assert db.get(Task, tid).status == "reviewed"


async def test_review_without_text_suggests_manual_check(sf, services, make_user):
    uid = make_user()
    svc, _ = services()
    tid, rid, job = reviewable(svc, sf, uid, confirmed=None)
    await Pipeline(svc).review(job)
    with sf() as db:
        assert db.get(Round, rid).review["suggestions"][0]["action"] == "manual_check"
    assert svc.chat.calls == []


async def test_review_uses_previous_round_diffs(sf, services, make_user):
    uid = make_user()
    svc, _ = services(chat=FakeChat(lambda i, s: "晚上还会发出光光呢！"))
    prev_review = {"diffs": [{"expected": "亮", "found": "光", "sentence": "x"}], "suggestions": []}
    tid, _, _ = reviewable(svc, sf, uid, confirmed="晚上还会发出亮光呢！", review=prev_review)
    _, rid, job = reviewable(svc, sf, uid, confirmed="晚上还会发出亮光呢！", use_hint=True, pre=2,
                             seq=2, task_id=tid)
    await Pipeline(svc).review(job)
    with sf() as db:
        sugs = db.get(Round, rid).review["suggestions"]
    assert [s["action"] for s in sugs] == ["manual_check"] and sugs[0]["diff_ids"] == [0]


async def test_generate_for_deleted_task_leaves_no_files(sf, services, make_user):
    uid = make_user()
    images = FakeImages()
    images.gate = threading.Event()
    svc, _ = services(images=images)
    tid, _, job = seed(sf, svc.storage, Image.new("RGB", (300, 200)), owner=uid)
    run = asyncio.create_task(Pipeline(svc).generate(job))
    for _ in range(500):
        if images.calls:
            break
        await asyncio.sleep(0.01)
    assert images.calls, "generate never reached the image call"
    with sf() as db:
        db.delete(db.get(Task, tid))
        db.commit()
    svc.storage.delete_task(tid)
    images.gate.set()
    await run  # must not raise
    assert not svc.storage.task_dir(tid).exists()


async def test_on_interrupted_marks_states_and_refunds(sf, services, make_user):
    uid = make_user()
    with sf() as db:
        charge = quota.consume(db, [(f"user:{uid}", 50, "x")], quota.today())
    svc, _ = services()
    tid, rid, job_id = seed(sf, svc.storage, Image.new("RGB", (30, 20)), owner=uid, charge=charge)
    with sf() as db:
        Pipeline(svc).on_interrupted(db, db.get(Job, job_id))
        db.commit()
        rnd = db.get(Round, rid)
        assert (rnd.status, rnd.error) == ("failed", "服务重启")
        assert db.get(Task, tid).status == "round_failed"
        assert quota.used(db, f"user:{uid}", quota.today()) == 0


async def test_save_failure_after_render_fails_round_and_refunds(sf, services, make_user, monkeypatch):
    uid = make_user()
    with sf() as db:
        charge = quota.consume(db, [(f"user:{uid}", 50, "x")], quota.today())
    svc, _ = services()
    tid, rid, job = seed(sf, svc.storage, Image.new("RGB", (300, 200)), owner=uid, charge=charge)
    real_save = handlers_mod.save_png

    def failing_save(img, path):
        if path.name == "result.png":
            raise OSError(28, "No space left on device")
        real_save(img, path)

    monkeypatch.setattr(handlers_mod, "save_png", failing_save)
    with pytest.raises(OSError):
        await Pipeline(svc).generate(job)
    with sf() as db:
        rnd = db.get(Round, rid)
        assert rnd.status == "failed" and "No space" in rnd.error
        assert db.get(Task, tid).status == "round_failed"
        assert quota.used(db, f"user:{uid}", quota.today()) == 0


async def test_plan_over_tile_cap_fails_before_upstream_calls(sf, services, make_user, monkeypatch):
    uid = make_user()
    with sf() as db:
        charge = quota.consume(db, [(f"user:{uid}", 50, "x")], quota.today())
    monkeypatch.setattr(handlers_mod, "MAX_TILES", 1)
    svc, _ = services()
    tid, rid, job = seed(sf, svc.storage, two_column_page(), owner=uid, confirmed="左栏。", charge=charge)
    with pytest.raises(Exception, match="上限"):
        await Pipeline(svc).generate(job)
    assert svc.images.calls == [] and svc.chat.calls == []
    with sf() as db:
        rnd = db.get(Round, rid)
        assert rnd.status == "failed" and "上限" in rnd.error and "PlanTooLarge" not in rnd.error
        assert quota.used(db, f"user:{uid}", quota.today()) == 0


async def test_review_skips_tile_refine_when_over_cap(sf, services, make_user, monkeypatch):
    uid = make_user()
    monkeypatch.setattr(handlers_mod, "MAX_TILES", 0)
    svc, _ = services(chat=FakeChat(lambda i, s: "晚上还会发出光光呢！"))
    tid, rid, job = reviewable(svc, sf, uid, confirmed="晚上还会发出亮光呢！", use_hint=True)
    await Pipeline(svc).review(job)
    with sf() as db:
        sugs = db.get(Round, rid).review["suggestions"]
    assert [s["action"] for s in sugs] == ["manual_check"]


async def test_review_skips_tile_refine_when_refine_plan_degenerates(sf, services, make_user):
    uid = make_user()  # the blank 300x200 test image has no seams, so a refine plan is just "whole"
    svc, _ = services(chat=FakeChat(lambda i, s: "晚上还会发出光光呢！"))
    tid, rid, job = reviewable(svc, sf, uid, confirmed="晚上还会发出亮光呢！", use_hint=True)
    await Pipeline(svc).review(job)
    with sf() as db:
        sugs = db.get(Round, rid).review["suggestions"]
    assert [s["action"] for s in sugs] == ["manual_check"]
