import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { Chess } from "chess.js";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiClient, type FetchLike } from "../src/api.js";
import { GameServer, moveToUci } from "../src/game.js";
import { MemoryGameStore, SnapshotGameStore, type GameStore } from "../src/store.js";
import type { Conn, ServerMsg } from "../src/types.js";

const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

interface Call {
  path: string;
  body: any;
}

type BotReply = { uci: string; think_ms: number } | "fail";

class FakeConn implements Conn {
  msgs: ServerMsg[] = [];
  send(m: ServerMsg) {
    this.msgs.push(m);
  }
  of<T extends ServerMsg["t"]>(t: T): Extract<ServerMsg, { t: T }>[] {
    return this.msgs.filter((m) => m.t === t) as Extract<ServerMsg, { t: T }>[];
  }
  last<T extends ServerMsg["t"]>(t: T): Extract<ServerMsg, { t: T }> | undefined {
    const xs = this.of(t);
    return xs[xs.length - 1];
  }
}

function firstLegal(fen: string): string {
  return moveToUci(new Chess(fen).moves({ verbose: true })[0]);
}

function setup(
  opts: {
    bot?: (body: { fen: string; ply: number }) => BotReply;
    userMoveFails?: number;
    store?: GameStore;
  } = {},
) {
  const calls: Call[] = [];
  let userMoveFails = opts.userMoveFails ?? 0;
  const bot = opts.bot ?? ((b) => ({ uci: firstLegal(b.fen), think_ms: 2000 }));
  const fetchFn: FetchLike = async (url, init) => {
    const p = new URL(url).pathname;
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ path: p, body });
    const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data });
    const fail = { ok: false, status: 500, json: async () => ({ detail: "boom" }) };
    if (p.endsWith("/bot-move")) {
      const r = bot(body);
      return r === "fail" ? fail : ok(r);
    }
    if (p.endsWith("/user-move")) {
      if (userMoveFails > 0) {
        userMoveFails--;
        return fail;
      }
      return ok({ ok: true });
    }
    if (p.endsWith("/finish")) return ok({ ok: true });
    return { ok: false, status: 404, json: async () => ({}) };
  };
  const logs: string[] = [];
  const server = new GameServer({
    api: new ApiClient("http://api.test", fetchFn),
    store: opts.store ?? new MemoryGameStore(),
    clock: { now: () => Date.now() },
    random: () => 0,
    log: (m) => logs.push(m),
    postRetryDelayMs: 100,
  });
  const conn = new FakeConn();
  const join = (c: Conn, color: "white" | "black" = "white", gid = "g1") =>
    server.handleMessage(
      c,
      JSON.stringify({
        t: "join",
        session_id: "s1",
        game_id: gid,
        user_color: color,
        time_control: { initial_ms: 600000, increment_ms: 5000 },
      }),
    );
  const move = (c: Conn, uci: string, ply?: number) =>
    server.handleMessage(c, JSON.stringify({ t: "move", uci, ...(ply !== undefined ? { ply } : {}) }));
  const callsTo = (suffix: string) => calls.filter((c) => c.path.endsWith(suffix));
  return { server, conn, calls, callsTo, join, move, logs };
}

/** Senaryolu bot: verilen hamleleri sırayla oynar. */
function scriptedBot(moves: string[], think_ms = 1000) {
  let i = 0;
  return () => ({ uci: moves[i++], think_ms });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-01-01T00:00:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
});

describe("join", () => {
  it("ilk join oyunu kurar ve state gönderir", () => {
    const { server, conn, join } = setup();
    join(conn, "white");
    const st = conn.last("state")!;
    expect(st).toMatchObject({
      fen: START_FEN,
      ply: 0,
      turn: "white",
      user_color: "white",
      status: "active",
      moves: [],
      clocks: { white: 600000, black: 600000 },
    });
    server.shutdown();
  });

  it("bilinmeyen oyun için user_color yoksa hata döner", () => {
    const { server, conn } = setup();
    server.handleMessage(conn, JSON.stringify({ t: "join", session_id: "s1", game_id: "gx" }));
    expect(conn.last("error")).toBeDefined();
    expect(server.getState("gx")).toBeUndefined();
  });

  it("farklı session_id ile join reddedilir", () => {
    const { server, conn, join } = setup();
    join(conn, "white");
    const c2 = new FakeConn();
    server.handleMessage(c2, JSON.stringify({ t: "join", session_id: "other", game_id: "g1" }));
    expect(c2.last("error")).toBeDefined();
    server.shutdown();
  });
});

describe("hamle doğrulama", () => {
  it("yasal kullanıcı hamlesi uygulanır ve user-move gönderilir", async () => {
    const { server, conn, join, move, callsTo } = setup();
    join(conn, "white");
    move(conn, "e2e4", 0);
    const mv = conn.last("move")!;
    expect(mv.uci).toBe("e2e4");
    expect(mv.by).toBe("user");
    await vi.advanceTimersByTimeAsync(0);
    const um = callsTo("/games/g1/user-move");
    expect(um).toHaveLength(1);
    expect(um[0].body).toEqual({
      ply: 0,
      fen_before: START_FEN,
      uci: "e2e4",
      spent_ms: 0,
      clock_ms: 600000,
      focus_lost: false,
    });
    server.shutdown();
  });

  it("istemcinin focus_lost işareti user-move'a iletilir; yalnızca true kabul edilir", async () => {
    const { server, conn, join, callsTo } = setup({ bot: scriptedBot(["e7e5", "b8c6"], 0) });
    join(conn, "white");
    server.handleMessage(conn, JSON.stringify({ t: "move", uci: "e2e4", ply: 0, focus_lost: true }));
    await vi.advanceTimersByTimeAsync(10);
    server.handleMessage(conn, JSON.stringify({ t: "move", uci: "g1f3", ply: 2, focus_lost: "yes" }));
    await vi.advanceTimersByTimeAsync(10);
    const um = callsTo("/games/g1/user-move").map((c) => (c.body as { focus_lost: boolean }).focus_lost);
    expect(um).toEqual([true, false]);
    server.shutdown();
  });

  it("yasadışı hamle, sıra dışı hamle ve yanlış ply reddedilir", () => {
    const { server, conn, join, move } = setup();
    join(conn, "white");
    move(conn, "e2e5");
    expect(conn.last("illegal")).toEqual({ t: "illegal", uci: "e2e5" });
    move(conn, "zz");
    expect(conn.last("illegal")).toEqual({ t: "illegal", uci: "zz" });
    move(conn, "e2e4", 3);
    expect(conn.last("illegal")).toEqual({ t: "illegal", uci: "e2e4" });
    expect(conn.of("move")).toHaveLength(0);

    const b = setup();
    b.join(b.conn, "black");
    b.move(b.conn, "e7e5");
    expect(b.conn.last("illegal")).toEqual({ t: "illegal", uci: "e7e5" });
    server.shutdown();
    b.server.shutdown();
  });

  it("terfi UCI ile işlenir (terfi harfi zorunlu)", async () => {
    const { server, conn, join, move } = setup({
      bot: scriptedBot(["h7h6", "h6h5", "g7g6", "g6g5"], 0),
    });
    join(conn, "white");
    for (const m of ["a2a4", "a4a5", "a5a6", "a6b7"]) {
      move(conn, m);
      await vi.advanceTimersByTimeAsync(10);
    }
    move(conn, "b7a8");
    expect(conn.last("illegal")?.uci).toBe("b7a8");
    move(conn, "b7a8q");
    const mv = conn.last("move")!;
    expect(mv.uci).toBe("b7a8q");
    expect(mv.fen.startsWith("Qnbqkbnr")).toBe(true);
    server.shutdown();
  });
});

describe("saat", () => {
  it("geçen süre düşülür, artış eklenir; bot düşünme süresi botun saatinden düşer", async () => {
    const { server, conn, join, move, callsTo } = setup({
      bot: () => ({ uci: "e7e5", think_ms: 2000 }),
    });
    join(conn, "white");
    await vi.advanceTimersByTimeAsync(3000);
    move(conn, "e2e4");
    expect(conn.last("move")!.clocks).toEqual({ white: 602000, black: 600000 });
    await vi.advanceTimersByTimeAsync(0);
    expect(callsTo("/user-move")[0].body).toMatchObject({ spent_ms: 3000, clock_ms: 597000 });

    // Bot sırası: think_ms dolmadan hamle gelmez.
    await vi.advanceTimersByTimeAsync(1999);
    expect(conn.of("move")).toHaveLength(1);
    // Düşünürken botun saati işler.
    conn.msgs = [];
    await vi.advanceTimersByTimeAsync(1);
    const botMv = conn.last("move")!;
    expect(botMv.by).toBe("bot");
    expect(botMv.uci).toBe("e7e5");
    expect(botMv.clocks).toEqual({ white: 602000, black: 603000 });
    server.shutdown();
  });

  it("süre biterse kullanıcı kaybeder (timeout) ve finish gönderilir", async () => {
    const { server, conn, join, callsTo, move } = setup();
    join(conn, "white");
    await vi.advanceTimersByTimeAsync(599_999);
    expect(conn.last("end")).toBeUndefined();
    await vi.advanceTimersByTimeAsync(1);
    expect(conn.last("end")).toEqual({ t: "end", result: "0-1", reason: "timeout" });
    move(conn, "e2e4");
    expect(conn.last("illegal")).toBeDefined();
    await server.idle();
    const fin = callsTo("/games/g1/finish");
    expect(fin).toHaveLength(1);
    expect(fin[0].body).toMatchObject({ result: "0-1", reason: "timeout" });
    expect(fin[0].body.pgn).toContain('[Termination "timeout"]');
  });
});

describe("bot", () => {
  it("bot beyazsa ilk hamleyi ister, think_ms sonra uygular", async () => {
    const { server, conn, join, callsTo } = setup({ bot: () => ({ uci: "d2d4", think_ms: 1500 }) });
    join(conn, "black");
    await vi.advanceTimersByTimeAsync(0);
    const bm = callsTo("/games/g1/bot-move");
    expect(bm).toHaveLength(1);
    expect(bm[0].body).toEqual({ fen: START_FEN, ply: 0 });
    await vi.advanceTimersByTimeAsync(1499);
    expect(conn.of("move")).toHaveLength(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(conn.last("move")).toMatchObject({ uci: "d2d4", by: "bot", clocks: { white: 603500, black: 600000 } });
    expect(callsTo("/user-move")).toHaveLength(0);
    server.shutdown();
  });

  it("API başarısızsa 3 kez yeniden dener, sonra rastgele yasal hamle oynar", async () => {
    const { server, conn, join, callsTo, logs } = setup({ bot: () => "fail" });
    join(conn, "black");
    await vi.advanceTimersByTimeAsync(250 + 500 + 1000 + 10);
    expect(callsTo("/bot-move")).toHaveLength(4);
    const mv = conn.last("move")!;
    expect(mv.by).toBe("bot");
    const legal = new Chess().moves({ verbose: true }).map(moveToUci);
    expect(legal).toContain(mv.uci);
    expect(logs.some((l) => l.includes("yedek rastgele hamle"))).toBe(true);
    server.shutdown();
  });

  it("bot yasadışı hamle döndürürse yine yedek hamleye düşer", async () => {
    const { server, conn, join } = setup({ bot: () => ({ uci: "e2e5", think_ms: 0 }) });
    join(conn, "black");
    await vi.advanceTimersByTimeAsync(5000);
    expect(conn.last("move")?.by).toBe("bot");
    server.shutdown();
  });
});

describe("bitiş", () => {
  it("mat oyunu bitirir ve finish (sonuç + PGN) gönderilir", async () => {
    const { server, conn, join, move, callsTo } = setup({ bot: scriptedBot(["f2f3", "g2g4"], 500) });
    join(conn, "black");
    await vi.advanceTimersByTimeAsync(500);
    move(conn, "e7e5", 1);
    await vi.advanceTimersByTimeAsync(500);
    move(conn, "d8h4", 3);
    expect(conn.last("end")).toEqual({ t: "end", result: "0-1", reason: "checkmate" });
    await server.idle();
    const fin = callsTo("/games/g1/finish");
    expect(fin).toHaveLength(1);
    expect(fin[0].body.result).toBe("0-1");
    expect(fin[0].body.reason).toBe("checkmate");
    expect(fin[0].body.pgn).toContain("Qh4#");
    expect(fin[0].body.pgn).toContain('[Result "0-1"]');
    // user-move hamle sırasıyla, finish'ten önce gönderilir.
    const order = callsTo("").filter((c) => !c.path.endsWith("/bot-move")).map((c) => c.path.split("/").pop());
    expect(order).toEqual(["user-move", "user-move", "finish"]);
    expect(server.getState("g1")!.finish_reported).toBe(true);
  });

  it("terk etme (resign) kullanıcıyı kaybettirir", async () => {
    const { server, conn, join, callsTo } = setup();
    join(conn, "white");
    server.handleMessage(conn, JSON.stringify({ t: "resign" }));
    expect(conn.last("end")).toEqual({ t: "end", result: "0-1", reason: "resign" });
    await server.idle();
    expect(callsTo("/finish")[0].body.reason).toBe("resign");
  });

  it("user-move hatası oyunu bloklamaz, yeniden denenir", async () => {
    const { server, conn, join, move, callsTo } = setup({ userMoveFails: 2, bot: () => ({ uci: "e7e5", think_ms: 0 }) });
    join(conn, "white");
    move(conn, "e2e4");
    await vi.advanceTimersByTimeAsync(10);
    expect(conn.last("move")?.by).toBe("bot"); // oyun devam etti
    await vi.advanceTimersByTimeAsync(1000);
    expect(callsTo("/user-move")).toHaveLength(3);
    server.shutdown();
  });
});

describe("kopma", () => {
  it("60 sn içinde yeniden join kaldığı yerden sürdürür (saat işlemeye devam eder)", async () => {
    const { server, conn, join, move } = setup({ bot: () => ({ uci: "e7e5", think_ms: 1000 }) });
    join(conn, "white");
    move(conn, "e2e4");
    await vi.advanceTimersByTimeAsync(1000); // bot oynadı
    server.handleClose(conn);
    await vi.advanceTimersByTimeAsync(30_000);
    const c2 = new FakeConn();
    join(c2, "white");
    const st = c2.last("state")!;
    expect(st.status).toBe("active");
    expect(st.moves).toEqual(["e2e4", "e7e5"]);
    expect(st.ply).toBe(2);
    expect(st.clocks.white).toBe(605000 - 30_000);
    // Terk sayacı iptal edildi.
    await vi.advanceTimersByTimeAsync(40_000);
    expect(c2.last("end")).toBeUndefined();
    move(c2, "g1f3", 2);
    expect(c2.last("move")?.uci).toBe("g1f3");
    server.shutdown();
  });

  it("60 sn'den uzun kopma kullanıcıyı kaybettirir (abandoned)", async () => {
    const { server, conn, join, callsTo } = setup();
    join(conn, "black");
    await vi.advanceTimersByTimeAsync(3000); // bot oynadı, sıra kullanıcıda
    server.handleClose(conn);
    await vi.advanceTimersByTimeAsync(59_999);
    expect(server.getState("g1")!.status).toBe("active");
    await vi.advanceTimersByTimeAsync(1);
    const st = server.getState("g1")!;
    expect(st.status).toBe("ended");
    expect(st.result).toBe("1-0");
    expect(st.reason).toBe("abandoned");
    await server.idle();
    expect(callsTo("/finish")[0].body).toMatchObject({ result: "1-0", reason: "abandoned" });
    // Sonradan gelen join bitmiş oyunu görür.
    const c2 = new FakeConn();
    join(c2, "black");
    expect(c2.last("state")?.status).toBe("ended");
    expect(c2.last("end")).toEqual({ t: "end", result: "1-0", reason: "abandoned" });
  });
});

describe("kalıcılık", () => {
  it("her hamlede JSON anlık görüntüsü yazılır ve açılışta yüklenir", async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "chessdex-game-"));
    try {
      const a = setup({ store: new SnapshotGameStore(dir, () => {}), bot: () => ({ uci: "e7e5", think_ms: 0 }) });
      a.join(a.conn, "white");
      a.move(a.conn, "e2e4");
      await vi.advanceTimersByTimeAsync(10);
      const snap = JSON.parse(fs.readFileSync(path.join(dir, "g1.json"), "utf8"));
      expect(snap.moves).toEqual(["e2e4", "e7e5"]);
      a.server.shutdown();

      const b = setup({ store: new SnapshotGameStore(dir, () => {}) });
      const st = b.server.getState("g1")!;
      expect(st.moves).toEqual(["e2e4", "e7e5"]);
      expect(st.status).toBe("active");
      const c = new FakeConn();
      b.join(c, "white");
      expect(c.last("state")).toMatchObject({ ply: 2, turn: "white" });
      b.move(c, "d2d4", 2);
      expect(c.last("move")?.uci).toBe("d2d4");
      b.server.shutdown();
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
