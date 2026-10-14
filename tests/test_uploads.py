import io

import pytest
from PIL import Image

from imgsr.uploads import UploadRejected, normalize_upload

LIMITS = {"max_bytes": 15_000_000, "max_pixels": 25_000_000}


def encode(img, fmt, **kw):
    buf = io.BytesIO()
    img.save(buf, fmt, **kw)
    return buf.getvalue()


def test_rgba_png_is_flattened_on_white():
    img = Image.new("RGBA", (20, 10), (255, 0, 0, 0))
    img.putpixel((0, 0), (0, 0, 255, 255))
    out = normalize_upload(encode(img, "PNG"), **LIMITS)
    assert out.mode == "RGB"
    assert out.getpixel((5, 5)) == (255, 255, 255)
    assert out.getpixel((0, 0)) == (0, 0, 255)


def test_palette_png_with_transparency():
    img = Image.new("P", (10, 10), 0)
    img.putpalette([255, 0, 0] + [0, 0, 0] * 255)
    out = normalize_upload(encode(img, "PNG", transparency=0), **LIMITS)
    assert out.getpixel((0, 0)) == (255, 255, 255)


def test_cmyk_jpeg_becomes_rgb():
    out = normalize_upload(encode(Image.new("CMYK", (10, 10), (0, 0, 0, 0)), "JPEG"), **LIMITS)
    assert out.mode == "RGB" and out.getpixel((5, 5))[0] > 240


def test_exif_rotation_is_applied():
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise when displayed
    data = encode(Image.new("RGB", (200, 100), "white"), "JPEG", exif=exif)
    out = normalize_upload(data, **LIMITS)
    assert out.size == (100, 200)
    assert not out.info.get("exif")


def test_16bit_grey_png():
    out = normalize_upload(encode(Image.new("I;16", (10, 10), 40000), "PNG"), **LIMITS)
    assert out.mode == "RGB" and out.getpixel((0, 0)) == (156, 156, 156)


@pytest.mark.parametrize(
    "data,message",
    [
        (b"", "文件为空"),
        (b"hello", "无法识别"),
        (encode(Image.new("RGB", (5, 5)), "GIF"), "只支持"),
    ],
)
def test_rejections(data, message):
    with pytest.raises(UploadRejected, match=message):
        normalize_upload(data, **LIMITS)


def test_too_many_bytes():
    with pytest.raises(UploadRejected, match="上限"):
        normalize_upload(b"x" * 11, max_bytes=10, max_pixels=25_000_000)


def test_too_many_pixels():
    data = encode(Image.new("RGB", (200, 100)), "PNG")
    with pytest.raises(UploadRejected, match="像素"):
        normalize_upload(data, max_bytes=15_000_000, max_pixels=10_000)


def test_rejection_does_not_shrink_global_pillow_limit():
    before = Image.MAX_IMAGE_PIXELS
    with pytest.raises(UploadRejected):
        normalize_upload(encode(Image.new("RGB", (200, 100)), "PNG"), max_bytes=15_000_000,
                         max_pixels=10_000)
    assert Image.MAX_IMAGE_PIXELS == before
    Image.open(io.BytesIO(encode(Image.new("RGB", (300, 300)), "PNG"))).load()


def test_mpo_phone_jpeg_is_accepted_and_rotated():
    exif = Image.Exif()
    exif[0x0112] = 6
    extra = Image.new("RGB", (200, 100), "gray")
    data = encode(Image.new("RGB", (200, 100), "white"), "MPO", save_all=True,
                  append_images=[extra], exif=exif)
    assert Image.open(io.BytesIO(data)).format == "MPO"
    out = normalize_upload(data, **LIMITS)
    assert out.mode == "RGB" and out.size == (100, 200)
