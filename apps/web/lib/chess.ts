// chess.js yardımcıları: yalnızca istemci tarafı yasal hamle ipuçları ve gösterim içindir.
// Doğruluk ve puanlama her zaman sunucudadır.

import { Chess, type Square } from "chess.js";

export type Key = Square;

export function safeChess(fen?: string): Chess | null {
  try {
    return fen ? new Chess(fen) : new Chess();
  } catch {
    return null;
  }
}

/** chessground `movable.dests` için: kare -> gidebileceği kareler. */
export function destsOf(chess: Chess): Map<Key, Key[]> {
  const dests = new Map<Key, Key[]>();
  for (const m of chess.moves({ verbose: true })) {
    const arr = dests.get(m.from) ?? [];
    if (!arr.includes(m.to)) arr.push(m.to);
    dests.set(m.from, arr);
  }
  return dests;
}

export function isPromotion(chess: Chess, from: string, to: string): boolean {
  return chess
    .moves({ verbose: true })
    .some((m) => m.from === from && m.to === to && !!m.promotion);
}

/** UCI hamlesini uygular; yasadışıysa null döner (konum değişmez). */
export function applyUci(chess: Chess, uci: string) {
  try {
    return chess.move({
      from: uci.slice(0, 2),
      to: uci.slice(2, 4),
      promotion: uci.length > 4 ? uci[4] : undefined,
    });
  } catch {
    return null;
  }
}

/** UCI dizisini verilen konumdan SAN'a çevirir; çevrilemeyenler UCI olarak kalır. */
export function ucisToSan(fen: string | undefined, ucis: string[]): string[] {
  const c = safeChess(fen);
  return ucis.map((u) => {
    if (!c) return u;
    const m = applyUci(c, u);
    return m ? m.san : u;
  });
}

export function uciToSan(fen: string, uci: string): string {
  return ucisToSan(fen, [uci])[0];
}

export function fenAfter(fen: string | undefined, ucis: string[]): string | null {
  const c = safeChess(fen);
  if (!c) return null;
  for (const u of ucis) if (!applyUci(c, u)) return null;
  return c.fen();
}

export function turnColor(fen: string): "white" | "black" {
  return fen.split(" ")[1] === "b" ? "black" : "white";
}

export function lastMoveKeys(uci: string | null | undefined): [Key, Key] | undefined {
  if (!uci || uci.length < 4) return undefined;
  return [uci.slice(0, 2) as Key, uci.slice(2, 4) as Key];
}

export const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
