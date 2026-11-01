import { ImageResponse } from "next/og";

// Paylaşım önizlemesi (Twitter/X, vb.): makale başlık sayfası gibi sade. Varsayılan yazı tipi yalnız Latin
// karakterleri kapsadığı için metin İngilizcedir.
export const alt = "Adaptive Measurement of Chess Strength — research prototype";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OgImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          background: "#fbfbf9",
          color: "#1b1b1b",
          padding: "72px 80px",
        }}
      >
        <div style={{ display: "flex", fontSize: 26, color: "#5f6368", letterSpacing: 1 }}>
          RESEARCH PROTOTYPE · MODEL VERSION 0.3 · 2026
        </div>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", height: 2, background: "#1b1b1b", width: "100%" }} />
          <div style={{ display: "flex", height: 2, background: "#1b1b1b", width: "100%", marginTop: 4, marginBottom: 36 }} />
          <div style={{ display: "flex", fontSize: 72, lineHeight: 1.1 }}>Adaptive Measurement of Chess Strength</div>
          <div style={{ display: "flex", fontSize: 34, color: "#5f6368", marginTop: 24, lineHeight: 1.3 }}>
            Probabilistic estimation of rapid rating from chess problems and a single game, reported with a 90%
            credible interval.
          </div>
        </div>
        <div style={{ display: "flex", fontSize: 26, color: "#5f6368" }}>
          Item response theory · Bayesian inference · Maia-2 · Stockfish
        </div>
      </div>
    ),
    size,
  );
}
