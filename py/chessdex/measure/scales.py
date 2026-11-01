"""Skala dönüşümü. Katsayılar PİLOT ÖNCESİ YAKLAŞIK değerlerdir; eşleştirilmiş hesap verisiyle yeniden kurulacak."""
from __future__ import annotations

Z90 = 1.6449
FLOOR = 100   # doğrusal eşleme uçlarda bozulur; hiçbir skalada bunun altı gösterilmez

# hedef = slope * lichess + intercept, artı dönüşümün kendi belirsizliği (sd)
SCALES = {
    "lichess": {"slope": 1.0, "intercept": 0.0, "sd": 0.0},
    "chesscom": {"slope": 1.14, "intercept": -514.0, "sd": 100.0},
    "fide": {"slope": 0.86, "intercept": 110.0, "sd": 150.0},
}


def convert(summary: dict) -> dict:
    out = {}
    half = (summary["hi90"] - summary["lo90"]) / 2
    for name, s in SCALES.items():
        if name == "lichess":   # iç skala: sonsal yüzdelikleri aynen
            out[name] = {k: summary[k] for k in ("median", "lo90", "hi90")}
            continue
        med = s["slope"] * summary["median"] + s["intercept"]
        sd = ((s["slope"] * half / Z90) ** 2 + s["sd"] ** 2) ** 0.5
        lo, hi = med - Z90 * sd, med + Z90 * sd
        out[name] = {"median": round(max(med, FLOOR)), "lo90": round(max(lo, FLOOR)), "hi90": round(max(hi, FLOOR))}
    return out
