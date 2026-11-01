import type { GameResult, EndReason } from "./types.js";

/** fetch ile uyumlu en küçük arayüz (testte sahtesi verilir). */
export type FetchLike = (
  url: string,
  init: { method: string; headers: Record<string, string>; body?: string; signal?: AbortSignal },
) => Promise<{ ok: boolean; status: number; json(): Promise<unknown> }>;

export interface BotMoveResponse {
  uci: string;
  think_ms: number;
}

export interface UserMoveBody {
  ply: number;
  fen_before: string;
  uci: string;
  spent_ms: number;
  clock_ms: number;
  focus_lost?: boolean;
}

export interface FinishBody {
  result: GameResult;
  reason: EndReason;
  pgn: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
  }
}

/** Ölçüm servisi (CONTRACTS.md bölüm 2) istemcisi. */
export class ApiClient {
  constructor(
    private baseUrl: string,
    private fetchFn: FetchLike,
    /** İstek başına zaman aşımı (ms); asılı kalan API oyunu durdurmasın. */
    private timeoutMs = 10_000,
    /** Ölçüm servisinin /games/* uçları için paylaşılan iç belirteç (CHESSDEX_INTERNAL_TOKEN). */
    private internalToken?: string,
  ) {
    this.baseUrl = baseUrl.replace(/\/+$/, "");
  }

  private async post(path: string, body: unknown): Promise<unknown> {
    const res = await this.fetchFn(this.baseUrl + path, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...(this.internalToken ? { "x-internal-token": this.internalToken } : {}),
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(this.timeoutMs),
    });
    if (!res.ok) throw new ApiError(`POST ${path} -> HTTP ${res.status}`, res.status);
    return res.json();
  }

  async botMove(gid: string, fen: string, ply: number): Promise<BotMoveResponse> {
    const r = (await this.post(`/games/${encodeURIComponent(gid)}/bot-move`, { fen, ply })) as
      | Partial<BotMoveResponse>
      | null;
    if (!r || typeof r.uci !== "string") throw new ApiError("bot-move: geçersiz yanıt");
    const think = typeof r.think_ms === "number" && Number.isFinite(r.think_ms) ? r.think_ms : 0;
    return { uci: r.uci, think_ms: Math.max(0, think) };
  }

  async userMove(gid: string, body: UserMoveBody): Promise<void> {
    await this.post(`/games/${encodeURIComponent(gid)}/user-move`, body);
  }

  async finish(gid: string, body: FinishBody): Promise<void> {
    await this.post(`/games/${encodeURIComponent(gid)}/finish`, body);
  }
}
