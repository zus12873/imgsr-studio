import pytest
from PIL import Image, ImageDraw

from imgsr.pipeline.bands import Band, find_blank_bands


def canvas(w, h):
    return Image.new("L", (w, h), 255)


def ink(img, box):
    ImageDraw.Draw(img).rectangle(box, fill=0)


def inner(bands, length, margin=0):
    return [(b.start, b.end) for b in bands if b.start > margin and b.end < length - margin]


def test_vertical_band_between_two_blocks():
    img = canvas(400, 200)
    ink(img, (10, 20, 150, 180))
    ink(img, (250, 20, 390, 180))
    assert inner(find_blank_bands(img, "x"), 400) == [(151, 250)]


def test_horizontal_bands():
    img = canvas(300, 400)
    for y0, y1 in ((10, 100), (150, 250), (300, 390)):
        ink(img, (10, y0, 290, y1))
    assert inner(find_blank_bands(img, "y"), 400) == [(101, 150), (251, 300)]


def test_narrow_gap_is_ignored():
    img = canvas(300, 100)
    ink(img, (0, 10, 140, 90))
    ink(img, (146, 10, 299, 90))  # 5-px gap < min_width
    assert inner(find_blank_bands(img, "x"), 300) == []


def test_dark_frame_does_not_hide_bands():
    img = canvas(400, 200)
    ImageDraw.Draw(img).rectangle((0, 0, 399, 199), outline=0, width=4)
    ink(img, (20, 30, 150, 170))
    ink(img, (250, 30, 380, 170))
    assert inner(find_blank_bands(img, "x"), 400, margin=4) == [(151, 250)]


def test_band_properties():
    band = Band(10, 30)
    assert (band.center, band.width) == (20, 20)


def test_accepts_rgb_images():
    img = Image.new("RGB", (300, 100), "white")
    ImageDraw.Draw(img).rectangle((0, 10, 100, 90), fill="black")
    ImageDraw.Draw(img).rectangle((200, 10, 299, 90), fill="black")
    assert inner(find_blank_bands(img, "x"), 300) == [(101, 200)]


@pytest.mark.parametrize("frame", [4, 7, 20, 30])  # 2%, 3.5%, 10%, 15% of the 200-px lines
def test_thick_frames_do_not_hide_bands(frame):
    img = canvas(400, 200)
    ImageDraw.Draw(img).rectangle((0, 0, 399, 199), outline=0, width=frame)
    ink(img, (frame + 10, frame + 10, 150, 199 - frame - 10))
    ink(img, (250, frame + 10, 399 - frame - 10, 199 - frame - 10))
    assert inner(find_blank_bands(img, "x"), 400, margin=frame) == [(151, 250)]


def test_content_near_the_edge_is_not_ignored():
    img = canvas(1000, 300)
    ink(img, (10, 10, 990, 100))
    ink(img, (10, 200, 990, 290))
    ink(img, (985, 140, 995, 160))  # small right-aligned badge in the outer 3% of each row
    bands = inner(find_blank_bands(img, "y"), 300)
    assert bands and all(not (b0 <= 150 < b1) for b0, b1 in bands)
