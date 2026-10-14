from datetime import datetime, timedelta

from PIL import Image

from imgsr.db.models import Job, Task, utcnow
from imgsr.maintenance import backup_db, cleanup_expired
from imgsr.storage import Storage


def test_cleanup_removes_expired_tasks_but_keeps_busy_and_fresh(sf, tmp_path, make_task):
    storage = Storage(tmp_path / "files")
    past = utcnow() - timedelta(hours=1)
    expired = make_task(expires_at=past)
    busy = make_task(expires_at=past)
    fresh = make_task()
    storage.save_source(expired, Image.new("RGB", (5, 5)))
    with sf() as db:
        db.add(Job(kind="generate", task_id=busy, status="queued"))
        db.commit()
    assert cleanup_expired(sf, storage) == 1
    with sf() as db:
        assert db.get(Task, expired) is None
        assert db.get(Task, busy) is not None and db.get(Task, fresh) is not None
    assert not storage.task_dir(expired).exists()


def test_backup_keeps_latest_n(engine, tmp_path):
    target_dir = tmp_path / "backup"
    for day in range(1, 10):
        backup_db(engine, target_dir, keep=7, now=datetime(2026, 10, day))
    files = sorted(p.name for p in target_dir.iterdir())
    assert len(files) == 7
    assert files[-1] == "imgsr-20261009.sqlite3" and files[0] == "imgsr-20261003.sqlite3"
