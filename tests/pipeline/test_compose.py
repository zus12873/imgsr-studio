from PIL import Image

from imgsr.pipeline.compose import (
    crop_content,
    edge_color,
    make_download,
    pad_to_ratio,
    stitch,
    upscale,
)
from imgsr.pipeline.tiling import Box, Tile, TilePlan


def test_pad_wide_image_to_three_to_one():
    img = Image.new("RGB", (1838, 456), "white")
    padded, content = pad_to_ratio(img)
    assert padded.size == (1838, 613)
    assert content == Box(0, 78, 1838, 534)


def test_pad_tall_image():
    padded, content = pad_to_ratio(Image.new("RGB", (100, 400), "white"))
    assert padded.size == (134, 400)
    assert content == Box(17, 0, 117, 400)


def test_no_padding_needed_returns_same_image():
    img = Image.new("RGB", (300, 200), "white")
    padded, content = pad_to_ratio(img)
    assert padded is img and content == Box(0, 0, 300, 200)


def test_crop_content_undoes_padding_after_model_rescale():
    padded, content = pad_to_ratio(Image.new("RGB", (1838, 456), "white"))
    model_out = padded.resize((2171, 724))
    cropped = crop_content(model_out, padded.size, content)
    assert cropped.width == 2171
    assert abs(cropped.width / cropped.height - 1838 / 456) / (1838 / 456) < 0.01


def test_edge_color_uses_border_median():
    img = Image.new("RGB", (50, 50), (250, 250, 250))
    img.paste((0, 0, 0), (10, 10, 40, 40))
    assert edge_color(img) == (250, 250, 250)


def test_upscale():
    assert upscale(Image.new("RGB", (10, 7)), 2).size == (20, 14)
    img = Image.new("RGB", (10, 7))
    assert upscale(img, 1) is img


def test_stitch_whole_returns_output_and_scale():
    out = Image.new("RGB", (200, 100), "red")
    plan = TilePlan("whole", [Tile(Box(0, 0, 100, 50), Box(0, 0, 100, 50))])
    result, scale = stitch(plan, [out], (100, 50))
    assert result.size == (200, 100) and scale == 2.0


def two_tile_plan():
    return TilePlan(
        "tiles",
        [
            Tile(Box(0, 0, 110, 100), Box(0, 0, 100, 100)),
            Tile(Box(90, 0, 200, 100), Box(100, 0, 200, 100)),
        ],
    )


def test_stitch_two_tiles_at_seam():
    outs = [Image.new("RGB", (220, 200), "red"), Image.new("RGB", (220, 200), "blue")]
    result, scale = stitch(two_tile_plan(), outs, (200, 100))
    assert scale == 2.0 and result.size == (400, 200)
    assert result.getpixel((199, 100)) == (255, 0, 0)
    assert result.getpixel((201, 100)) == (0, 0, 255)


def test_stitch_uses_smallest_tile_scale():
    outs = [Image.new("RGB", (220, 200), "red"), Image.new("RGB", (165, 150), "blue")]
    result, scale = stitch(two_tile_plan(), outs, (200, 100))
    assert scale == 1.5 and result.size == (300, 150)


def test_make_download_never_smaller_than_source():
    small = Image.new("RGB", (80, 40))
    assert make_download(small, (100, 50)).size == (100, 50)
    big = Image.new("RGB", (200, 100))
    assert make_download(big, (100, 50)) is big
