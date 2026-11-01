import { Chess, type Move } from "chess.js";
import type { ApiClient } from "./api.js";
import type { GameStore } from "./store.js";
import type {
  Clock,
  Color,
  Conn,
  EndReason,
  GameResult,
  GameState,
  JoinMsg,
  MoveMsg,
  ServerMsg,
  StateOut,
  TimeControl,
} from "./types.js";

type Timer = ReturnType<typeof setTimeout>;

export const DEFAULT_TIME_CONTROL: TimeControl = { initial_ms: 600_000, increment_ms: 5_000 };

export interface GameServerOptions {
  api: ApiClient;
  store: GameStore;
  clock?: Clock;
  /** Yedek rastgele hamle için [0,1) üreteci. */
  random?: () => number;
  log?: (msg: string) => void;
  /** Kopmadan sonra terk sayılma süresi (vars. 60 000 ms). */
  abandonMs?: number;
  /** bot-move başarısız olursa ek deneme sayısı (vars. 3). */
  botRetries?: number;
  botRetryDelayMs?: number;
  /** user-move/finish gönderimi için toplam deneme sayısı (vars. 6). */
  postAttempts?: number;
  postRetryDelayMs?: number;
  /** Bot düşünürken saatinde en az bu kadar süre bırakılır (vars. 1000 ms). */
  botReserveMs?: number;
}

interface Runtime {
  state: GameState;
  chess: Chess;
  conns: Set<Conn>;
  flagTimer?: Timer;
  abandonTimer?: Timer;
  botTimer?: Timer;
  /** Bot hamlesi istenen ply (eski yanıtları elemek için). */
  botPly: number | null;
  /** Ölçüm servisine sıralı, ateşle-unut gönderimler. */
  outbox: Promise<void>;
}

const UCI_RE = /^[a-h][1-8][a-h][1-8][qrbn]?$/;

export function moveToUci(m: Pick<Move, "from" | "to" | "promotion">): string {
  return m.from + m.to + (m.promotion ?? "");
}

const other = (c: Color): Color => (c === "white" ? "black" : "white");

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/** Bu rengin mat edecek malzemesi var mı? (Saat düşmesinde beraberlik kuralı.) */
function hasMatingMaterial(chess: Chess, color: Color): boolean {
  const c = color === "white" ? "w" : "b";
  let minors = 0;
  for (const row of chess.board()) {
    for (const sq of row) {
      if (!sq || sq.color !== c || sq.type === "k") continue;
      if (sq.type === "n" || sq.type === "b") minors++;
      else return true; // piyon, kale, vezir
    }
  }
  return minors >= 2;
}

function newRuntime(state: GameState, chess: Chess): Runtime {
  return { state, chess, conns: new Set(), botPly: null, outbox: Promise.resolve() };
}

export class GameServer {
  private games = new Map<string, Runtime>();
  private connGame = new Map<Conn, string>();
  private api: ApiClient;
  private store: GameStore;
  private clock: Clock;
  private random: () => number;
  private log: (msg: string) => void;
  private abandonMs: number;
  private botRetries: number;
  private botRetryDelayMs: number;
  private postAttempts: number;
  private postRetryDelayMs: number;
  private botReserveMs: number;

  constructor(opts: GameServerOptions) {
    this.api = opts.api;
    this.store = opts.store;
    this.clock = opts.clock ?? { now: () => Date.now() };
    this.random = opts.random ?? Math.random;
    this.log = opts.log ?? ((m) => console.log(m));
    this.abandonMs = opts.abandonMs ?? 60_000;
    this.botRetries = opts.botRetries ?? 3;
    this.botRetryDelayMs = opts.botRetryDelayMs ?? 250;
    this.postAttempts = opts.postAttempts ?? 6;
    this.postRetryDelayMs = opts.postRetryDelayMs ?? 500;
    this.botReserveMs = opts.botReserveMs ?? 1_000;
    this.restore();
  }

  // ------------------------------------------------------------------ açılış

  /**
   * Depodaki oyunları yükler. Kesinti süresi saatten düşülmez: sıradaki tarafın
   * saati açılış anından itibaren yeniden işlemeye başlar. Bağlı istemci olmadığı
   * için 60 sn terk sayacı da başlar.
   */
  private restore() {
    for (const st of this.store.all()) {
      const chess = new Chess();
      let ok = true;
      for (const uci of st.moves) {
        if (!this.tryMove(chess, uci)) {
          this.log(`[game ${st.game_id}] yüklenemedi: kayıtlı hamle uygulanamadı (${uci})`);
          ok = false;
          break;
        }
      }
      if (!ok) continue;
      const rt = newRuntime(st, chess);
      this.games.set(st.game_id, rt);
      if (st.status === "active") {
        st.turn_started_at = this.clock.now();
        this.store.save(st);
        this.armAbandon(rt);
        this.startTurn(rt);
      } else if (!st.finish_reported && st.result && st.reason) {
        this.reportFinish(rt);
      }
    }
  }

  // ------------------------------------------------------------------ dış arayüz

  handleMessage(conn: Conn, raw: string) {
    let msg: unknown;
    try {
      msg = JSON.parse(raw);
    } catch {
      conn.send({ t: "error", message: "geçersiz JSON" });
      return;
    }
    if (!msg || typeof msg !== "object") {
      conn.send({ t: "error", message: "geçersiz mesaj" });
      return;
    }
    const t = (msg as { t?: unknown }).t;
    switch (t) {
      case "join":
        return this.onJoin(conn, msg as JoinMsg);
      case "move":
        return this.onMove(conn, msg as MoveMsg);
      case "resign":
        return this.onResign(conn);
      default:
        conn.send({ t: "error", message: `bilinmeyen mesaj türü: ${String(t)}` });
    }
  }

  handleClose(conn: Conn) {
    const gid = this.connGame.get(conn);
    this.connGame.delete(conn);
    if (!gid) return;
    const rt = this.games.get(gid);
    if (!rt) return;
    rt.conns.delete(conn);
    if (rt.conns.size === 0 && rt.state.status === "active") this.armAbandon(rt);
  }

  /** Testler ve kapanış için: bekleyen tüm API gönderimlerinin bitmesini bekler. */
  async idle(): Promise<void> {
    await Promise.all([...this.games.values()].map((g) => g.outbox));
  }

  getState(gameId: string): GameState | undefined {
    return this.games.get(gameId)?.state;
  }

  shutdown() {
    for (const rt of this.games.values()) this.clearTimers(rt);
  }

  // ------------------------------------------------------------------ mesajlar

  private onJoin(conn: Conn, msg: JoinMsg) {
    const gid = msg.game_id;
    const sid = msg.session_id;
    if (typeof gid !== "string" || !gid || typeof sid !== "string" || !sid) {
      conn.send({ t: "error", message: "join: session_id ve game_id gerekli" });
      return;
    }
    let rt = this.games.get(gid);
    let created = false;
    if (rt) {
      if (rt.state.session_id !== sid) {
        conn.send({ t: "error", message: "join: session_id bu oyunla eşleşmiyor" });
        return;
      }
    } else {
      if (msg.user_color !== "white" && msg.user_color !== "black") {
        conn.send({ t: "error", message: "join: yeni oyun için user_color (white|black) gerekli" });
        return;
      }
      const tc = msg.time_control;
      const valid =
        !!tc &&
        Number.isFinite(tc.initial_ms) &&
        tc.initial_ms > 0 &&
        Number.isFinite(tc.increment_ms) &&
        tc.increment_ms >= 0;
      const time_control: TimeControl = valid
        ? { initial_ms: tc!.initial_ms, increment_ms: tc!.increment_ms }
        : { ...DEFAULT_TIME_CONTROL };
      const now = this.clock.now();
      const state: GameState = {
        game_id: gid,
        session_id: sid,
        user_color: msg.user_color,
        time_control,
        moves: [],
        clocks: { white: time_control.initial_ms, black: time_control.initial_ms },
        turn_started_at: now,
        status: "active",
        result: null,
        reason: null,
        created_at: now,
        updated_at: now,
        finish_reported: false,
      };
      rt = newRuntime(state, new Chess());
      this.games.set(gid, rt);
      this.store.save(state);
      created = true;
      this.log(`[game ${gid}] oluşturuldu (kullanıcı ${state.user_color})`);
    }

    // Bağlantı başka bir oyundaysa oradan ayır.
    const prev = this.connGame.get(conn);
    if (prev && prev !== gid) this.handleClose(conn);

    rt.conns.add(conn);
    this.connGame.set(conn, gid);
    if (rt.abandonTimer) {
      clearTimeout(rt.abandonTimer);
      rt.abandonTimer = undefined;
    }
    conn.send(this.stateMsg(rt));
    if (rt.state.status === "ended" && rt.state.result && rt.state.reason) {
      conn.send({ t: "end", result: rt.state.result, reason: rt.state.reason });
      return;
    }
    if (created) this.startTurn(rt);
  }

  private onMove(conn: Conn, msg: MoveMsg) {
    const rt = this.gameOf(conn);
    if (!rt) return;
    const uci = typeof msg.uci === "string" ? msg.uci.toLowerCase() : "";
    const st = rt.state;
    if (st.status !== "active") {
      conn.send({ t: "illegal", uci });
      if (st.result && st.reason) conn.send({ t: "end", result: st.result, reason: st.reason });
      return;
    }
    const wrongTurn = this.turn(rt) !== st.user_color;
    const wrongPly = typeof msg.ply === "number" && msg.ply !== st.moves.length;
    if (wrongTurn || wrongPly || !this.isLegal(rt.chess, uci)) {
      conn.send({ t: "illegal", uci });
      conn.send(this.stateMsg(rt));
      return;
    }
    this.applyMove(rt, uci, "user", msg.focus_lost === true);
  }

  private onResign(conn: Conn) {
    const rt = this.gameOf(conn);
    if (!rt || rt.state.status !== "active") return;
    this.end(rt, this.winResult(other(rt.state.user_color)), "resign");
  }

  private gameOf(conn: Conn): Runtime | undefined {
    const gid = this.connGame.get(conn);
    const rt = gid ? this.games.get(gid) : undefined;
    if (!rt) conn.send({ t: "error", message: "önce join gönderin" });
    return rt;
  }

  // ------------------------------------------------------------------ oyun mantığı

  private turn(rt: Runtime): Color {
    return rt.chess.turn() === "w" ? "white" : "black";
  }

  private tryMove(chess: Chess, uci: string): Move | null {
    if (!UCI_RE.test(uci)) return null;
    try {
      return chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] });
    } catch {
      return null;
    }
  }

  private isLegal(chess: Chess, uci: string): boolean {
    if (!UCI_RE.test(uci)) return false;
    return chess.moves({ verbose: true }).some((m) => moveToUci(m) === uci);
  }

  /** Sıradaki tarafın geçen süresi düşülmüş anlık saatler. */
  private liveClocks(rt: Runtime): { white: number; black: number } {
    const c = { ...rt.state.clocks };
    if (rt.state.status === "active") {
      const side = this.turn(rt);
      c[side] = Math.max(0, c[side] - (this.clock.now() - rt.state.turn_started_at));
    }
    return c;
  }

  private stateMsg(rt: Runtime): StateOut {
    return {
      t: "state",
      fen: rt.chess.fen(),
      ply: rt.state.moves.length,
      clocks: this.liveClocks(rt),
      turn: this.turn(rt),
      user_color: rt.state.user_color,
      status: rt.state.status,
      moves: [...rt.state.moves],
    };
  }

  private broadcast(rt: Runtime, msg: ServerMsg) {
    for (const c of rt.conns) {
      try {
        c.send(msg);
      } catch (e) {
        this.log(`[game ${rt.state.game_id}] gönderim hatası: ${String(e)}`);
      }
    }
  }

  private applyMove(rt: Runtime, uci: string, by: "user" | "bot", focusLost = false): boolean {
    const st = rt.state;
    const side = this.turn(rt);
    const now = this.clock.now();
    const spent = now - st.turn_started_at;
    const remaining = st.clocks[side] - spent;
    if (remaining <= 0) {
      this.onFlag(rt);
      return false;
    }
    const fenBefore = rt.chess.fen();
    const ply = st.moves.length;
    const mv = this.tryMove(rt.chess, uci);
    if (!mv) return false;
    const norm = moveToUci(mv);
    st.clocks[side] = remaining + st.time_control.increment_ms;
    st.moves.push(norm);
    st.turn_started_at = now;
    st.updated_at = now;
    this.clearTurnTimers(rt);
    this.store.save(st);

    this.broadcast(rt, { t: "move", uci: norm, by, fen: rt.chess.fen(), clocks: { ...st.clocks } });

    if (by === "user") {
      const gid = st.game_id;
      const body = { ply, fen_before: fenBefore, uci: norm, spent_ms: spent, clock_ms: remaining, focus_lost: focusLost };
      this.enqueue(rt, `user-move ply=${ply}`, () => this.api.userMove(gid, body));
    }

    const over = this.gameOver(rt);
    if (over) this.end(rt, over.result, over.reason);
    else this.startTurn(rt);
    return true;
  }

  private gameOver(rt: Runtime): { result: GameResult; reason: EndReason } | null {
    const c = rt.chess;
    if (c.isCheckmate()) return { result: this.winResult(other(this.turn(rt))), reason: "checkmate" };
    if (c.isStalemate()) return { result: "1/2-1/2", reason: "stalemate" };
    if (c.isInsufficientMaterial()) return { result: "1/2-1/2", reason: "insufficient" };
    if (c.isThreefoldRepetition()) return { result: "1/2-1/2", reason: "threefold" };
    if (c.isDraw()) return { result: "1/2-1/2", reason: "fifty_move" };
    return null;
  }

  private winResult(winner: Color): GameResult {
    return winner === "white" ? "1-0" : "0-1";
  }

  private startTurn(rt: Runtime) {
    if (rt.state.status !== "active") return;
    const side = this.turn(rt);
    const left = rt.state.clocks[side] - (this.clock.now() - rt.state.turn_started_at);
    this.armFlag(rt, left);
    if (side !== rt.state.user_color) void this.requestBot(rt);
  }

  private armFlag(rt: Runtime, ms: number) {
    if (rt.flagTimer) clearTimeout(rt.flagTimer);
    rt.flagTimer = setTimeout(() => {
      rt.flagTimer = undefined;
      this.onFlag(rt);
    }, Math.max(0, ms));
  }

  private onFlag(rt: Runtime) {
    const st = rt.state;
    if (st.status !== "active") return;
    const side = this.turn(rt);
    const left = st.clocks[side] - (this.clock.now() - st.turn_started_at);
    if (left > 0) {
      this.armFlag(rt, left); // zamanlayıcı erken tetiklendi
      return;
    }
    st.clocks[side] = 0;
    st.turn_started_at = this.clock.now();
    const winner = other(side);
    const result = hasMatingMaterial(rt.chess, winner) ? this.winResult(winner) : "1/2-1/2";
    this.end(rt, result, "timeout");
  }

  private async requestBot(rt: Runtime) {
    const st = rt.state;
    const ply = st.moves.length;
    if (rt.botPly === ply) return; // zaten istendi
    rt.botPly = ply;
    const fen = rt.chess.fen();
    const still = () => st.status === "active" && st.moves.length === ply && rt.botPly === ply;

    let choice: { uci: string; think_ms: number } | null = null;
    for (let attempt = 0; attempt <= this.botRetries; attempt++) {
      try {
        const r = await this.api.botMove(st.game_id, fen, ply);
        if (!still()) return;
        const uci = r.uci.toLowerCase();
        if (this.isLegal(rt.chess, uci)) {
          choice = { uci, think_ms: r.think_ms };
          break;
        }
        this.log(`[game ${st.game_id}] bot-move yasadışı hamle döndü (${r.uci}), deneme ${attempt + 1}`);
      } catch (e) {
        if (!still()) return;
        this.log(`[game ${st.game_id}] bot-move hatası (deneme ${attempt + 1}): ${String(e)}`);
      }
      if (attempt < this.botRetries) {
        await sleep(this.botRetryDelayMs * 2 ** attempt);
        if (!still()) return;
      }
    }
    if (!choice) {
      const legal = rt.chess.moves({ verbose: true });
      if (legal.length === 0) return;
      const m = legal[Math.min(legal.length - 1, Math.floor(this.random() * legal.length))];
      choice = { uci: moveToUci(m), think_ms: 0 };
      this.log(`[game ${st.game_id}] bot-move başarısız; yedek rastgele hamle: ${choice.uci} (ply ${ply})`);
    }

    // Düşünme süresi sıra başından itibaren sayılır ve botun saatinden düşer.
    const side = this.turn(rt);
    const waited = this.clock.now() - st.turn_started_at;
    const budget = Math.max(0, st.clocks[side] - this.botReserveMs);
    const wait = Math.max(0, Math.min(choice.think_ms, budget) - waited);
    const uci = choice.uci;
    rt.botTimer = setTimeout(() => {
      rt.botTimer = undefined;
      if (!still()) return;
      rt.botPly = null;
      if (!this.applyMove(rt, uci, "bot") && st.status === "active") {
        this.log(`[game ${st.game_id}] bot hamlesi uygulanamadı: ${uci}`);
      }
    }, wait);
  }

  private end(rt: Runtime, result: GameResult, reason: EndReason) {
    const st = rt.state;
    if (st.status !== "active") return;
    st.clocks = this.liveClocks(rt); // bitiş anındaki saatleri dondur
    st.status = "ended";
    st.result = result;
    st.reason = reason;
    st.updated_at = this.clock.now();
    this.clearTimers(rt);
    rt.botPly = null;
    this.store.save(st);
    this.log(`[game ${st.game_id}] bitti: ${result} (${reason})`);
    this.broadcast(rt, { t: "end", result, reason });
    this.reportFinish(rt);
  }

  private reportFinish(rt: Runtime) {
    const st = rt.state;
    if (!st.result || !st.reason) return;
    const body = { result: st.result, reason: st.reason, pgn: this.pgn(st) };
    this.enqueue(rt, "finish", async () => {
      await this.api.finish(st.game_id, body);
      st.finish_reported = true;
      this.store.save(st);
    });
  }

  pgn(st: GameState): string {
    const c = new Chess();
    c.setHeader("Event", "Chessdex rating match");
    c.setHeader("Site", "chessdex");
    c.setHeader("Date", new Date(st.created_at).toISOString().slice(0, 10).replace(/-/g, "."));
    c.setHeader("White", st.user_color === "white" ? "User" : "Bot");
    c.setHeader("Black", st.user_color === "black" ? "User" : "Bot");
    const tc = st.time_control;
    c.setHeader("TimeControl", `${Math.round(tc.initial_ms / 1000)}+${Math.round(tc.increment_ms / 1000)}`);
    c.setHeader("GameId", st.game_id);
    for (const m of st.moves) this.tryMove(c, m);
    if (st.result) c.setHeader("Result", st.result);
    if (st.reason) c.setHeader("Termination", st.reason);
    return c.pgn();
  }

  private enqueue(rt: Runtime, what: string, fn: () => Promise<void>) {
    rt.outbox = rt.outbox.then(async () => {
      for (let i = 0; i < this.postAttempts; i++) {
        try {
          await fn();
          return;
        } catch (e) {
          this.log(`[game ${rt.state.game_id}] ${what} gönderilemedi (deneme ${i + 1}): ${String(e)}`);
          if (i < this.postAttempts - 1) await sleep(Math.min(30_000, this.postRetryDelayMs * 2 ** i));
        }
      }
      this.log(`[game ${rt.state.game_id}] ${what} vazgeçildi`);
    });
  }

  private armAbandon(rt: Runtime) {
    if (rt.abandonTimer) clearTimeout(rt.abandonTimer);
    rt.abandonTimer = setTimeout(() => {
      rt.abandonTimer = undefined;
      if (rt.conns.size === 0 && rt.state.status === "active") {
        this.end(rt, this.winResult(other(rt.state.user_color)), "abandoned");
      }
    }, this.abandonMs);
  }

  private clearTurnTimers(rt: Runtime) {
    if (rt.flagTimer) clearTimeout(rt.flagTimer);
    if (rt.botTimer) clearTimeout(rt.botTimer);
    rt.flagTimer = undefined;
    rt.botTimer = undefined;
  }

  private clearTimers(rt: Runtime) {
    this.clearTurnTimers(rt);
    if (rt.abandonTimer) clearTimeout(rt.abandonTimer);
    rt.abandonTimer = undefined;
  }
}
