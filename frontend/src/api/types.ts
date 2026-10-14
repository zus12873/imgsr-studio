export type TaskStatus =
  | "uploaded"
  | "transcribing"
  | "awaiting_confirm"
  | "transcribe_failed"
  | "ready"
  | "generating"
  | "reviewing"
  | "reviewed"
  | "round_failed"
  | "done";

export interface Diff {
  expected: string;
  found: string;
  sentence: string;
}

export type SuggestionAction = "accept" | "retry_with_hint" | "tile_refine" | "manual_check";

export interface Suggestion {
  action: SuggestionAction;
  reason: string;
  diff_ids: number[];
  params: Record<string, unknown>;
}

export interface Review {
  model: string | null;
  transcript: string;
  diffs: Diff[];
  suggestions: Suggestion[];
  error?: string;
}

export interface TilePlanJson {
  mode: "whole" | "tiles";
  tiles: { box: number[]; keep: number[] }[];
  notes: string[];
}

export interface Strategy {
  mode: "auto" | "whole" | "tiles";
  preupscale: 1 | 2;
  plan?: TilePlanJson;
  scale?: number;
}

export type RoundStatus = "queued" | "running" | "succeeded" | "failed";

export interface Round {
  id: number;
  seq: number;
  status: RoundStatus;
  image_model: string;
  prompt: string;
  strategy: Strategy;
  use_text_hint: boolean;
  result_w: number | null;
  result_h: number | null;
  download_w: number | null;
  download_h: number | null;
  elapsed_s: number | null;
  error: string | null;
  review: Review | null;
  created_at: string;
}

export interface Task {
  id: string;
  status: TaskStatus;
  source_w: number;
  source_h: number;
  transcript_raw: string | null;
  confirmed_text: string | null;
  final_round_id: number | null;
  error: string | null;
  created_at: string;
  expires_at: string;
  rounds: Round[];
  busy: boolean;
}

export interface TaskSummary {
  id: string;
  status: TaskStatus;
  source_w: number;
  source_h: number;
  created_at: string;
  final_round_id: number | null;
  rounds: number;
}

export interface TaskPage {
  items: TaskSummary[];
  next_cursor: string | null;
}

export interface GuestTask {
  id: string;
  status: TaskStatus;
  source_w: number;
  source_h: number;
  created_at: string;
  expires_at: string;
  round: Round | null;
}

export interface Quota {
  limit: number;
  remaining: number;
  global_remaining: number;
}

export interface Me {
  id: number;
  username: string;
  role: "admin" | "user";
  daily_quota: number;
  used_today: number;
}

export interface AdminUser {
  id: number;
  username: string;
  role: "admin" | "user";
  daily_quota: number;
  disabled: boolean;
  created_at: string;
  used_today: number;
}

export interface SettingsView {
  effective: Record<string, string | number>;
  overrides: Record<string, string | number>;
  restart_required: string[];
}

export interface RoundRequest {
  prompt?: string | null;
  strategy?: "auto" | "whole" | "tiles";
  preupscale?: 1 | 2;
  use_text_hint?: boolean;
  suggestion?: { round_id: number; index: number };
}
