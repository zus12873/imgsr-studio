from imgsr.pipeline.prompt import BASE_PROMPT, TRANSCRIBE_PROMPT, build_prompt, split_phrases


def test_no_hint_returns_base():
    assert build_prompt(BASE_PROMPT, None) == BASE_PROMPT
    assert build_prompt(BASE_PROMPT, "  \n ") == BASE_PROMPT


def test_hint_lists_each_paragraph():
    prompt = build_prompt("Base.", "第一段。\n\n 第二段。 ")
    assert prompt == (
        "Base. For reference, the original text contains these exact phrases "
        "(keep them character-for-character): 「第一段。」 / 「第二段。」."
    )


def test_split_phrases():
    assert split_phrases("a\n\n b \n") == ["a", "b"]


def test_prompts_mention_key_constraints():
    assert "do not add, remove" in BASE_PROMPT
    assert "[?]" in TRANSCRIBE_PROMPT
