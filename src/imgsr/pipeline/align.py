"""Find the part of the confirmed text that one tile shows."""

from __future__ import annotations

import difflib

_MIN_BLOCK = 3  # ignore stray 1–2 character coincidences such as "的"
_MAX_GAP = 40  # blocks further apart than this belong to different regions
_MAX_EXTEND = 20  # how far to stretch over unmatched transcript head/tail


def slice_for_tile(confirmed: str, tile_transcript: str) -> str:
    if not confirmed.strip() or not tile_transcript.strip():
        return ""
    matcher = difflib.SequenceMatcher(None, confirmed, tile_transcript, autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size >= _MIN_BLOCK]
    if not blocks:
        return ""
    groups = [[blocks[0]]]
    for block in blocks[1:]:
        prev = groups[-1][-1]
        if block.a - (prev.a + prev.size) > _MAX_GAP:
            groups.append([block])
        else:
            groups[-1].append(block)
    best = max(groups, key=lambda g: sum(b.size for b in g))
    first, last = best[0], best[-1]
    head = min(first.b, _MAX_EXTEND)
    tail = min(len(tile_transcript) - (last.b + last.size), _MAX_EXTEND)
    start = max(0, first.a - head)
    end = min(len(confirmed), last.a + last.size + tail)
    return confirmed[start:end].strip()
