"""Plan how to cut an image into tiles that each fit the relay's output pixel cap."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from PIL import Image

from imgsr.pipeline.bands import Axis, Band, find_blank_bands

Mode = Literal["auto", "whole", "tiles"]
FILL = 0.95  # keep every tile a little under the cap
PAD_RATIO = 3.0  # the relay clamps aspect ratio to 3:1, so wider tiles are padded before sending
MAX_TILES = 16  # per round: bounds upstream calls (~3 per tile) and the stitched image size


class PlanTooLarge(ValueError):
    """A plan needs more tiles than one round may use. The message is user-facing."""


def padded_area(w: int, h: int) -> int:
    """Pixels the relay actually sees for a w×h tile after padding it to PAD_RATIO."""
    long, short = max(w, h), min(w, h)
    return long * max(short, math.ceil(long / PAD_RATIO))
NO_BAND_NOTE = "未找到可切分的空白带，整图处理（输出可能小于原图）"


@dataclass(frozen=True)
class Box:
    x0: int
    y0: int
    x1: int
    y1: int

    @property
    def width(self) -> int:
        return self.x1 - self.x0

    @property
    def height(self) -> int:
        return self.y1 - self.y0

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def padded_area(self) -> int:
        return padded_area(self.width, self.height)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x0, self.y0, self.x1, self.y1)

    def intersect(self, other: Box) -> Box:
        return Box(
            max(self.x0, other.x0),
            max(self.y0, other.y0),
            min(self.x1, other.x1),
            min(self.y1, other.y1),
        )


@dataclass(frozen=True)
class Tile:
    box: Box  # region sent to the model (source coords, includes overlap)
    keep: Box  # part of this tile used in the final composite (source coords)


@dataclass(frozen=True)
class TilePlan:
    mode: Literal["whole", "tiles"]
    tiles: list[Tile]
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "mode": self.mode,
            "tiles": [
                {"box": list(t.box.as_tuple()), "keep": list(t.keep.as_tuple())} for t in self.tiles
            ],
            "notes": list(self.notes),
        }

    @classmethod
    def from_json(cls, data: dict) -> TilePlan:
        tiles = [Tile(Box(*t["box"]), Box(*t["keep"])) for t in data["tiles"]]
        return cls(data["mode"], tiles, list(data.get("notes", [])))


def plan_tiles(img: Image.Image, cap: int, mode: Mode = "auto", preupscale: int = 1) -> TilePlan:
    w, h = img.size
    full = Box(0, 0, w, h)
    eff = cap // (preupscale * preupscale)
    if mode == "whole" or (mode == "auto" and full.padded_area <= eff):
        return TilePlan("whole", [Tile(full, full)])
    axis: Axis = "x" if w >= h else "y"
    tiles, notes = _plan_region(img, full, eff, axis, depth=0, min_pieces=2 if mode == "tiles" else 1)
    if len(tiles) == 1:
        return TilePlan("whole", [Tile(full, full)], [NO_BAND_NOTE])
    return TilePlan("tiles", tiles, notes)


def _other(axis: Axis) -> Axis:
    return "y" if axis == "x" else "x"


def _span(region: Box, axis: Axis, a: int, b: int) -> Box:
    """Sub-box of `region` covering offsets [a, b) along `axis`."""
    if axis == "x":
        return Box(region.x0 + a, region.y0, region.x0 + b, region.y1)
    return Box(region.x0, region.y0 + a, region.x1, region.y0 + b)


def _seams_fit(length: int, seams: list[Band], fits: Callable[[int, int], bool]) -> bool:
    starts = [0, *[b.start for b in seams]]
    ends = [*[b.end for b in seams], length]
    return all(fits(a, b) for a, b in zip(starts, ends, strict=True))


def _balanced_seams(length: int, bands: list[Band], pieces: int) -> list[Band]:
    seams: list[Band] = []
    for k in range(1, pieces):
        ideal = length * k / pieces
        candidates = [b for b in bands if not seams or b.start >= seams[-1].end]
        if not candidates:
            break
        seams.append(min(candidates, key=lambda b: abs(b.center - ideal)))
    return seams


def _greedy_seams(length: int, bands: list[Band], fits: Callable[[int, int], bool]) -> list[Band]:
    """Fill each piece as far as it fits; the next piece starts at the seam band's start."""
    seams: list[Band] = []
    start = 0
    while not fits(start, length):
        candidates = [b for b in bands if b.start > start and (not seams or b.start >= seams[-1].end)]
        if not candidates:
            break
        fitting = [b for b in candidates if fits(start, b.end)]
        band = max(fitting, key=lambda b: b.end) if fitting else min(candidates, key=lambda b: b.start)
        seams.append(band)
        start = band.start
    return seams


def _choose_seams(
    length: int, bands: list[Band], pieces: int, fits: Callable[[int, int], bool]
) -> list[Band]:
    balanced = _balanced_seams(length, bands, pieces)
    if balanced and _seams_fit(length, balanced, fits):
        return balanced
    return _greedy_seams(length, bands, fits) or balanced


def _plan_region(
    img: Image.Image, region: Box, eff: int, axis: Axis, depth: int, min_pieces: int = 1
) -> tuple[list[Tile], list[str]]:
    limit = FILL * eff
    if region.padded_area <= limit and min_pieces <= 1:
        return [Tile(region, region)], []
    # Count pieces by real area: padding an extreme strip (e.g. 1080x12000) as a whole would
    # wildly overstate how many tiles it needs. `fits` below still judges padded area.
    pieces = max(min_pieces, 2, math.ceil(region.area / limit))
    length = region.width if axis == "x" else region.height
    across = region.height if axis == "x" else region.width
    if depth == 0 and padded_area(across, 1) > limit:
        return _plan_slabs(img, region, eff, axis)

    def fits(a: int, b: int) -> bool:
        return padded_area(b - a, across) <= limit

    sub = img.crop(region.as_tuple())
    bands = [b for b in find_blank_bands(sub, axis) if b.start > 0 and b.end < length]
    seams = _choose_seams(length, bands, pieces, fits)
    if not seams:
        if depth == 0:
            return _plan_region(img, region, eff, _other(axis), depth + 1, min_pieces)
        return [Tile(region, region)], [f"区域 {region.as_tuple()} 没有可用空白带，该块会被模型缩小"]
    keep_edges = [0, *[b.center for b in seams], length]
    box_starts = [0, *[b.start for b in seams]]
    box_ends = [*[b.end for b in seams], length]
    tiles: list[Tile] = []
    notes: list[str] = []
    for i in range(len(seams) + 1):
        box = _span(region, axis, box_starts[i], box_ends[i])
        keep = _span(region, axis, keep_edges[i], keep_edges[i + 1])
        if box.padded_area > limit and depth == 0:
            sub_tiles, sub_notes = _plan_region(img, box, eff, _other(axis), depth + 1)
            tiles += [Tile(t.box, t.keep.intersect(keep)) for t in sub_tiles]
            notes += sub_notes
            continue
        if box.padded_area > limit:
            notes.append(f"区域 {box.as_tuple()} 超过像素上限，该块会被模型缩小")
        tiles.append(Tile(box, keep))
    return tiles, notes


def _plan_slabs(img: Image.Image, region: Box, eff: int, axis: Axis) -> tuple[list[Tile], list[str]]:
    """Full-span strips along `axis` can never fit once padded to 3:1 (the other side is too
    long), so cut slabs along the other axis first, thin enough for their strips to fit, then
    cut each slab along `axis`."""
    limit = FILL * eff
    other = _other(axis)
    length = region.width if other == "x" else region.height
    max_span = int(math.sqrt(PAD_RATIO * limit))
    sub = img.crop(region.as_tuple())
    bands = [b for b in find_blank_bands(sub, other) if b.start > 0 and b.end < length]
    seams = _greedy_seams(length, bands, lambda a, b: b - a <= max_span)
    if not seams:
        return _even_strips(img, region, eff, axis)
    keep_edges = [0, *[b.center for b in seams], length]
    box_starts = [0, *[b.start for b in seams]]
    box_ends = [*[b.end for b in seams], length]
    tiles: list[Tile] = []
    notes: list[str] = []
    for i in range(len(seams) + 1):
        slab = _span(region, other, box_starts[i], box_ends[i])
        keep = _span(region, other, keep_edges[i], keep_edges[i + 1])
        sub_tiles, sub_notes = _plan_region(img, slab, eff, axis, depth=1)
        tiles += [Tile(t.box, t.keep.intersect(keep)) for t in sub_tiles]
        notes += sub_notes
    return tiles, notes


def _even_strips(img: Image.Image, region: Box, eff: int, axis: Axis) -> tuple[list[Tile], list[str]]:
    """Fallback when no slab can be cut: evenly spaced strips along `axis`. They exceed the cap
    somewhat once padded (the model shrinks them a little), which still beats one whole tile."""
    limit = FILL * eff
    length = region.width if axis == "x" else region.height
    sub = img.crop(region.as_tuple())
    bands = [b for b in find_blank_bands(sub, axis) if b.start > 0 and b.end < length]
    seams = _balanced_seams(length, bands, max(2, math.ceil(region.area / limit)))
    if not seams:
        return [Tile(region, region)], [f"区域 {region.as_tuple()} 没有可用空白带，该块会被模型缩小"]
    keep_edges = [0, *[b.center for b in seams], length]
    box_starts = [0, *[b.start for b in seams]]
    box_ends = [*[b.end for b in seams], length]
    tiles: list[Tile] = []
    notes: list[str] = []
    for i in range(len(seams) + 1):
        box = _span(region, axis, box_starts[i], box_ends[i])
        if box.padded_area > limit:
            notes.append(f"区域 {box.as_tuple()} 超过像素上限，该块会被模型缩小")
        tiles.append(Tile(box, _span(region, axis, keep_edges[i], keep_edges[i + 1])))
    return tiles, notes
