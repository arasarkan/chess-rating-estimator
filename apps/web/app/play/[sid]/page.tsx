"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import Board from "@/components/Board";
import { useLang } from "@/components/LangProvider";
import SessionNotFound from "@/components/SessionNotFound";
import { api, errorMessage, isNotFound, local, MOCK, WS_URL } from "@/lib/api";
import { fenAfter, lastMoveKeys, START_FEN, turnColor, ucisToSan } from "@/lib/chess";
import type { ClientMsg, Clocks, Color, CreateGameResponse, ServerMsg } from "@/lib/types";

type Conn = "idle" | "connecting" | "open" | "closed";

const ENDED_STATUSES = new Set(["ended", "finished", "over", "aborted", "done"]);

function fmtClock(ms: number) {
  const t = Math.max(0, ms);
  const s = Math.floor(t / 1000);
  const m = Math.floor(s / 60);
  const ss = String(s % 60).padStart(2, "0");
  if (t < 10_000) return `${m}:${ss}.${Math.floor((t % 1000) / 100)}`;
  return `${m}:${ss}`;
}

export default function PlayPage() {
  const { t } = useLang();
  const P = t.play;
  // WS mesaj işleyicisi dil değişince yeniden kurulmasın diye metinler ref üzerinden okunur
  const msgText = useRef(P);
  msgText.current = P;
  const { sid } = useParams<{ sid: string }>();
  const router = useRouter();

  const [game, setGame] = useState<CreateGameResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [conn, setConn] = useState<Conn>("idle");
  const [fen, setFen] = useState(START_FEN);
  const [moves, setMoves] = useState<string[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [clocks, setClocks] = useState<Clocks | null>(null);
  const [clockAt, setClockAt] = useState(0);
  const [status, setStatus] = useState("waiting");
  const [userColor, setUserColor] = useState<Color>("white");
  const [ended, setEnded] = useState<{ result: string; reason: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [synced, setSynced] = useState(false);
  const [now, setNow] = useState(0);

  const wsRef = useRef<WebSocket | null>(null);
  const endedRef = useRef(false);
  const attemptRef = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const creating = useRef(false);

  // 1) Oyunu oluştur (ya da bu sekmede daha önce oluşturulanı kullan).
  useEffect(() => {
    if (MOCK || !sid || creating.current) return;
    creating.current = true;
    const saved = local.getGame(sid);
    if (saved) {
      setGame(saved);
      setUserColor(saved.user_color);
      return;
    }
    api
      .createGame(sid)
      .then((g) => {
        local.setGame(sid, g);
        setGame(g);
        setUserColor(g.user_color);
        setClocks({ white: g.time_control.initial_ms, black: g.time_control.initial_ms });
        setClockAt(performance.now());
      })
      .catch((e) => {
        if (isNotFound(e)) setNotFound(true);
        else setErr(errorMessage(e));
        creating.current = false;
      });
  }, [sid]);

  const goReport = useCallback(() => router.push(`/report/${encodeURIComponent(sid)}`), [router, sid]);

  const onServerMsg = useCallback(
    (msg: ServerMsg) => {
      switch (msg.t) {
        case "state": {
          setFen(msg.fen);
          setMoves(msg.moves ?? []);
          setClocks(msg.clocks);
          setClockAt(performance.now());
          setStatus(msg.status);
          if (msg.user_color) setUserColor(msg.user_color);
          setPending(null);
          setSynced(true);
          break;
        }
        case "move": {
          setFen(msg.fen);
          setMoves((m) => [...m, msg.uci]);
          if (msg.clocks) {
            setClocks(msg.clocks);
            setClockAt(performance.now());
          }
          if (msg.by === "user") setPending(null);
          setStatus((s) => (s === "waiting" ? "active" : s));
          break;
        }
        case "illegal": {
          setPending(null);
          setNotice(msgText.current.rejected);
          break;
        }
        case "end": {
          endedRef.current = true;
          setEnded({ result: msg.result, reason: msg.reason });
          setStatus("ended");
          setTimeout(goReport, 3000);
          break;
        }
        case "error": {
          setNotice(msg.detail ?? msg.message ?? msgText.current.serverError);
          break;
        }
      }
    },
    [goReport],
  );

  // 2) WS bağlantısı; kopunca üstel geri çekilmeyle yeniden bağlan.
  useEffect(() => {
    if (!game || MOCK) return;
    let disposed = false;

    const connect = () => {
      if (disposed || endedRef.current) return;
      setConn("connecting");
      let ws: WebSocket;
      try {
        ws = new WebSocket(WS_URL);
      } catch {
        scheduleReconnect();
        return;
      }
      wsRef.current = ws;
      ws.onopen = () => {
        attemptRef.current = 0;
        setConn("open");
        const join: ClientMsg = {
          t: "join",
          session_id: sid,
          game_id: game.game_id,
          user_color: game.user_color,
          time_control: game.time_control,
        };
        ws.send(JSON.stringify(join));
      };
      ws.onmessage = (ev) => {
        try {
          onServerMsg(JSON.parse(String(ev.data)) as ServerMsg);
        } catch {
          /* bozuk mesaj: yoksay */
        }
      };
      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
        setConn("closed");
        setSynced(false);
        scheduleReconnect();
      };
      ws.onerror = () => {
        try {
          ws.close();
        } catch {
          /* yoksay */
        }
      };
    };

    const scheduleReconnect = () => {
      if (disposed || endedRef.current) return;
      const n = attemptRef.current++;
      const delay = Math.min(10_000, 500 * 2 ** n) + Math.random() * 300;
      reconnectTimer.current = setTimeout(connect, delay);
    };

    connect();
    return () => {
      disposed = true;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        ws.onclose = null;
        ws.close();
      }
    };
  }, [game, sid, onServerMsg]);

  // Saatler: sunucu durumları arasında yerelde akar.
  const running = synced && !ended && !ENDED_STATUSES.has(status) && (status !== "waiting" || moves.length > 0);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(performance.now()), 100);
    return () => clearInterval(t);
  }, [running]);

  const send = (m: ClientMsg) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(m));
    return true;
  };

  const turn = turnColor(fen);
  const displayFen = (pending && fenAfter(fen, [pending])) || fen;
  const myTurn = turn === userColor && !pending && !ended && conn === "open" && synced;

  // Bütünlük sinyali: kullanıcının sırasında sekme gizlenirse / pencere odağı kaybolursa hamleyle bildirilir.
  // Yalnız işaret; içerik ya da süre gönderilmez. Her yeni sırada sıfırlanır.
  const focusLostRef = useRef(false);
  useEffect(() => {
    if (!myTurn) return;
    focusLostRef.current = document.visibilityState === "hidden";
    const lost = () => {
      focusLostRef.current = true;
    };
    const onVisibility = () => {
      if (document.visibilityState === "hidden") lost();
    };
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("blur", lost);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("blur", lost);
    };
  }, [myTurn]);

  const onMove = (uci: string) => {
    if (!myTurn) return;
    if (send({ t: "move", uci, ply: moves.length, focus_lost: focusLostRef.current })) {
      setPending(uci);
      setNotice(null);
    }
  };

  const resign = () => {
    if (ended) return;
    if (window.confirm(P.confirmResign)) send({ t: "resign" });
  };

  const clockOf = (c: Color) => {
    if (!clocks) return game?.time_control.initial_ms ?? 600_000;
    const base = clocks[c];
    return running && c === turn ? base - Math.max(0, now - clockAt) : base;
  };

  const sans = useMemo(() => ucisToSan(undefined, moves), [moves]);
  const allMoves = pending ? [...moves, pending] : moves;
  const lastMove = lastMoveKeys(allMoves[allMoves.length - 1]);
  const oppColor: Color = userColor === "white" ? "black" : "white";

  if (MOCK) {
    return (
      <div className="card">
        <h1>{P.mockTitle}</h1>
        <p className="note">
          {P.mockNote}
        </p>
        <Link className="btn" href={`/report/${encodeURIComponent(sid)}`}>
          {P.toReport}
        </Link>
      </div>
    );
  }

  const renderClock = (c: Color, label: string) => {
    const ms = clockOf(c);
    return (
      <div className={`clock ${running && turn === c ? "active" : ""} ${ms < 30_000 ? "low" : ""}`}>
        <span className="who">{label}</span>
        <span>{fmtClock(ms)}</span>
      </div>
    );
  };

  if (notFound) return <SessionNotFound />;

  return (
    <div className="play-layout">
      <div className="stack">
        {renderClock(oppColor, `${P.bot} (${oppColor === "white" ? t.test.white : t.test.black})`)}
        <Board fen={displayFen} orientation={userColor} userColor={userColor} interactive={myTurn} onMove={onMove} lastMove={lastMove} />
        {renderClock(userColor, `${P.you} (${userColor === "white" ? t.test.white : t.test.black})`)}
      </div>

      <div className="side">
        <div className="card">
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>{P.title}</strong>
            <span className={`conn ${conn === "open" ? "ok" : "bad"}`}>
              {conn === "open" ? P.conn.open : conn === "connecting" ? P.conn.connecting : conn === "closed" ? P.conn.closed : P.conn.idle}
            </span>
          </div>
          <p className="muted small">
            {P.about}
          </p>
          {err && <div className="error">{err}</div>}
          {notice && <p className="muted small">{notice}</p>}
          {ended ? (
            <div className="feedback ok" style={{ marginTop: 8 }}>
              {P.over}: {ended.result} ({P.reasons[ended.reason] ?? ended.reason})
              <div className="sol">{P.preparing}</div>
              <button className="btn btn-small" style={{ marginTop: 8 }} onClick={goReport}>
                {P.goReport}
              </button>
            </div>
          ) : (
            <p className="muted small">
              {!synced ? P.syncing : myTurn ? P.yourTurn : pending ? P.sent : P.thinking}
            </p>
          )}
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn btn-danger btn-small" onClick={resign} disabled={!!ended || conn !== "open"}>
              {P.resign}
            </button>
          </div>
        </div>

        <div className="card">
          <h2>{P.moves}</h2>
          <div className="movelist">
            {Array.from({ length: Math.ceil(sans.length / 2) }).map((_, i) => (
              <div key={i} style={{ display: "contents" }}>
                <span className="muted">{i + 1}.</span>
                <span>{sans[2 * i]}</span>
                <span>{sans[2 * i + 1] ?? ""}</span>
              </div>
            ))}
            {sans.length === 0 && <span className="muted" style={{ gridColumn: "1 / -1" }}>{P.noMoves}</span>}
          </div>
        </div>
      </div>
    </div>
  );
}
