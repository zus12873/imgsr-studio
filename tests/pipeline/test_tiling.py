import numpy as np
from PIL import Image, ImageDraw

from imgsr.pipeline.tiling import NO_BAND_NOTE, Box, TilePlan, plan_tiles

CAP = 1_550_000


def two_column_page(w=2316, h=1294, gap=(919, 999)):
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    d.rectangle((20, 40, gap[0] - 1, h - 40), fill=0)
    d.rectangle((gap[1], 40, w - 20, h - 40), fill=0)
    return img


def test_small_image_is_whole():
    plan = plan_tiles(Image.new("RGB", (1000, 1000), "white"), CAP)
    assert plan.mode == "whole"
    assert plan.tiles[0].box == plan.tiles[0].keep == Box(0, 0, 1000, 1000)


def test_whole_mode_is_respected_even_when_large():
    assert plan_tiles(Image.new("RGB", (3000, 2000), "white"), CAP, "whole").mode == "whole"


def test_wide_page_splits_at_gap_and_notes_oversized_piece():
    plan = plan_tiles(two_column_page(), CAP)
    assert plan.mode == "tiles"
    assert [t.box.as_tuple() for t in plan.tiles] == [(0, 0, 999, 1294), (919, 0, 2316, 1294)]
    assert [t.keep.as_tuple() for t in plan.tiles] == [(0, 0, 959, 1294), (959, 0, 2316, 1294)]
    assert any("缩小" in note for note in plan.notes)


def test_tall_page_splits_into_pieces_under_cap():
    w, h = 1200, 3000
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    for y in range(0, h, 300):
        d.rectangle((50, y + 20, w - 50, y + 260), fill=0)
    plan = plan_tiles(img, CAP)
    assert plan.mode == "tiles" and len(plan.tiles) == 3
    assert all(t.box.area <= 0.95 * CAP for t in plan.tiles)
    keeps = [t.keep for t in plan.tiles]
    assert keeps[0].y0 == 0 and keeps[-1].y1 == h
    assert all(a.y1 == b.y0 for a, b in zip(keeps, keeps[1:], strict=False))


def test_no_bands_falls_back_to_whole_with_note():
    plan = plan_tiles(Image.effect_noise((2000, 1500), 80), CAP)
    assert plan.mode == "whole"
    assert plan.notes == [NO_BAND_NOTE]


def test_forced_tiles_with_preupscale_split_small_image():
    w, h = 558, 714
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    d.rectangle((20, 20, w - 20, 360), fill=0)
    d.rectangle((20, 400, w - 20, h - 20), fill=0)
    plan = plan_tiles(img, CAP, "tiles", preupscale=2)
    assert plan.mode == "tiles" and len(plan.tiles) == 2
    assert plan.tiles[0].keep.y1 == plan.tiles[1].keep.y0 == 380


def test_plan_json_roundtrip():
    plan = plan_tiles(two_column_page(), CAP)
    assert TilePlan.from_json(plan.to_json()) == plan


def test_box_intersect():
    assert Box(0, 0, 10, 10).intersect(Box(5, 2, 20, 8)) == Box(5, 2, 10, 8)


def grid_page(w=2400, h=3000):
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    for y in range(0, h, 300):
        d.rectangle((20, y + 20, 1149, y + 259), fill=0)
        d.rectangle((1250, y + 20, w - 20, y + 259), fill=0)
    return img


def test_box_padded_area():
    assert Box(0, 0, 2400, 600).padded_area == 2400 * 800
    assert Box(0, 0, 1000, 800).padded_area == 1000 * 800


def test_tiles_fit_after_padding_and_cover_page_once():
    img = grid_page()
    plan = plan_tiles(img, CAP)
    assert plan.mode == "tiles" and len(plan.tiles) <= 8
    assert all(t.box.padded_area <= 0.95 * CAP for t in plan.tiles)
    cover = np.zeros((img.height, img.width), dtype=np.int8)
    for t in plan.tiles:
        cover[t.keep.y0:t.keep.y1, t.keep.x0:t.keep.x1] += 1
    assert (cover == 1).all()


def test_wide_strip_is_whole_only_if_padded_area_fits():
    assert plan_tiles(Image.new("L", (1838, 456), 255), CAP).mode == "whole"
    plan = plan_tiles(Image.new("L", (2400, 600), 255), CAP)
    assert plan.mode == "whole" and plan.notes == [NO_BAND_NOTE]


def rows_page(w, h, pitch=150):
    """Full-width text rows: horizontal gaps only, no vertical gap anywhere."""
    img = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(img)
    for y in range(0, h, pitch):
        d.rectangle((20, y + 20, w - 20, y + 120), fill=0)
    return img


def test_long_screenshot_uses_area_not_padded_area_for_piece_count():
    plan = plan_tiles(rows_page(1080, 12000), CAP)
    assert plan.mode == "tiles" and len(plan.tiles) <= 10
    assert all(t.box.padded_area <= 0.95 * CAP for t in plan.tiles)


def test_refine_without_vertical_gaps_falls_back_to_even_strips():
    plan = plan_tiles(rows_page(1200, 2400), CAP, "tiles", preupscale=2)
    assert plan.mode == "tiles" and 2 <= len(plan.tiles) <= 16
