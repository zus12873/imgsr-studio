"""Filesystem layout for task images. All paths derive from the task id."""

from __future__ import annotations

import io
import re
import shutil
from pathlib import Path
from typing import Literal

from PIL import Image

TASK_ID_RE = re.compile(r"[0-9a-f]{32}")
_NAME_RE = re.compile(r"source|thumb|result-(\d{1,4})|download-(\d{1,4})")


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def task_dir(self, task_id: str) -> Path:
        if not TASK_ID_RE.fullmatch(task_id):
            raise ValueError(f"invalid task id: {task_id!r}")
        return self.root / task_id

    def source(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "source.png"

    def thumb(self, task_id: str) -> Path:
        return self.task_dir(task_id) / "thumb.webp"

    def round_dir(self, task_id: str, seq: int) -> Path:
        return self.task_dir(task_id) / "rounds" / str(seq)

    def result(self, task_id: str, seq: int) -> Path:
        return self.round_dir(task_id, seq) / "result.png"

    def download(self, task_id: str, seq: int) -> Path:
        return self.round_dir(task_id, seq) / "download.png"

    def tile(self, task_id: str, seq: int, index: int, kind: Literal["in", "out"]) -> Path:
        return self.round_dir(task_id, seq) / "tiles" / f"{index:02d}-{kind}.png"

    def named(self, task_id: str, name: str) -> Path | None:
        match = _NAME_RE.fullmatch(name)
        if match is None or not TASK_ID_RE.fullmatch(task_id):
            return None
        if name == "source":
            path = self.source(task_id)
        elif name == "thumb":
            path = self.thumb(task_id)
        elif match.group(1):
            path = self.result(task_id, int(match.group(1)))
        else:
            path = self.download(task_id, int(match.group(2)))
        return path if path.is_file() else None

    def save_source(self, task_id: str, img: Image.Image) -> None:
        save_png(img, self.source(task_id))
        thumb = img.copy()
        thumb.thumbnail((480, 480))
        thumb.save(self.thumb(task_id), "WEBP", quality=80)

    def delete_task(self, task_id: str) -> None:
        shutil.rmtree(self.task_dir(task_id), ignore_errors=True)

    def free_bytes(self) -> int:
        self.root.mkdir(parents=True, exist_ok=True)
        return shutil.disk_usage(self.root).free
