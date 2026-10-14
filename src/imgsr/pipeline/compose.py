"""Pure image operations around the model call: padding, scaling, stitching."""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

from imgsr.pipeline.tiling import Box, TilePlan

MAX_RATIO = 3.0


def edge_color(img: Image.Image) -> tuple[int, int, int]:
    a = np.asarray(img.convert("RGB"))
    edges = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    r, g, b = (int(v) for v in np.median(edges, axis=0))
    return (r, g, b)


def pad_to_ratio(img: Image.Image, max_ratio: float = MAX_RATIO) -> tuple[Image.Image, Box]:
    """Pad with the edge colour so long/short side <= max_ratio.

    Returns the padded image and where the original content sits inside it.
    """
    w, h = img.size
    if w / h > max_ratio:
        nw, nh = w, math.ceil(w / max_ratio)
    elif h / w > max_ratio:
        nw, nh = math.ceil(h / max_ratio), h
    else:
        return img, Box(0, 0, w, h)
    canvas = Image.new("RGB", (nw, nh), edge_color(img))
    x, y = (nw - w) // 2, (nh - h) // 2
    canvas.paste(img.convert("RGB"), (x, y))
    return canvas, Box(x, y, x + w, y + h)


def crop_content(result: Image.Image, padded_size: tuple[int, int], content: Box) -> Image.Image:
    """Undo pad_to_ratio on a (possibly rescaled) model output."""
    sx, sy = result.width / padded_size[0], result.height / padded_size[1]
    return result.crop(
        (
            round(content.x0 * sx),
            round(content.y0 * sy),
            round(content.x1 * sx),
            round(content.y1 * sy),
        )
    )


def upscale(img: Image.Image, factor: int) -> Image.Image:
    if factor == 1:
        return img
    return img.resize((img.width * factor, img.height * factor), Image.LANCZOS)


def stitch(
    plan: TilePlan, outputs: list[Image.Image], src_size: tuple[int, int]
) -> tuple[Image.Image, float]:
    """Combine per-tile outputs (same order as plan.tiles) into one image.

    Returns (image, scale) where scale maps source pixels to result pixels.
    """
    if plan.mode == "whole":
        out = outputs[0].convert("RGB")
        return out, out.width / src_size[0]
    raw = min(
        min(o.width / t.box.width, o.height / t.box.height)
        for o, t in zip(outputs, plan.tiles, strict=True)
    )
    s = max(0.1, math.floor(raw * 10 + 1e-9) / 10)
    canvas = Image.new("RGB", (round(src_size[0] * s), round(src_size[1] * s)), "white")
    for out, tile in zip(outputs, plan.tiles, strict=True):
        bx0, by0 = round(tile.box.x0 * s), round(tile.box.y0 * s)
        bw, bh = round(tile.box.x1 * s) - bx0, round(tile.box.y1 * s) - by0
        scaled = out.convert("RGB").resize((bw, bh), Image.LANCZOS)
        kx0, ky0 = round(tile.keep.x0 * s), round(tile.keep.y0 * s)
        kx1, ky1 = round(tile.keep.x1 * s), round(tile.keep.y1 * s)
        canvas.paste(scaled.crop((kx0 - bx0, ky0 - by0, kx1 - bx0, ky1 - by0)), (kx0, ky0))
    return canvas, s


def make_download(result: Image.Image, src_size: tuple[int, int]) -> Image.Image:
    """Never hand back fewer pixels than the source."""
    if result.width >= src_size[0] and result.height >= src_size[1]:
        return result
    return result.resize(src_size, Image.LANCZOS)
