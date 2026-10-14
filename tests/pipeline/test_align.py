from imgsr.pipeline.align import slice_for_tile

CONFIRMED = "第一段文字在这里。\n第二段内容也在这里。\n第三段是最后的部分。"


def test_slice_middle_paragraph():
    assert slice_for_tile(CONFIRMED, "第二段内容也在这里。") == "第二段内容也在这里。"


def test_slice_tolerates_transcription_errors():
    got = slice_for_tile(CONFIRMED, "第二段内客也在这里。\n第三段是最后的部分。")
    assert got == "第二段内容也在这里。\n第三段是最后的部分。"


def test_slice_extends_over_unmatched_head():
    assert slice_for_tile(CONFIRMED, "弟二段内容也在这里。") == "第二段内容也在这里。"


def test_no_overlap_returns_empty():
    assert slice_for_tile(CONFIRMED, "完全无关的字符串ABC") == ""


def test_empty_inputs():
    assert slice_for_tile("", "x") == ""
    assert slice_for_tile("abc", "  ") == ""
