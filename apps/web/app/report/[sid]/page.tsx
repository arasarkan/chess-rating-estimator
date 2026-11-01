"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import AccountLink from "@/components/AccountLink";
import EstimateBand from "@/components/EstimateBand";
import { useLang } from "@/components/LangProvider";
import PosteriorChart from "@/components/PosteriorChart";
import { api, ApiError, errorMessage, isNotFound } from "@/lib/api";
import SessionNotFound from "@/components/SessionNotFound";
import type { Dict } from "@/lib/i18n";
import type { CriticalMoment, Flag, Report, ScaleEstimate, SubskillName } from "@/lib/types";

const SCALES: (keyof Report["scales"])[] = ["lichess", "chesscom", "fide"];
const SUBSKILLS: SubskillName[] = ["tactics", "endgame", "positional", "defense", "time"];

// Yorum notları: suçlama değil, sonucun yorumlanmasına dair nötr notlar.
function flagText(f: Flag, flags: Dict["flags"]): string {
  if (typeof f === "string") return flags[f] ?? f;
  if (f.code && flags[String(f.code)]) return flags[String(f.code)];
  if (f.message) return String(f.message);
  if (f.code) return String(f.code);
  return JSON.stringify(f);
}

function moveNo(ply: number) {
  // ply 1 tabanlı varsayılır (1 = beyazın ilk hamlesi).
  const p = Math.max(1, ply);
  const n = Math.ceil(p / 2);
  return p % 2 === 1 ? `${n}.` : `${n}…`;
}

function lossText(m: CriticalMoment, r: Dict["report"], decimal: string) {
  const v = m.eval_loss;
  if (v == null || Number.isNaN(v)) return "—";
  if (Math.abs(v) <= 1) return r.lossWin(Math.round(v * 100));
  return r.lossPawn((v / 100).toFixed(1).replace(".", decimal));
}

export default function ReportPage() {
  const { sid } = useParams<{ sid: string }>();
  const { lang, t } = useLang();
  const R = t.report;
  const [report, setReport] = useState<Report | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [tries, setTries] = useState(0);

  const load = useCallback(async () => {
    setErr(null);
    try {
      setReport(await api.report(sid));
      setPreparing(false);
    } catch (e) {
      if (isNotFound(e)) {
        setNotFound(true);
        return;
      }
      // Oyun analizi henüz bitmemiş olabilir: birkaç kez yeniden dene.
      if (e instanceof ApiError && (e.status === 409 || e.status === 425 || e.status === 503) && tries < 10) {
        setTimeout(() => setTries((n) => n + 1), 2000);
        setPreparing(true);
        return;
      }
      setPreparing(false);
      setErr(errorMessage(e));
    }
  }, [sid, tries]);

  useEffect(() => {
    if (sid) load();
  }, [sid, load]);

  if (notFound) return <SessionNotFound />;
  if (!report) {
    return (
      <div className="card">
        {preparing ? (
          <p className="muted">{R.preparing}</p>
        ) : err ? (
          <>
            <div className="error">{err}</div>
            <button className="btn btn-small" onClick={load}>
              {R.retry}
            </button>
          </>
        ) : (
          <p className="muted">{R.loading}</p>
        )}
      </div>
    );
  }

  const e = report.estimate;
  const subs = SUBSKILLS.map((k) => ({ key: k, label: t.subskills[k] ?? k, v: report.subskills?.[k] ?? null })).filter(
    (s): s is typeof s & { v: ScaleEstimate } => s.v != null,
  );
  const moments = report.critical_moments ?? [];
  const flags = report.flags ?? [];
  const decimal = lang === "tr" ? "," : ".";

  return (
    <div className="paper" style={{ maxWidth: 760 }}>
      <header className="report-head">
        <h1>{R.title}</h1>
        <div className="muted small" style={{ fontFamily: "var(--sans)" }}>
          {R.estimate}
        </div>
        <div className="big-number">{Math.round(e.median)}</div>
        <p style={{ margin: "4px 0 0" }}>{R.interval(Math.round(e.lo90), Math.round(e.hi90))}</p>
      </header>

      <figure>
        <PosteriorChart est={e} />
        <figcaption>{R.figCaption(e.n_items)}</figcaption>
      </figure>
      <dl className="explain">
        <dt>{R.howRead}</dt>
        <dd>{R.howReadText}</dd>
        <dt>{R.whyDiff}</dt>
        <dd>
          {R.whyDiffText} <Link href="/sonuclar">{R.limits}</Link> · <Link href="/yontem">{R.method}</Link>
        </dd>
      </dl>

      <section className="section">
        <h2>{R.scales}</h2>
        <div className="stack">
          {SCALES.map((k) =>
            report.scales?.[k] ? <EstimateBand key={k} label={t.scales[k]} est={report.scales[k]} /> : null,
          )}
        </div>
        <p className="table-note">{R.scalesNote}</p>
      </section>

      {subs.length > 0 && (
        <section className="section">
          <h2>{R.subskills}</h2>
          <div className="stack">
            {subs.map((s) => (
              <EstimateBand key={s.key} label={s.label} est={s.v} />
            ))}
          </div>
          <p className="table-note">{R.subskillsNote}</p>
        </section>
      )}

      {moments.length > 0 && (
        <section className="section">
          <h2>{R.moments}</h2>
          <table className="moments">
            <thead>
              <tr>
                <th>{R.mMove}</th>
                <th>{R.mPlayed}</th>
                <th>{R.mLoss}</th>
                <th>{R.mTypical}</th>
              </tr>
            </thead>
            <tbody>
              {moments.map((m, i) => (
                <tr key={i}>
                  <td>{m.move_no ? `${m.move_no}${m.side === "black" ? "…" : "."}` : moveNo(m.ply)}</td>
                  <td>
                    <code>{m.played_san ?? m.played}</code>
                  </td>
                  <td>{lossText(m, R, decimal)}</td>
                  <td>
                    {m.typical ? <code>{m.typical_san ?? m.typical}</code> : <span className="muted">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {flags.length > 0 && (
        <section className="section">
          <h2>{R.flags}</h2>
          <ul>
            {flags.map((f, i) => (
              <li key={i}>{flagText(f, t.flags)}</li>
            ))}
          </ul>
        </section>
      )}

      <section className="section">
        <AccountLink sid={sid} report={report} onLinked={load} />
      </section>

      <div className="row">
        <Link className="btn btn-ghost" href="/">
          {R.newTest}
        </Link>
      </div>

      <p className="muted small" style={{ marginTop: 16, fontFamily: "var(--sans)" }}>
        {R.model}:{" "}
        {Object.entries(report.model_version ?? {})
          .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
          .join(" · ") || "—"}
      </p>
    </div>
  );
}
