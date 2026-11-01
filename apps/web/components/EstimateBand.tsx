"use client";

import type { Estimate, ScaleEstimate } from "@/lib/types";
import { useLang } from "./LangProvider";

const MIN = 400;
const MAX = 3000;

function pct(v: number, lo = MIN, hi = MAX) {
  return Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100));
}

/** Yatay bant: %90 aralık + medyan işareti. */
export default function EstimateBand({
  est,
  label,
  compact,
  min = MIN,
  max = MAX,
}: {
  est: Pick<Estimate, "median" | "lo90" | "hi90"> | ScaleEstimate;
  label?: string;
  compact?: boolean;
  min?: number;
  max?: number;
}) {
  const d = useLang().t.demo;
  const l = pct(est.lo90, min, max);
  const h = pct(est.hi90, min, max);
  const m = pct(est.median, min, max);
  return (
    <div className={compact ? "band band-compact" : "band"}>
      {label && <div className="band-label">{label}</div>}
      <div className="band-track" aria-label={`${d.estimate} ${Math.round(est.median)}, ${d.interval} ${Math.round(est.lo90)}–${Math.round(est.hi90)}`}>
        <div className="band-range" style={{ left: `${l}%`, width: `${Math.max(0.5, h - l)}%` }} />
        <div className="band-median" style={{ left: `${m}%` }} />
      </div>
      <div className="band-text">
        <strong>{Math.round(est.median)}</strong>{" "}
        <span className="muted">
          ({Math.round(est.lo90)}–{Math.round(est.hi90)})
        </span>
      </div>
    </div>
  );
}
