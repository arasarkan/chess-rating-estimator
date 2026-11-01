"use client";

import type { Estimate } from "@/lib/types";
import { useLang } from "./LangProvider";

/**
 * Sonsal dağılımın basit SVG gösterimi. Rapor tam sonsalı taşımadığı için
 * medyan ve %5/%95 yüzdeliklerinden iki parçalı (asimetrik) normal yaklaşımı çizilir.
 */
export default function PosteriorChart({ est }: { est: Estimate }) {
  const { lang, t } = useLang();
  const aria = t.demo.aria;
  const pct = (n: number) => (lang === "tr" ? `%${n}` : `${n}%`);
  const W = 600;
  const H = 160;
  const PAD_X = 24;
  const BASE = H - 28;
  const z90 = 1.645;
  const sdL = Math.max(20, (est.median - est.lo90) / z90);
  const sdR = Math.max(20, (est.hi90 - est.median) / z90);
  const xmin = Math.max(400, Math.floor((est.lo90 - 2.2 * sdL) / 100) * 100);
  const xmax = Math.min(3000, Math.ceil((est.hi90 + 2.2 * sdR) / 100) * 100);
  const span = Math.max(100, xmax - xmin);
  const sx = (v: number) => PAD_X + ((v - xmin) / span) * (W - 2 * PAD_X);
  const dens = (v: number) => {
    const sd = v < est.median ? sdL : sdR;
    return Math.exp(-0.5 * ((v - est.median) / sd) ** 2);
  };
  const sy = (d: number) => BASE - d * (BASE - 16);

  const N = 120;
  const pts: [number, number][] = [];
  for (let i = 0; i <= N; i++) {
    const v = xmin + (span * i) / N;
    pts.push([v, dens(v)]);
  }
  const line = pts.map(([v, d], i) => `${i ? "L" : "M"}${sx(v).toFixed(1)},${sy(d).toFixed(1)}`).join(" ");
  const inner = pts.filter(([v]) => v >= est.lo90 && v <= est.hi90);
  const area =
    inner.length > 1
      ? `M${sx(est.lo90).toFixed(1)},${BASE} ` +
        inner.map(([v, d]) => `L${sx(v).toFixed(1)},${sy(d).toFixed(1)}`).join(" ") +
        ` L${sx(est.hi90).toFixed(1)},${BASE} Z`
      : "";
  const ticks: number[] = [];
  const step = span > 1200 ? 400 : span > 600 ? 200 : 100;
  for (let t = Math.ceil(xmin / step) * step; t <= xmax; t += step) ticks.push(t);

  return (
    <svg className="posterior" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={aria}>
      <path d={area} className="post-area" />
      <path d={line} className="post-line" />
      <line x1={sx(est.median)} x2={sx(est.median)} y1={sy(1)} y2={BASE} className="post-median" />
      <line x1={PAD_X} x2={W - PAD_X} y1={BASE} y2={BASE} className="post-axis" />
      {ticks.map((t) => (
        <g key={t}>
          <line x1={sx(t)} x2={sx(t)} y1={BASE} y2={BASE + 4} className="post-axis" />
          <text x={sx(t)} y={BASE + 18} textAnchor="middle" className="post-tick">
            {t}
          </text>
        </g>
      ))}
      <text x={sx(est.median)} y={12} textAnchor="middle" className="post-label">
        {Math.round(est.median)}
      </text>
      <text x={sx(est.lo90)} y={BASE - 4} textAnchor="end" className="post-tick" dx={-4}>
        {pct(5)}
      </text>
      <text x={sx(est.hi90)} y={BASE - 4} textAnchor="start" className="post-tick" dx={4}>
        {pct(95)}
      </text>
    </svg>
  );
}
