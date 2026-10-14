"""Detect blank (near-uniform) bands of rows or columns where an image can be cut."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from PIL import Image

Axis = Literal["x", "y"]


@dataclass(frozen=True)
class Band:
    start: int  # inclusive
    end: int  # exclusive

    @property
    def center(self) -> int:
        return (self.start + self.end) // 2

    @property
    def width(self) -> int:
        return self.end - self.start


FRAME_MAX_LEVEL = 200  # uniform edge strips darker than this are frames (borders, bezels)


def _frame_extent(lines: np.ndarray, max_std: float) -> tuple[int, int]:
    """Leading/trailing positions along the lines that form a dark outer frame.

    A frame position is uniform across *all* lines and darker than FRAME_MAX_LEVEL (a
    screenshot border, phone bezels). Frames are excluded when judging blankness so a thick
    border cannot make every line look busy. Light margins are kept: they match the page
    background, and keeping them preserves contrast against solid content. Content near the
    edge (a right-aligned badge) is never trimmed because it is not uniform across lines.
    """
    uniform = (lines.std(axis=0) < max_std) & (lines.mean(axis=0) < FRAME_MAX_LEVEL)
    length = uniform.size
    lead = 0
    while lead < length and uniform[lead]:
        lead += 1
    trail = 0
    while trail < length - lead and uniform[length - 1 - trail]:
        trail += 1
    return lead, trail


def find_blank_bands(
    img: Image.Image,
    axis: Axis,
    *,
    min_width: int = 8,
    max_std: float = 3.0,
    min_trim: int = 1,
) -> list[Band]:
    """Return runs of near-uniform lines.

    axis="x" scans columns (vertical bands, i.e. cut positions along x);
    axis="y" scans rows. A detected outer frame (see _frame_extent), plus `min_trim`
    pixels, is ignored at both ends of every line.
    """
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    lines = gray.T if axis == "x" else gray  # one row of `lines` per scanned line
    lead, trail = _frame_extent(lines, max_std)
    lo, hi = max(lead, min_trim), lines.shape[1] - max(trail, min_trim)
    inner = lines[:, lo:hi] if hi - lo >= 2 else lines
    blank = inner.std(axis=1) < max_std
    bands: list[Band] = []
    start: int | None = None
    for i, is_blank in enumerate(blank):
        if is_blank and start is None:
            start = i
        elif not is_blank and start is not None:
            if i - start >= min_width:
                bands.append(Band(start, i))
            start = None
    if start is not None and len(blank) - start >= min_width:
        bands.append(Band(start, len(blank)))
    return bands
