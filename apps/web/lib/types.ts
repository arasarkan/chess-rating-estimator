// Sözleşme (docs/CONTRACTS.md §2, §3) JSON tiplerinin TypeScript karşılıkları.

export type Mode = "full" | "short";
export type Color = "white" | "black";

export interface Survey {
  years_playing?: string;
  games_per_week?: string;
  tournament?: string;
  [k: string]: unknown;
}

export interface Estimate {
  median: number;
  lo90: number;
  hi90: number;
  sd: number;
  n_items: number;
  stage: string;
}

export interface CreateSessionRequest {
  mode: Mode;
  survey?: Survey;
  /** Cloudflare Turnstile belirteci (API'de CHESSDEX_TURNSTILE_SECRET tanımlıysa zorunlu). */
  turnstile_token?: string;
}
export interface CreateSessionResponse {
  session_id: string;
  estimate: Estimate;
}

/** Çoktan seçmeli şık: sözleşmede biçimi sabit değil; düz UCI dizesi ya da nesne kabul edilir. */
export type Choice = string | { uci: string; label?: string };

export interface Item {
  token: string;
  fen: string;
  orientation: Color;
  kind: string;
  prompt: string;
  n_moves: number;
  choices?: Choice[] | null;
  /** Senaryonun ilk gösteriminden beri sunucunun ölçtüğü süre (ms). */
  elapsed_ms?: number;
  index?: number;
  max_items?: number;
  /** Yalnız kısa mod: senaryo zaman bütçesi ve şimdiye kadar harcanan (sunucu ölçümü, ms). */
  time_budget_ms?: number;
  spent_ms?: number;
}

export type NextItemResponse = { done: false; item: Item } | { done: true };

export interface ResponseRequest {
  token: string;
  moves: string[];
  elapsed_ms: number;
  /** Sözleşme eki: çok hamleli senaryolarda ara hamle. */
  partial?: boolean;
}

export interface FinalResponse {
  correct: boolean;
  score: number;
  solution: string[];
  estimate: Estimate;
  done: boolean;
}
export interface ContinueResponse {
  continue: true;
  reply: string | null;
}
export type ResponseResult = FinalResponse | ContinueResponse;

export function isContinue(r: ResponseResult): r is ContinueResponse {
  return (r as ContinueResponse).continue === true;
}

export interface TimeControl {
  initial_ms: number;
  increment_ms: number;
}

export interface CreateGameResponse {
  game_id: string;
  bot_level: number;
  user_color: Color;
  time_control: TimeControl;
  seed: number;
}

export interface ScaleEstimate {
  median: number;
  lo90: number;
  hi90: number;
  sd?: number;
  [k: string]: unknown;
}

export type SubskillName = "tactics" | "endgame" | "positional" | "defense" | "time";

export interface CriticalMoment {
  ply: number;
  played: string;
  eval_loss: number;
  typical: string | null;
  /** Sunucunun verdiği hamle numarası, sıra ve standart notasyon (eski sunucularda olmayabilir). */
  move_no?: number;
  side?: "white" | "black";
  played_san?: string;
  typical_san?: string;
}

export type Flag = string | { code?: string; message?: string; [k: string]: unknown };

export interface ExternalAccount {
  platform: "lichess" | "chesscom";
  username: string;
  rating: number | null;
  rd: number | null;
  games: number | null;
  provisional: boolean;
  calibration_eligible: boolean;
  ineligible_reasons: string[];
}

export interface Comparison {
  scale?: "lichess" | "chesscom";
  verified_rating: number;
  difference: number;
  inside_90: boolean;
}

export interface Report {
  external?: ExternalAccount | null;
  comparison?: Comparison | null;
  estimate: Estimate;
  scales: { lichess: ScaleEstimate; chesscom: ScaleEstimate; fide: ScaleEstimate };
  subskills: Partial<Record<SubskillName, ScaleEstimate | null>>;
  critical_moments: CriticalMoment[];
  flags: Flag[];
  model_version: Record<string, unknown>;
}

export interface Health {
  ok: boolean;
  human_model: string;
  stockfish: boolean | string;
}

// --- Oyun sunucusu WS mesajları (§3) ---

export interface Clocks {
  white: number;
  black: number;
}

export type ClientMsg =
  | {
      t: "join";
      session_id: string;
      game_id: string;
      user_color: Color;
      time_control: TimeControl;
    }
  | { t: "move"; uci: string; ply: number; focus_lost?: boolean }
  | { t: "resign" };

export type ServerMsg =
  | {
      t: "state";
      fen: string;
      ply: number;
      clocks: Clocks;
      turn: Color | "w" | "b";
      user_color: Color;
      status: string;
      moves: string[];
    }
  | { t: "move"; uci: string; by: "user" | "bot"; fen: string; clocks: Clocks }
  | { t: "illegal"; uci: string }
  | { t: "end"; result: string; reason: string }
  | { t: "error"; detail?: string; message?: string };
