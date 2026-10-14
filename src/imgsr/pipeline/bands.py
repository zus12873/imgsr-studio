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


def find_blank_bands(
    img: Image.Image,
    axis: Axis,
    *,
    min_width: int = 8,
    max_std: float = 3.0,
    edge_trim_ratio: float = 0.03,
) -> list[Band]:
    """Return runs of near-uniform lines.

    axis="x" scans columns (vertical bands, i.e. cut positions along x);
    axis="y" scans rows. Both ends of every line are trimmed by `edge_trim_ratio`
    so that a screenshot's dark outer frame does not make every line look busy.
    """
    gray = np.asarray(img.convert("L"), dtype=np.float32)
    lines = gray.T if axis == "x" else gray  # one row of `lines` per scanned line
    trim = max(1, int(lines.shape[1] * edge_trim_ratio))
    inner = lines[:, trim : lines.shape[1] - trim] if lines.shape[1] > 2 * trim else lines
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
