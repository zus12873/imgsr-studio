"""Prompt texts. BASE_PROMPT was validated in the 2026-10-13 probes."""

from __future__ import annotations

BASE_PROMPT = (
    "This is a blurry, low-resolution screenshot that contains Chinese text. "
    "Restore it into a sharp, clean, high-resolution version of exactly the same image. "
    "Keep every Chinese character, punctuation mark, number, letter, emoji, icon, line break "
    "and paragraph exactly as in the original; do not add, remove, translate, rephrase, reorder "
    "or move anything. Preserve the layout, positions, proportions, borders, boxes, callout "
    "bubbles, underlines, buttons, background colors and every text color and weight. "
    "Re-render all text with crisp, clean typefaces that match the original styles. "
    "No blur, no noise, no JPEG artifacts."
)

TRANSCRIBE_PROMPT = (
    "逐字转写这张图片中的所有中文正文，按阅读顺序输出，段落之间换行。"
    "忽略界面按钮、图标、水印和缩略图。不要改写、不要纠正、不要省略；"
    "看不清的字按上下文填最可能的字，并在该字后加[?]。只输出转写文字。"
)


def split_phrases(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def build_prompt(base: str, hint_text: str | None) -> str:
    phrases = split_phrases(hint_text or "")
    if not phrases:
        return base
    joined = " / ".join(f"「{p}」" for p in phrases)
    return (
        f"{base} For reference, the original text contains these exact phrases "
        f"(keep them character-for-character): {joined}."
    )
