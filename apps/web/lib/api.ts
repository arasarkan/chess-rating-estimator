// Ölçüm servisi (FastAPI, docs/CONTRACTS.md §2) için tipli fetch sarmalayıcı.
// NEXT_PUBLIC_MOCK=1 ise tarayıcı içi sahte servis (lib/mock.ts) kullanılır.

import { mockApi } from "./mock";
import type {
  CreateGameResponse,
  CreateSessionRequest,
  CreateSessionResponse,
  Health,
  Mode,
  NextItemResponse,
  Report,
  ResponseRequest,
  ResponseResult,
  ExternalAccount,
} from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8080/ws";
export const MOCK = process.env.NEXT_PUBLIC_MOCK === "1";

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_URL + path, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "Ölçüm servisine ulaşılamadı (" + API_URL + ").");
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  if (!res.ok) {
    const d = (data as { detail?: unknown } | null)?.detail;
    throw new ApiError(res.status, typeof d === "string" ? d : `HTTP ${res.status}`);
  }
  return data as T;
}

const enc = encodeURIComponent;

const realApi = {
  health: () => request<Health>("GET", "/health"),
  createSession: (req: CreateSessionRequest) => request<CreateSessionResponse>("POST", "/sessions", req),
  nextItem: (sid: string) => request<NextItemResponse>("GET", `/sessions/${enc(sid)}/next-item`),
  postResponse: (sid: string, req: ResponseRequest) =>
    request<ResponseResult>("POST", `/sessions/${enc(sid)}/responses`, req),
  createGame: (sid: string) => request<CreateGameResponse>("POST", `/sessions/${enc(sid)}/game`),
  report: (sid: string) => request<Report>("GET", `/sessions/${enc(sid)}/report`),
  linkLichess: (sid: string) => request<{ authorize_url: string }>("POST", `/sessions/${enc(sid)}/link/lichess`),
  chesscomStart: (sid: string, username: string) =>
    request<{ code: string; expires_in_s: number; instructions: string }>("POST", `/sessions/${enc(sid)}/link/chesscom`, {
      username,
    }),
  chesscomVerify: (sid: string) =>
    request<{ external: ExternalAccount }>("POST", `/sessions/${enc(sid)}/link/chesscom/verify`),
};

/**
 * /games/{gid}/bot-move, /user-move, /finish uçlarını oyun sunucusu çağırır; web istemcisi kullanmaz.
 * Sözleşmenin tamamı tipli olsun diye burada bulunur.
 */
export const gameServerEndpoints = {
  botMove: (gid: string, body: { fen: string; ply: number }) =>
    request<{ uci: string; think_ms: number }>("POST", `/games/${enc(gid)}/bot-move`, body),
  userMove: (
    gid: string,
    body: { ply: number; fen_before: string; uci: string; spent_ms: number; clock_ms: number },
  ) => request<{ ok: boolean }>("POST", `/games/${enc(gid)}/user-move`, body),
  finish: (gid: string, body: { result: "1-0" | "0-1" | "1/2-1/2"; reason: string; pgn: string }) =>
    request<{ ok: boolean }>("POST", `/games/${enc(gid)}/finish`, body),
};

export const api: typeof realApi = MOCK ? mockApi : realApi;

/** Oturum/oyun bulunamadı (geçersiz bağlantı ya da süresi dolmuş oturum). */
export function isNotFound(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404;
}

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.detail;
  if (e instanceof Error) return e.message;
  return String(e);
}

// --- Oturum bazlı istemci notları (sessionStorage) ---
function ssGet<T>(key: string): T | null {
  try {
    const v = sessionStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : null;
  } catch {
    return null;
  }
}
function ssSet(key: string, v: unknown) {
  try {
    sessionStorage.setItem(key, JSON.stringify(v));
  } catch {
    /* yoksay */
  }
}

export const local = {
  getMode: (sid: string) => ssGet<Mode>(`chessdex:mode:${sid}`),
  setMode: (sid: string, m: Mode) => ssSet(`chessdex:mode:${sid}`, m),
  getGame: (sid: string) => ssGet<CreateGameResponse>(`chessdex:game:${sid}`),
  setGame: (sid: string, g: CreateGameResponse) => ssSet(`chessdex:game:${sid}`, g),
};
