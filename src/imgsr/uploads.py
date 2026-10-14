"""Validate and normalise user uploads into a plain RGB image."""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}


class UploadRejected(Exception):
    """Raised with a user-facing (Chinese) message."""


def normalize_upload(data: bytes, *, max_bytes: int, max_pixels: int) -> Image.Image:
    if not data:
        raise UploadRejected("文件为空")
    if len(data) > max_bytes:
        raise UploadRejected(f"文件超过 {max_bytes // 1_000_000} MB 上限")
    too_big = f"图片像素超过 {max_pixels // 1_000_000} MP 上限"
    # Image.open only parses the header, so the explicit size check below rejects
    # decompression bombs before any pixel is decoded. Pillow's global limit is left alone:
    # changing it here would affect every other image operation in the process.
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in ALLOWED_FORMATS:
            raise UploadRejected("只支持 PNG、JPG、WebP 图片")
        if img.width * img.height > max_pixels:
            raise UploadRejected(too_big)
        img.load()
    except UploadRejected:
        raise
    except Image.DecompressionBombError as exc:
        raise UploadRejected(too_big) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise UploadRejected("无法识别的图片文件") from exc
    return _to_rgb(ImageOps.exif_transpose(img))


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        canvas = Image.new("RGB", rgba.size, "white")
        canvas.paste(rgba, mask=rgba.getchannel("A"))
        return canvas
    if img.mode.startswith("I;16"):
        img = img.convert("I")
    if img.mode == "I":
        img = img.point(lambda v: v * (1 / 256)).convert("L")
    rgb = img.convert("RGB")
    rgb.info.pop("exif", None)
    return rgb
