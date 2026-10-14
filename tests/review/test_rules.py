from imgsr.pipeline.textdiff import Diff
from imgsr.review.rules import Suggestion, suggest

D = Diff("亮", "光", "晚上还会发出亮光呢！")


def actions(sugs):
    return [s.action for s in sugs]


def test_no_text_means_manual_check():
    sugs = suggest([], has_text=False, used_hint=False, preupscale=1, previous=None)
    assert actions(sugs) == ["manual_check"]


def test_clean_round_suggests_accept():
    sugs = suggest([], has_text=True, used_hint=True, preupscale=1, previous=None)
    assert actions(sugs) == ["accept"]


def test_first_fix_is_text_hint():
    sugs = suggest([D], has_text=True, used_hint=False, preupscale=1, previous=None)
    assert actions(sugs) == ["retry_with_hint"]
    assert sugs[0].params == {"use_text_hint": True} and sugs[0].diff_ids == [0]


def test_then_tile_refine():
    sugs = suggest([D], has_text=True, used_hint=True, preupscale=1, previous=None)
    assert actions(sugs) == ["tile_refine"]
    assert sugs[0].params == {"strategy": "tiles", "preupscale": 2, "use_text_hint": True}


def test_exhausted_falls_back_to_manual_check():
    sugs = suggest([D], has_text=True, used_hint=True, preupscale=2, previous=None)
    assert actions(sugs) == ["manual_check"] and sugs[0].diff_ids == [0]


def test_repeated_diff_adds_manual_check():
    sugs = suggest(
        [D, Diff("", "多", "x。")], has_text=True, used_hint=True, preupscale=1, previous=[D]
    )
    assert actions(sugs) == ["tile_refine", "manual_check"]
    assert sugs[1].diff_ids == [0]


def test_insertions_match_by_found_text():
    sugs = suggest(
        [Diff("", "多", "x。")],
        has_text=True,
        used_hint=True,
        preupscale=2,
        previous=[Diff("", "多", "y。")],
    )
    assert actions(sugs) == ["manual_check"] and sugs[0].diff_ids == [0]


def test_to_json():
    assert Suggestion("accept", "ok").to_json() == {
        "action": "accept", "reason": "ok", "diff_ids": [], "params": {}
    }
