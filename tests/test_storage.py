import pytest
from PIL import Image

from imgsr.storage import Storage, png_bytes, save_png

TID = "a" * 32


def test_paths_and_named_lookup(tmp_path):
    s = Storage(tmp_path)
    s.save_source(TID, Image.new("RGB", (50, 40)))
    assert s.named(TID, "source") == s.source(TID)
    assert s.named(TID, "thumb").suffix == ".webp"
    assert s.named(TID, "result-1") is None
    save_png(Image.new("RGB", (5, 5)), s.result(TID, 1))
    assert s.named(TID, "result-1") == s.result(TID, 1)
    assert s.tile(TID, 2, 3, "out").name == "03-out.png"


@pytest.mark.parametrize(
    "task_id,name",
    [(TID, "../etc"), ("../../x", "source"), ("A" * 32, "source"), (TID, "source.png")],
)
def test_named_rejects_bad_input(tmp_path, task_id, name):
    assert Storage(tmp_path).named(task_id, name) is None


def test_task_dir_rejects_bad_id(tmp_path):
    with pytest.raises(ValueError):
        Storage(tmp_path).task_dir("../x")


def test_delete_task_and_free_bytes(tmp_path):
    s = Storage(tmp_path)
    s.save_source(TID, Image.new("RGB", (5, 5)))
    s.delete_task(TID)
    assert not s.task_dir(TID).exists()
    assert s.free_bytes() > 0


def test_png_bytes():
    assert png_bytes(Image.new("RGB", (2, 2))).startswith(b"\x89PNG")
