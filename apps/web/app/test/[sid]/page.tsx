"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Board, { type Arrow } from "@/components/Board";
import EstimateBand from "@/components/EstimateBand";
import SessionNotFound from "@/components/SessionNotFound";
import { useLang } from "@/components/LangProvider";
import { api, errorMessage, isNotFound, local } from "@/lib/api";
import { fenAfter, lastMoveKeys, ucisToSan, uciToSan, type Key } from "@/lib/chess";
import { isContinue, type Choice, type Estimate, type FinalResponse, type Item, type ResponseRequest } from "@/lib/types";

type Phase = "loading" | "answering" | "sending" | "feedback" | "error";

// API tür adlarının eski/alternatif yazımları
const KIND_ALIAS: Record<string, string> = { tactic: "tactics", defensive: "defense" };

const FEEDBACK_MS = 2800;

function choiceUci(c: Choice): string {
  return typeof c === "string" ? c : c.uci;
}
function fmtTime(ms: number) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export default function TestPage() {
  const { sid } = useParams<{ sid: string }>();
  const router = useRouter();
  const { t } = useLang();
  const T = t.test;

  const [phase, setPhase] = useState<Phase>("loading");
  const [item, setItem] = useState<Item | null>(null);
  const [fen, setFen] = useState<string>("");
  const [moves, setMoves] = useState<string[]>([]);
  const [result, setResult] = useState<FinalResponse | null>(null);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [now, setNow] = useState(0);
  const startRef = useRef(0);
  const retryRef = useRef<(() => void) | null>(null);
  const advanceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const started = useRef(false);

  const mode = useMemo(() => (sid ? local.getMode(sid) : null) ?? "full", [sid]);

  const finish = useCallback(() => {
    router.push(mode === "full" ? `/play/${encodeURIComponent(sid)}` : `/report/${encodeURIComponent(sid)}`);
  }, [mode, router, sid]);

  const loadNext = useCallback(async () => {
    setPhase("loading");
    setErr(null);
    setResult(null);
    try {
      const res = await api.nextItem(sid);
      if (res.done) {
        finish();
        return;
      }
      setItem(res.item);
      setFen(res.item.fen);
      setMoves([]);
      // sunucu bu senaryonun ilk gösteriminden beri geçen süreyi verir (yenilemede sayaç sıfırlanmaz)
      startRef.current = performance.now() - (res.item.elapsed_ms ?? 0);
      setNow(performance.now());
      setPhase("answering");
    } catch (e) {
      if (isNotFound(e)) {
        setNotFound(true);
        return;
      }
      setErr(errorMessage(e));
      retryRef.current = loadNext;
      setPhase("error");
    }
  }, [sid, finish]);

  useEffect(() => {
    if (started.current || !sid) return;
    started.current = true;
    loadNext();
  }, [sid, loadNext]);

  useEffect(() => {
    if (phase !== "answering" && phase !== "sending") return;
    const t = setInterval(() => setNow(performance.now()), 250);
    return () => clearInterval(t);
  }, [phase]);

  useEffect(() => () => {
    if (advanceTimer.current) clearTimeout(advanceTimer.current);
  }, []);

  const advance = useCallback(
    (r: FinalResponse | null) => {
      if (advanceTimer.current) clearTimeout(advanceTimer.current);
      advanceTimer.current = null;
      if (r?.done) finish();
      else loadNext();
    },
    [finish, loadNext],
  );

  const send = useCallback(
    async (req: ResponseRequest, fenNow: string, movesNow: string[]) => {
      setPhase("sending");
      setErr(null);
      try {
        const res = await api.postResponse(sid, req);
        if (isContinue(res)) {
          if (res.reply) {
            const reply = res.reply;
            await new Promise((r) => setTimeout(r, 350));
            const f2 = fenAfter(fenNow, [reply]);
            if (f2) setFen(f2);
            setMoves([...movesNow, reply]);
          }
          setPhase("answering");
          return;
        }
        setResult(res);
        setEstimate(res.estimate);
        setPhase("feedback");
        advanceTimer.current = setTimeout(() => advance(res), FEEDBACK_MS);
      } catch (e) {
        if (isNotFound(e)) {
          setNotFound(true);
          return;
        }
        setErr(errorMessage(e));
        retryRef.current = () => send(req, fenNow, movesNow);
        setPhase("error");
      }
    },
    [sid, advance],
  );

  const onMove = useCallback(
    (uci: string) => {
      if (phase !== "answering" || !item) return;
      const f = fenAfter(fen, [uci]);
      if (!f) return;
      const m2 = [...moves, uci];
      setFen(f);
      setMoves(m2);
      const partial = m2.length < item.n_moves;
      const req: ResponseRequest = {
        token: item.token,
        moves: m2,
        elapsed_ms: Math.round(performance.now() - startRef.current),
      };
      if (partial) req.partial = true;
      send(req, f, m2);
    },
    [phase, item, fen, moves, send],
  );

  const onChoice = useCallback(
    (uci: string) => {
      if (phase !== "answering" || !item) return;
      setMoves([uci]);
      send({ token: item.token, moves: [uci], elapsed_ms: Math.round(performance.now() - startRef.current) }, fen, [uci]);
    },
    [phase, item, fen, send],
  );

  const hasChoices = !!item?.choices && item.choices.length > 0;
  const kind = item ? KIND_ALIAS[item.kind] ?? item.kind : null;

  // Geri bildirimde: çözümün ilk hamlesi yeşil ok, yanlış ilk hamle kırmızı ok.
  const arrows: Arrow[] = useMemo(() => {
    if (phase !== "feedback" || !result || !item) return [];
    const out: Arrow[] = [];
    const s = lastMoveKeys(result.solution[0]);
    if (s) out.push({ orig: s[0], dest: s[1], brush: "green" });
    const u = lastMoveKeys(moves[0]);
    if (!result.correct && u && moves[0] !== result.solution[0]) out.push({ orig: u[0], dest: u[1], brush: "red" });
    return out;
  }, [phase, result, item, moves]);

  const boardFen = phase === "feedback" && item ? item.fen : fen;
  const lastMove: [Key, Key] | undefined = phase === "feedback" ? undefined : lastMoveKeys(moves[moves.length - 1]);
  // sayfa yenilenince tahmin henüz yoktur: cevaplanan sayıyı sunucunun verdiği sıra numarasından al
  const nItems = estimate?.n_items ?? (item?.index ? item.index - 1 : 0);
  // senaryo sayısı ya da (kısa modda) zaman bütçesi — hangisi önce dolarsa
  const byCount = nItems / (item?.max_items ?? 20);
  const byTime = item?.time_budget_ms ? (item.spent_ms ?? 0) / item.time_budget_ms : 0;
  const progress = Math.min(1, Math.max(byCount, byTime));
  const elapsed = Math.max(0, now - startRef.current);

  if (!sid) return null;

  if (notFound) return <SessionNotFound />;

  return (
    <div className="test-layout">
      <div>
        {item && fen ? (
          <Board
            fen={boardFen}
            orientation={item.orientation}
            interactive={phase === "answering" && !hasChoices}
            onMove={onMove}
            lastMove={lastMove}
            arrows={arrows}
          />
        ) : (
          <div className="card muted">{T.loading}</div>
        )}
      </div>

      <div className="side">
        <div className="card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <span className="muted small">
              {T.item} {phase === "feedback" ? nItems : nItems + 1}
              {item && kind ? ` · ${t.kinds[kind] ?? kind}` : ""}
            </span>
            <span className="timer">{phase === "feedback" ? "—" : fmtTime(elapsed)}</span>
          </div>
          <div className="progress" style={{ marginTop: 8 }}>
            <div style={{ width: `${Math.round(progress * 100)}%` }} />
          </div>
          <p className="prompt">{kind ? t.prompts[kind] ?? item?.prompt : ""}</p>
          {item && (
            <p className="muted small">
              {T.youPlay(item.orientation === "white" ? T.white : T.black)}
              {item.n_moves > 1 && !hasChoices && T.solutionLen(Math.ceil(item.n_moves / 2))}
              {!hasChoices && T.howTo}
            </p>
          )}

          {hasChoices && item && (
            <div className="choices">
              {item.choices!.map((c) => {
                const u = choiceUci(c);
                const label = typeof c !== "string" && c.label ? c.label : uciToSan(item.fen, u);
                return (
                  <button key={u} className="choice" disabled={phase !== "answering"} onClick={() => onChoice(u)}>
                    {label}
                  </button>
                );
              })}
            </div>
          )}

          {phase === "sending" && <p className="muted small">{T.checking}</p>}

          {phase === "feedback" && result && item && (
            <div className={`feedback ${result.correct ? "ok" : "bad"}`}>
              {result.correct ? T.correct : result.score > 0 ? T.partial : T.wrong}
              <div className="sol">
                {T.solution}: {ucisToSan(item.fen, result.solution).join(" ") || "—"}
              </div>
              <button className="btn btn-small" style={{ marginTop: 8 }} onClick={() => advance(result)}>
                {result.done ? T.cont : T.next}
              </button>
            </div>
          )}

          {phase === "error" && (
            <div className="error">
              {err}
              <div style={{ marginTop: 8 }}>
                <button className="btn btn-small" onClick={() => retryRef.current?.()}>
                  {T.retry}
                </button>
              </div>
            </div>
          )}
        </div>

        {estimate && (
          <div className="card">
            <div className="muted small" style={{ marginBottom: 6 }}>
              {T.estimate}
            </div>
            <EstimateBand est={estimate} compact />
            <p className="muted small" style={{ marginBottom: 0 }}>
              {T.estimateNote}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
