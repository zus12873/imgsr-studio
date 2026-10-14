"""Rule engine: review diffs -> short list of next-step suggestions (spec §6.5)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from imgsr.pipeline.textdiff import Diff

Action = Literal["accept", "retry_with_hint", "tile_refine", "manual_check"]


@dataclass(frozen=True)
class Suggestion:
    action: Action
    reason: str
    diff_ids: list[int] = field(default_factory=list)
    params: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return asdict(self)


def _key(diff: Diff) -> str:
    return diff.expected if diff.expected else f"+{diff.found}"


def suggest(
    diffs: list[Diff],
    *,
    has_text: bool,
    used_hint: bool,
    preupscale: int,
    previous: list[Diff] | None,
    can_refine: bool = True,
) -> list[Suggestion]:
    """`can_refine` is False when a 2x-preupscaled tiling would exceed the per-round tile cap."""
    if not has_text:
        return [Suggestion("manual_check", "没有确认原文，无法自动比对，请人工放大核对")]
    if not diffs:
        return [Suggestion("accept", "结果转写与确认原文一致，可以设为最终版")]
    all_ids = list(range(len(diffs)))
    previous_keys = {_key(d) for d in previous or []}
    repeated = [i for i, d in enumerate(diffs) if _key(d) in previous_keys]
    out: list[Suggestion] = []
    if not used_hint:
        out.append(
            Suggestion("retry_with_hint", "上一轮没有带原文提示，带上完整原文重跑", all_ids,
                       {"use_text_hint": True})
        )
    elif preupscale < 2 and can_refine:
        out.append(
            Suggestion("tile_refine", "已带原文提示仍有差异，切块并预放大 2 倍后重绘", all_ids,
                       {"strategy": "tiles", "preupscale": 2, "use_text_hint": True})
        )
    if repeated:
        out.append(
            Suggestion("manual_check", "这些差异连续两轮出现，模型可能改不对，请人工放大核对或接受",
                       repeated)
        )
    if not out:
        out.append(Suggestion("manual_check", "自动修正手段已用尽，请人工核对剩余差异", all_ids))
    return out
