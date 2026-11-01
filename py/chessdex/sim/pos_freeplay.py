"""Pozisyonel senaryo parametrelerinin gerçek oyun kararlarıyla sınanması.

Bankadaki her pozisyonel senaryo, rating'i bilinen bir oyuncunun gerçek oyunda o pozisyonda verdiği karardan gelir
(`meta.player_rating`, `meta.played_score` — senaryo şıklarıyla aynı 0–3 kayıp ölçeği). Bu kararlar, senaryonun
(a, b, eşikler) parametrelerinin serbest oyunda öngörü gücünü ölçer ve `measure.calibration`'ın tür düzeyindeki
düzeltmesiyle (b' = α + β·b, eşikler' = β·eşikler, a' = γ·a) karşılaştırılır.

Serbest oyunda şık yoktur → tahmin payı c = 0. Sonuç 4 şıklı senaryo biçimine doğrudan aktarılamaz (şıklar seçimi
kolaylaştırır); bu yüzden kalibrasyon dosyası yazılmaz, yalnızca tanı raporu üretilir.

Kullanım (py/ dizininden): python -m chessdex.sim.pos_freeplay data/positional.jsonl ../docs/results/pos_freeplay.json
"""
from __future__ import annotations

import argparse
import hashlib
import json

import numpy as np

from chessdex.measure import calibration


def rows_from_bank(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            m = d.get("meta") or {}
            if d.get("kind") != "positional" or "played_score" not in m or not d.get("offsets"):
                continue
            out.append({"kind": "positional", "theta": float(m["player_rating"]), "k": int(m["played_score"]),
                        "a": float(d["a"]), "b": float(d["b"]), "c": 0.0, "offsets": list(d["offsets"]),
                        "game": d["id"].split(":")[1]})
    return out


def split(rows: list[dict], holdout_frac: float = 0.3) -> tuple[list[dict], list[dict]]:
    """Oyun kimliğine göre belirlenimci ayrım (aynı oyunun pozisyonları aynı tarafta)."""
    tr, ho = [], []
    for r in rows:
        h = int(hashlib.sha1(r["game"].encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        (ho if h < holdout_frac else tr).append(r)
    return tr, ho


def _p_good(rows: list[dict], p: dict | None) -> np.ndarray:
    """Her satır için model P(k ≥ 2) (iyi hamle)."""
    theta, _, a, b, c, off = calibration._arrays(rows)
    pr = p or {"alpha": 0.0, "beta": 1.0, "gamma": 1.0}
    ks = []
    for kk in range(off.shape[1] + 1):
        ks.append(np.exp(calibration._log_lik(theta, np.full(len(rows), kk), a, b, c, off,
                                              pr["alpha"], pr["beta"], pr["gamma"])))
    probs = np.stack(ks, 1)
    return probs[:, 2:].sum(1)


def reliability(rows: list[dict], p: dict | None, bins=(-1e9, -600, -200, 200, 600, 1e9)) -> list[dict]:
    """rating − b'ye göre gözlenen ve öngörülen P(k ≥ 2)."""
    pr = p or {"alpha": 0.0, "beta": 1.0, "gamma": 1.0}
    theta = np.array([r["theta"] for r in rows])
    b2 = pr["alpha"] + pr["beta"] * np.array([r["b"] for r in rows])
    good = np.array([r["k"] >= 2 for r in rows], float)
    pred = _p_good(rows, p)
    out = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (theta - b2 >= lo) & (theta - b2 < hi)
        if m.any():
            out.append({"range": [lo, hi], "n": int(m.sum()), "observed": round(float(good[m].mean()), 3),
                        "predicted": round(float(pred[m].mean()), 3)})
    return out


def run(bank: str) -> dict:
    rows = rows_from_bank(bank)
    tr, ho = split(rows)
    p = calibration.fit_kind(tr)
    theta = np.array([r["theta"] for r in rows])
    b = np.array([r["b"] for r in rows])
    return {
        "n": len(rows), "n_train": len(tr), "n_holdout": len(ho),
        "k_counts": {str(k): sum(r["k"] == k for r in rows) for k in range(4)},
        "corr_rating_b": round(float(np.corrcoef(theta, b)[0, 1]), 3),
        "fit": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()},
        "mean_log_lik": {"train": {"identity": round(calibration.mean_log_lik(tr, None), 4),
                                   "fitted": round(calibration.mean_log_lik(tr, p), 4)},
                         "holdout": {"identity": round(calibration.mean_log_lik(ho, None), 4),
                                     "fitted": round(calibration.mean_log_lik(ho, p), 4)},
                         "holdout_rating_only": round(_rating_only_ll(tr, ho), 4)},
        "reliability_holdout": {"identity": reliability(ho, None), "fitted": reliability(ho, p)},
    }


def _rating_only_ll(tr: list[dict], ho: list[dict]) -> float:
    """Karşılaştırma: senaryo parametresi kullanmadan yalnız rating'e göre kategori dağılımı (4 rating bandı)."""
    edges = np.quantile([r["theta"] for r in tr], [0.25, 0.5, 0.75])
    band = lambda t: int(np.searchsorted(edges, t))                          # noqa: E731
    counts = np.ones((4, 4))
    for r in tr:
        counts[band(r["theta"]), r["k"]] += 1
    probs = counts / counts.sum(1, keepdims=True)
    return float(np.mean([np.log(probs[band(r["theta"]), r["k"]]) for r in ho]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Pozisyonel parametreleri gerçek oyun kararlarıyla sına")
    ap.add_argument("bank")
    ap.add_argument("out")
    args = ap.parse_args(argv)
    res = run(args.bank)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: res[k] for k in ("n", "fit", "mean_log_lik")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
