export type Color = "white" | "black";
export type GameResult = "1-0" | "0-1" | "1/2-1/2";
export type EndReason =
  | "checkmate"
  | "stalemate"
  | "threefold"
  | "insufficient"
  | "fifty_move"
  | "timeout"
  | "resign"
  | "abandoned";

export interface TimeControl {
  initial_ms: number;
  increment_ms: number;
}

/** Kalıcı (JSON'a yazılan) oyun durumu. */
export interface GameState {
  game_id: string;
  session_id: string;
  user_color: Color;
  time_control: TimeControl;
  /** Oynanan hamleler (UCI). `ply` = moves.length. */
  moves: string[];
  /** Sıra başlangıcındaki kalan süreler (sıradaki tarafın geçen süresi henüz düşülmedi). */
  clocks: { white: number; black: number };
  /** Sıradaki tarafın sırasının başladığı an (sunucu saati, ms). */
  turn_started_at: number;
  status: "active" | "ended";
  result: GameResult | null;
  reason: EndReason | null;
  created_at: number;
  updated_at: number;
  /** Bitişin ölçüm servisine bildirilip bildirilmediği. */
  finish_reported: boolean;
}

// ---- İstemci -> sunucu ----
export interface JoinMsg {
  t: "join";
  session_id: string;
  game_id: string;
  user_color?: Color;
  time_control?: TimeControl;
}
export interface MoveMsg {
  t: "move";
  uci: string;
  ply?: number;
  /** İstemci: bu hamlenin düşünme süresinde sekme/pencere odağı kayboldu mu (bütünlük sinyali). */
  focus_lost?: boolean;
}
export interface ResignMsg {
  t: "resign";
}
export type ClientMsg = JoinMsg | MoveMsg | ResignMsg;

// ---- Sunucu -> istemci ----
export interface StateOut {
  t: "state";
  fen: string;
  ply: number;
  clocks: { white: number; black: number };
  turn: Color;
  user_color: Color;
  status: "active" | "ended";
  moves: string[];
}
export interface MoveOut {
  t: "move";
  uci: string;
  by: "user" | "bot";
  fen: string;
  clocks: { white: number; black: number };
}
export interface IllegalOut {
  t: "illegal";
  uci: string;
}
export interface EndOut {
  t: "end";
  result: GameResult;
  reason: EndReason;
}
export interface ErrorOut {
  t: "error";
  message: string;
}
export type ServerMsg = StateOut | MoveOut | IllegalOut | EndOut | ErrorOut;

/** Bir istemci bağlantısının soyutlaması (ws ya da testte sahte). */
export interface Conn {
  send(msg: ServerMsg): void;
}

export interface Clock {
  now(): number;
}
