// Yalnızca geliştirme: NEXT_PUBLIC_MOCK=1 iken tarayıcı içinde çalışan sahte ölçüm servisi.
// Gerçek ölçüm modelini taklit ETMEZ; sadece arayüzün uçtan uca tıklanabilmesi içindir.

import type {
  CreateGameResponse,
  CreateSessionRequest,
  CreateSessionResponse,
  Estimate,
  Health,
  Item,
  NextItemResponse,
  Report,
  ResponseRequest,
  ResponseResult,
} from "./types";

interface MockPuzzle {
  item: Omit<Item, "token">;
  solution: string[];
  /** Çoktan seçmeli: şık -> 0..3 puan */
  graded?: Record<string, number>;
}

const PUZZLES: MockPuzzle[] = [
  {
    item: {
      fen: "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1",
      orientation: "white",
      kind: "tactic",
      prompt: "Beyaz oynar ve tek hamlede mat eder.",
      n_moves: 1,
    },
    solution: ["d1d8"],
  },
  {
    item: {
      fen: "3r1rk1/5ppp/8/8/8/8/3R1PPP/3R2K1 w - - 0 1",
      orientation: "white",
      kind: "tactic",
      prompt: "Beyaz oynar ve kazanır (2 hamle).",
      n_moves: 3,
    },
    solution: ["d2d8", "f8d8", "d1d8"],
  },
  {
    item: {
      fen: "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
      orientation: "white",
      kind: "positional",
      prompt: "Bu pozisyonda en iyi plan hangisi?",
      n_moves: 1,
      choices: ["f1b5", "f1c4", "d2d4", "h2h3"],
    },
    solution: ["f1b5"],
    graded: { f1b5: 3, f1c4: 3, d2d4: 2, h2h3: 0 },
  },
  {
    item: {
      fen: "3r2k1/5ppp/8/8/8/8/5PPP/6K1 b - - 0 1",
      orientation: "black",
      kind: "tactic",
      prompt: "Siyah oynar ve tek hamlede mat eder.",
      n_moves: 1,
    },
    solution: ["d8d1"],
  },
  {
    item: {
      fen: "8/4P3/8/8/8/k7/8/K7 w - - 0 1",
      orientation: "white",
      kind: "endgame",
      prompt: "Beyaz oynar: en iyi hamleyi bulun.",
      n_moves: 1,
    },
    solution: ["e7e8q"],
  },
];

interface MockSession {
  mode: "full" | "short";
  idx: number;
  estimate: Estimate;
  current: { token: string; puzzle: number } | null;
}

const KEY = "chessdex:mock";

function load(): Record<string, MockSession> {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || "{}");
  } catch {
    return {};
  }
}
function save(db: Record<string, MockSession>) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(db));
  } catch {
    /* yoksay */
  }
}
function rid(): string {
  return Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}
function delay<T>(v: T, ms = 250): Promise<T> {
  return new Promise((r) => setTimeout(() => r(v), ms));
}
function notFound(): never {
  throw new Error("Oturum bulunamadı (mock)");
}

function updateEstimate(e: Estimate, score01: number): Estimate {
  const n = e.n_items + 1;
  const step = 260 / Math.sqrt(n);
  const median = Math.round(Math.min(2900, Math.max(500, e.median + (score01 - 0.5) * 2 * step)));
  const half = Math.max(110, ((e.hi90 - e.lo90) / 2) * 0.85);
  return {
    median,
    lo90: Math.round(median - half),
    hi90: Math.round(median + half),
    sd: Math.round(half / 1.645),
    n_items: n,
    stage: "items",
  };
}

export const mockApi = {
  async health(): Promise<Health> {
    return delay({ ok: true, human_model: "mock", stockfish: false });
  },

  async createSession(req: CreateSessionRequest): Promise<CreateSessionResponse> {
    const db = load();
    const sid = "mock-" + rid();
    const estimate: Estimate = { median: 1500, lo90: 900, hi90: 2100, sd: 365, n_items: 0, stage: "prior" };
    db[sid] = { mode: req.mode, idx: 0, estimate, current: null };
    save(db);
    return delay({ session_id: sid, estimate });
  },

  async nextItem(sid: string): Promise<NextItemResponse> {
    const db = load();
    const s = db[sid] ?? notFound();
    if (s.idx >= PUZZLES.length) return delay({ done: true as const });
    const token = rid();
    s.current = { token, puzzle: s.idx };
    save(db);
    return delay({ done: false as const, item: { token, ...PUZZLES[s.idx].item } });
  },

  async postResponse(sid: string, req: ResponseRequest): Promise<ResponseResult> {
    const db = load();
    const s = db[sid] ?? notFound();
    if (!s.current || s.current.token !== req.token) throw new Error("Geçersiz token (mock)");
    const p = PUZZLES[s.current.puzzle];
    const sol = p.solution;
    let correct: boolean;
    let score: number;
    if (p.graded) {
      score = p.graded[req.moves[0]] ?? 0;
      correct = score >= 3;
    } else {
      const prefixOk = req.moves.every((m, i) => sol[i] === m);
      if (req.partial && prefixOk && req.moves.length < sol.length) {
        return delay({ continue: true as const, reply: sol[req.moves.length] ?? null }, 150);
      }
      correct = prefixOk && req.moves.length >= sol.length;
      score = correct ? 1 : 0;
    }
    const s01 = p.graded ? score / 3 : score;
    s.estimate = updateEstimate(s.estimate, s01);
    s.idx += 1;
    s.current = null;
    const done = s.idx >= PUZZLES.length;
    save(db);
    return delay({ correct, score, solution: sol, estimate: s.estimate, done });
  },

  async createGame(sid: string): Promise<CreateGameResponse> {
    if (!load()[sid]) notFound();
    return delay({
      game_id: "mockgame-" + rid(),
      bot_level: 1500,
      user_color: "white" as const,
      time_control: { initial_ms: 600000, increment_ms: 5000 },
      seed: 1,
    });
  },

  async linkLichess(): Promise<{ authorize_url: string }> {
    throw new Error("Mock modunda Lichess bağlantısı yok.");
  },

  async chesscomStart(): Promise<{ code: string; expires_in_s: number; instructions: string }> {
    throw new Error("Mock modunda Chess.com doğrulaması yok.");
  },

  async chesscomVerify(): Promise<{ external: never }> {
    throw new Error("Mock modunda Chess.com doğrulaması yok.");
  },

  async report(sid: string): Promise<Report> {
    const s = load()[sid] ?? notFound();
    const e = s.estimate;
    const shift = (d: number, widen: number) => ({
      median: e.median + d,
      lo90: Math.round(e.lo90 + d - widen),
      hi90: Math.round(e.hi90 + d + widen),
    });
    return delay({
      estimate: { ...e, stage: "final" },
      scales: {
        lichess: shift(0, 0),
        chesscom: shift(-250, 40),
        fide: shift(-350, 90),
      },
      subskills: {
        tactics: shift(60, 80),
        endgame: shift(-40, 120),
        positional: shift(-20, 100),
        defense: null,
        time: null,
      },
      critical_moments: [
        { ply: 23, played: "g2g4", eval_loss: 0.21, typical: "f1e1" },
        { ply: 31, played: "d4d5", eval_loss: 0.12, typical: "c2c3" },
        { ply: 44, played: "h1h2", eval_loss: 0.08, typical: null },
      ],
      flags: s.mode === "short" ? ["no_game"] : ["short_game"],
      model_version: { measure: "mock-0", human_model: "mock", bank: "mock" },
    });
  },
};
