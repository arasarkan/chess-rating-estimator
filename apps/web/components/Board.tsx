"use client";

import { useEffect, useRef, useState } from "react";
import type { Api } from "chessground/api";
import type { Config } from "chessground/config";
import type { DrawShape } from "chessground/draw";
import type { Dests } from "chessground/types";
import { destsOf, isPromotion, safeChess, turnColor, type Key } from "@/lib/chess";
import { useLang } from "./LangProvider";

export interface Arrow {
  orig: Key;
  dest: Key;
  brush?: "green" | "red" | "blue" | "yellow";
}

interface Props {
  fen: string;
  orientation: "white" | "black";
  /** Kullanıcı hamle yapabilir mi (sıra kendisindeyse). */
  interactive: boolean;
  /** Kullanıcının rengi; verilmezse sıradaki taraf. */
  userColor?: "white" | "black";
  onMove?: (uci: string) => void;
  lastMove?: [Key, Key];
  arrows?: Arrow[];
}

const PROMO_ROLES: { p: "q" | "r" | "b" | "n" }[] = [
  { p: "q" },
  { p: "r" },
  { p: "b" },
  { p: "n" },
];
const PROMO_GLYPH: Record<string, { white: string; black: string }> = {
  q: { white: "♕", black: "♛" },
  r: { white: "♖", black: "♜" },
  b: { white: "♗", black: "♝" },
  n: { white: "♘", black: "♞" },
};

export default function Board({ fen, orientation, interactive, userColor, onMove, lastMove, arrows }: Props) {
  const B = useLang().t.board;
  const el = useRef<HTMLDivElement>(null);
  const cg = useRef<Api | null>(null);
  const onMoveRef = useRef(onMove);
  onMoveRef.current = onMove;
  const fenRef = useRef(fen);
  fenRef.current = fen;
  const [ready, setReady] = useState(false);
  const [promo, setPromo] = useState<{ from: Key; to: Key; color: "white" | "black" } | null>(null);

  // chessground yalnızca tarayıcıda yüklenir.
  useEffect(() => {
    let cancelled = false;
    import("chessground").then(({ Chessground }) => {
      if (cancelled || !el.current) return;
      cg.current = Chessground(el.current, {
        animation: { enabled: true, duration: 200 },
        highlight: { lastMove: true, check: true },
        premovable: { enabled: false },
        drawable: { enabled: true },
        movable: {
          free: false,
          showDests: true,
          events: {
            after: (orig, dest) => {
              const c = safeChess(fenRef.current);
              if (c && isPromotion(c, orig, dest)) {
                setPromo({ from: orig as Key, to: dest as Key, color: turnColor(fenRef.current) });
                return;
              }
              onMoveRef.current?.(orig + dest);
            },
          },
        },
      });
      setReady(true);
    });
    return () => {
      cancelled = true;
      cg.current?.destroy();
      cg.current = null;
    };
  }, []);

  useEffect(() => {
    if (!ready || !cg.current) return;
    const c = safeChess(fen);
    const turn = turnColor(fen);
    const canMove = interactive && !!c && (!userColor || userColor === turn);
    const cfg: Config = {
      fen,
      orientation,
      turnColor: turn,
      check: c?.inCheck() ? turn : false,
      lastMove: lastMove,
      viewOnly: false,
      movable: {
        color: canMove ? turn : undefined,
        dests: canMove && c ? (destsOf(c) as Dests) : new Map(),
      },
      drawable: {
        autoShapes: (arrows ?? []).map((a) => ({ orig: a.orig, dest: a.dest, brush: a.brush ?? "green" }) as DrawShape),
      },
    };
    cg.current.set(cfg);
    setPromo(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, fen, orientation, interactive, userColor, lastMove?.join(""), JSON.stringify(arrows ?? [])]);

  function choosePromo(p: string | null) {
    const pr = promo;
    setPromo(null);
    if (!pr) return;
    if (p === null) {
      cg.current?.set({ fen: fenRef.current });
      // dests'i geri yükle
      const c = safeChess(fenRef.current);
      if (c && cg.current) cg.current.set({ movable: { dests: destsOf(c) as Dests } });
      return;
    }
    onMoveRef.current?.(pr.from + pr.to + p);
  }

  return (
    <div className="board-outer">
      <div className="board-wrap">
        <div ref={el} className="cg-host" />
        {promo && (
          <div className="promo-overlay" role="dialog" aria-label={B.promoAria}>
            <div className="promo-box">
              <div className="promo-title">{B.promo}</div>
              <div className="promo-buttons">
                {PROMO_ROLES.map((r) => (
                  <button key={r.p} className="promo-btn" title={B[r.p]} onClick={() => choosePromo(r.p)}>
                    {PROMO_GLYPH[r.p][promo.color]}
                  </button>
                ))}
              </div>
              <button className="btn btn-ghost btn-small" onClick={() => choosePromo(null)}>
                {B.cancel}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
