"use client";

import { useMemo, useState } from "react";
import { useLang } from "./LangProvider";

// Sunucudaki modelin sadeleştirilmiş kopyası (yalnızca anlatım için): aynı ızgara, aynı önsel, ikili 3PL.
const LO = 400;
const HI = 3000;
const STEP = 10;
const GRID = Array.from({ length: (HI - LO) / STEP + 1 }, (_, i) => LO + i * STEP);
const PRIOR_MEAN = 1500;
const PRIOR_SD = 800;
const A = 1;
const C = 0.02;

function pCorrect(theta: number, b: number) {
  return C + (1 - C) / (1 + 10 ** (-A * (theta - b) / 400));
}

function summarize(logp: number[]) {
  const m = Math.max(...logp);
  const w = logp.map((v) => Math.exp(v - m));
  const z = w.reduce((s, v) => s + v, 0);
  const p = w.map((v) => v / z);
  let acc = 0;
  let lo = LO;
  let med = LO;
  let hi = HI;
  let gotLo = false;
  let gotMed = false;
  let gotHi = false;
  for (let i = 0; i < p.length; i++) {
    acc += p[i];
    if (!gotLo && acc >= 0.05) [lo, gotLo] = [GRID[i], true];
    if (!gotMed && acc >= 0.5) [med, gotMed] = [GRID[i], true];
    if (!gotHi && acc >= 0.95) [hi, gotHi] = [GRID[i], true];
  }
  return { p, lo, med, hi };
}

const PRIOR = GRID.map((t) => -0.5 * ((t - PRIOR_MEAN) / PRIOR_SD) ** 2);

type Answer = { b: number; correct: boolean };

export default function PosteriorDemo() {
  const d = useLang().t.demo;
  const [b, setB] = useState(1500);
  const [answers, setAnswers] = useState<Answer[]>([]);

  const logp = useMemo(() => {
    const out = [...PRIOR];
    for (const a of answers) {
      for (let i = 0; i < GRID.length; i++) {
        const pc = pCorrect(GRID[i], a.b);
        out[i] += Math.log(a.correct ? pc : 1 - pc);
      }
    }
    return out;
  }, [answers]);
  const s = useMemo(() => summarize(logp), [logp]);

  const W = 600;
  const H = 190;
  const PX = 28;
  const BASE = H - 26;
  const TOP = 14;
  const sx = (v: number) => PX + ((v - LO) / (HI - LO)) * (W - 2 * PX);
  const pmax = Math.max(...s.p);
  const sy = (d: number) => BASE - (d / pmax) * (BASE - TOP);
  const line = GRID.map((t, i) => `${i ? "L" : "M"}${sx(t).toFixed(1)},${sy(s.p[i]).toFixed(1)}`).join(" ");
  const inner = GRID.map((t, i) => [t, s.p[i]] as const).filter(([t]) => t >= s.lo && t <= s.hi);
  const area =
    `M${sx(s.lo).toFixed(1)},${BASE} ` +
    inner.map(([t, d]) => `L${sx(t).toFixed(1)},${sy(d).toFixed(1)}`).join(" ") +
    ` L${sx(s.hi).toFixed(1)},${BASE} Z`;
  // seçili pozisyonun doğru çözülme olasılığı (0–1, aynı yükseklik ölçeğinde)
  const curve = GRID.filter((_, i) => i % 4 === 0)
    .map((t, i) => `${i ? "L" : "M"}${sx(t).toFixed(1)},${(BASE - pCorrect(t, b) * (BASE - TOP)).toFixed(1)}`)
    .join(" ");

  const last = answers[answers.length - 1];

  return (
    <div className="demo">
      <svg className="posterior" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={d.aria}>
        <path d={area} className="post-area" />
        <path d={line} className="post-line" />
        <path d={curve} className="irt-curve" stroke="var(--muted)" strokeDasharray="4 4" />
        <line x1={sx(s.med)} x2={sx(s.med)} y1={TOP} y2={BASE} className="post-median" />
        <line x1={PX} x2={W - PX} y1={BASE} y2={BASE} className="post-axis" />
        {[400, 1000, 1500, 2000, 2500, 3000].map((t) => (
          <text key={t} x={sx(t)} y={BASE + 18} textAnchor="middle" className="post-tick">
            {t}
          </text>
        ))}
        <line x1={sx(b)} x2={sx(b)} y1={BASE - 6} y2={BASE + 2} stroke="var(--muted)" strokeWidth={2} />
      </svg>
      <p style={{ margin: "4px 0 10px", fontFamily: "var(--sans)" }}>
        {d.estimate} <strong>{s.med}</strong>, {d.interval}{" "}
        <strong>
          {s.lo}–{s.hi}
        </strong>{" "}
        <span className="muted">
          ({d.width} {s.hi - s.lo}, {answers.length} {d.answers})
        </span>
      </p>
      <div className="row">
        <label>
          {d.difficulty}
          <input type="range" min={600} max={2800} step={50} value={b} onChange={(e) => setB(Number(e.target.value))} />
          <span style={{ fontVariantNumeric: "tabular-nums", minWidth: 40 }}>{b}</span>
        </label>
        <button className="btn btn-small btn-ghost" onClick={() => setB(Math.min(2800, Math.max(600, Math.round(s.med / 50) * 50)))}>
          {d.match}
        </button>
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn btn-small" onClick={() => setAnswers([...answers, { b, correct: true }])}>
          {d.correct}
        </button>
        <button className="btn btn-small btn-ghost" onClick={() => setAnswers([...answers, { b, correct: false }])}>
          {d.wrong}
        </button>
        <button className="btn btn-small btn-ghost" onClick={() => setAnswers([])} disabled={!answers.length}>
          {d.reset}
        </button>
      </div>
      <p className="demo-log">
        {last ? d.last(last.b, last.correct) : d.none}
      </p>
    </div>
  );
}
