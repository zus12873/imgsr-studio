from imgsr.pipeline.textdiff import Diff, compare, normalize


def test_normalize_unifies_punctuation_and_drops_noise():
    assert normalize("你好, 世界!\n[?]——…") == "你好，世界！"


def test_identical_modulo_punctuation_has_no_diffs():
    assert compare("小猫，真可爱!", "小猫, 真可爱！") == []


def test_substitution_reports_sentence():
    diffs = compare("晚上还会发出亮光呢！小猫咪特别爱干净。", "晚上还会发出光光呢！小猫咪特别爱干净。")
    assert diffs == [Diff("亮", "光", "晚上还会发出亮光呢！")]


def test_deletion():
    diffs = compare("认认真真地洗脸。", "认真地洗脸。")
    assert len(diffs) == 1
    assert diffs[0].found == "" and len(diffs[0].expected) == 2
    assert diffs[0].sentence == "认认真真地洗脸。"


def test_insertion():
    assert compare("你好。", "你好啊。") == [Diff("", "啊", "你好。")]


def test_to_json():
    assert Diff("a", "b", "c").to_json() == {"expected": "a", "found": "b", "sentence": "c"}


def test_pictographs_and_symbols_are_ignored():
    # Transcriptions include or drop emoji/decorative symbols inconsistently.
    assert compare("👉基础词库：喜欢、爱", "基础词库：喜欢、爱") == []
    assert compare("☆借助下列框架", "借助下列框架") == []
    assert compare("△习作例文1", "习作例文1") == []
