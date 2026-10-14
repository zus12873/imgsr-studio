import asyncio

from imgsr.db.models import Job
from imgsr.jobs.runner import JobRunner


def add_job(sf, task_id, kind="transcribe", status="queued"):
    with sf() as db:
        job = Job(kind=kind, task_id=task_id, status=status)
        db.add(job)
        db.commit()
        return job.id


def status_of(sf, job_id):
    with sf() as db:
        job = db.get(Job, job_id)
        return (job.status, job.error)


async def test_runs_queued_job_and_marks_succeeded(sf, make_task):
    seen = []

    async def handler(job_id):
        seen.append(job_id)

    runner = JobRunner(sf, {"transcribe": handler}, workers=2)
    await runner.start()
    job_id = add_job(sf, make_task())
    runner.enqueue(job_id)
    await asyncio.sleep(0.01)
    await runner.join()
    await runner.stop()
    assert seen == [job_id]
    assert status_of(sf, job_id) == ("succeeded", None)


async def test_failure_is_recorded(sf, make_task):
    async def handler(job_id):
        raise ValueError("boom")

    runner = JobRunner(sf, {"transcribe": handler})
    await runner.start()
    job_id = add_job(sf, make_task())
    runner.enqueue(job_id)
    await asyncio.sleep(0.01)
    await runner.join()
    await runner.stop()
    assert status_of(sf, job_id) == ("failed", "boom")


async def test_recover_marks_running_failed_and_requeues_queued(sf, make_task):
    tid = make_task()
    running = add_job(sf, tid, status="running")
    queued = add_job(sf, tid)
    seen, interrupted = [], []

    async def handler(job_id):
        seen.append(job_id)

    runner = JobRunner(
        sf, {"transcribe": handler}, workers=1,
        on_interrupted=lambda db, job: interrupted.append(job.id),
    )
    await runner.start()
    await runner.join()
    await runner.stop()
    assert status_of(sf, running) == ("failed", "服务重启")
    assert interrupted == [running]
    assert seen == [queued]


async def test_enqueue_is_thread_safe(sf, make_task):
    seen = []

    async def handler(job_id):
        seen.append(job_id)

    runner = JobRunner(sf, {"transcribe": handler})
    await runner.start()
    job_id = add_job(sf, make_task())
    await asyncio.to_thread(runner.enqueue, job_id)
    await asyncio.sleep(0.01)
    await runner.join()
    await runner.stop()
    assert seen == [job_id]


async def test_missing_job_and_unknown_kind_do_not_crash(sf, make_task):
    runner = JobRunner(sf, {})
    await runner.start()
    job_id = add_job(sf, make_task(), kind="mystery")
    runner.enqueue(999_999)
    runner.enqueue(job_id)
    await asyncio.sleep(0.01)
    await runner.join()
    await runner.stop()
    assert status_of(sf, job_id)[0] == "failed"
