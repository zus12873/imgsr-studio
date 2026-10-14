import type { Round, Task } from "../api/types";

export function makeRound(over: Partial<Round> = {}): Round {
  return {
    id: 1,
    seq: 1,
    status: "succeeded",
    image_model: "gpt-image-2.5",
    prompt: "base prompt",
    strategy: { mode: "auto", preupscale: 1, plan: { mode: "whole", tiles: [], notes: [] }, scale: 1 },
    use_text_hint: true,
    result_w: 800,
    result_h: 600,
    download_w: 800,
    download_h: 600,
    elapsed_s: 30,
    error: null,
    review: {
      model: "gpt-6-sol",
      transcript: "原文。",
      diffs: [],
      suggestions: [{ action: "accept", reason: "结果转写与确认原文一致", diff_ids: [], params: {} }],
    },
    created_at: "2026-10-14T06:00:00",
    ...over,
  };
}

export function makeTask(over: Partial<Task> = {}): Task {
  return {
    id: "t1",
    status: "reviewed",
    source_w: 400,
    source_h: 300,
    transcript_raw: "原文。",
    confirmed_text: "原文。",
    final_round_id: null,
    error: null,
    created_at: "2026-10-14T06:00:00",
    expires_at: "2026-11-13T06:00:00",
    rounds: [],
    busy: false,
    ...over,
  };
}
