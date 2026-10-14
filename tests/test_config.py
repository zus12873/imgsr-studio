from pathlib import Path

import pytest

from imgsr.config import OVERRIDABLE, Settings


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("OPEN_API_KEY", "IMAGE_MODEL", "DATA_DIR", "PIXEL_CAP"):
        monkeypatch.delenv(key, raising=False)


def test_defaults_match_spec():
    s = Settings(_env_file=None)
    assert s.image_model == "gpt-image-2.5"
    assert s.transcribe_model == s.review_model == "gpt-6-sol"
    assert s.pixel_cap == 1_550_000
    assert (s.guest_daily_per_ip, s.guest_daily_global, s.user_daily_default) == (3, 100, 50)
    assert (s.retention_user_days, s.retention_guest_hours) == (30, 24)
    assert s.db_path == Path("/data/db/imgsr.sqlite3")


def test_env_vars_override(monkeypatch):
    monkeypatch.setenv("IMAGE_MODEL", "gpt-image-2")
    monkeypatch.setenv("DATA_DIR", "/tmp/imgsr-x")
    s = Settings(_env_file=None)
    assert s.image_model == "gpt-image-2"
    assert s.files_dir == Path("/tmp/imgsr-x/files")


def test_with_overrides_casts_and_ignores_unknown_and_secrets():
    s = Settings(_env_file=None).with_overrides(
        {"pixel_cap": "1000000", "open_api_key": "leak", "nope": 1}
    )
    assert s.pixel_cap == 1_000_000
    assert s.open_api_key == ""
    assert "open_api_key" not in OVERRIDABLE
