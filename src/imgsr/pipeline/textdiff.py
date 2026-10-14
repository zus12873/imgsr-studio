"""Character-level comparison between the confirmed text and a transcript of the result."""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import asdict, dataclass

_PUNCT = str.maketrans(
    {
        ",": "，", "!": "！", "?": "？", ":": "：", ";": "；", "(": "（", ")": "）",
        '"': "“", "”": "“", "'": "‘", "’": "‘",
    }
)
# Transcription uncertainty marks; removed before "?" is turned into "？".
_UNCERTAIN = re.compile(r"\[[?？]\]")
# OCR-noisy characters ignored on both sides: whitespace, dashes, ellipses, bullets, dots.
_DROP = re.compile(r"[\s—–\-－…·•.]")
_SENTENCE_END = "。！？；"


@dataclass(frozen=True)
class Diff:
    expected: str
    found: str
    sentence: str

    def to_json(self) -> dict:
        return asdict(self)


# Emoji, pictographs and decorative symbols (👉 ☆ △) are transcribed inconsistently.
_SYMBOL_CATEGORIES = {"So", "Sk", "Cf"}


def _is_symbol(ch: str) -> bool:
    return unicodedata.category(ch) in _SYMBOL_CATEGORIES or "\ufe00" <= ch <= "\ufe0f"


def normalize(text: str) -> str:
    text = _DROP.sub("", _UNCERTAIN.sub("", text).translate(_PUNCT))
    return "".join(ch for ch in text if not _is_symbol(ch))


def _sentence_at(text: str, index: int) -> str:
    start = max((text.rfind(c, 0, index) for c in _SENTENCE_END), default=-1) + 1
    ends = [p for c in _SENTENCE_END if (p := text.find(c, index)) != -1]
    return text[start : (min(ends) + 1 if ends else len(text))]


def compare(expected: str, found: str) -> list[Diff]:
    e, f = normalize(expected), normalize(found)
    diffs: list[Diff] = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, e, f, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        anchor = min(i1, max(len(e) - 1, 0))
        diffs.append(Diff(e[i1:i2], f[j1:j2], _sentence_at(e, anchor)))
    return diffs
