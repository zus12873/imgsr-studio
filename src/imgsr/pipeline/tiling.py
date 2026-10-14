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
    if mode == "whole" or (mode == "auto" and full.area <= eff):
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
    pieces = max(min_pieces, math.ceil(region.area / (FILL * eff)))
    if pieces <= 1:
        return [Tile(region, region)], []
    length = region.width if axis == "x" else region.height
    across = region.height if axis == "x" else region.width

    def fits(a: int, b: int) -> bool:
        return (b - a) * across <= FILL * eff

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
        if box.area > FILL * eff and depth == 0:
            sub_tiles, sub_notes = _plan_region(img, box, eff, _other(axis), depth + 1)
            tiles += [Tile(t.box, t.keep.intersect(keep)) for t in sub_tiles]
            notes += sub_notes
            continue
        if box.area > FILL * eff:
            notes.append(f"区域 {box.as_tuple()} 超过像素上限，该块会被模型缩小")
        tiles.append(Tile(box, keep))
    return tiles, notes
