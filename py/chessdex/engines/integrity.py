"""Basit hile/düşük çaba sinyal puanı (PLAN: "Hile önleme ve veri kalitesi").

Girdi: kullanıcı hamlesi başına sözlükler
    {"engine_match": bool|None,   # Stockfish ilk hamlesiyle eşleşme
     "human_prob": float|None,    # θ̂'da insan modeli olasılığı P(hamle)
     "spent_ms": int|None,        # harcanan süre
     "complexity": float|None,    # pozisyon karmaşıklığı (ör. entropi)
     "focus_lost": bool}          # bu hamle sırasında sekme/odak kaybı
Çıktı: {"score": 0..1, "reasons": [...], "flag": bool, "signals": {...}}

Puan bir suçlama değildir; işaretli oturum "güvenilirlik eşiğinin altında" sayılır
ve kalibrasyon verisine girmez.
"""
from __future__ import annotations

import math

import numpy as np

MIN_MOVES = 10                 # istatistiksel sinyaller için en az hamle
ENGINE_MATCH_BASE = 0.60       # bu orana kadar eşleşme normal sayılır
ENGINE_MATCH_HIGH = 0.90       # bu oranda sinyal tam (1.0)
LOW_HUMAN_PROB = 0.05          # "insan için olası değil" eşiği
LOW_HUMAN_FRAC_BASE = 0.15     # düşük-olasılıklı hamle oranı normal üst sınırı
LOW_HUMAN_FRAC_HIGH = 0.40
TIME_CV_LOW = 0.25             # süre varyasyon katsayısı bunun altında → sabit süreler
TIME_CORR_LOW = 0.10           # |corr(süre, karmaşıklık)| bunun altında → bağımsız
TIME_CV_FLAT = 0.05            # CV bunun altında → korelasyona bakmadan sabit süre
FOCUS_FRAC_BASE = 0.05
FOCUS_FRAC_HIGH = 0.30
LOW_EFFORT_MEDIAN_MS = 1500    # medyan süre bunun altındaysa ve eşleşme düşükse
LOW_EFFORT_MATCH = 0.30

# Sinyal ağırlıkları: score = 1 - Π(1 - w_i * s_i)
WEIGHTS = {
    "engine_match": 0.55,
    "low_human_prob": 0.35,
    "constant_time": 0.30,
    "focus_lost": 0.45,
    "focus_then_match": 0.35,
    "low_effort": 0.60,
}
FLAG_THRESHOLD = 0.5


def _ramp(x: float, lo: float, hi: float) -> float:
    if x <= lo:
        return 0.0
    if x >= hi:
        return 1.0
    return (x - lo) / (hi - lo)


def integrity_score(moves: list[dict]) -> dict:
    """Oyun için hile/düşük çaba puanı."""
    sig: dict[str, float] = {}
    n = len(moves)

    matches = [bool(m["engine_match"]) for m in moves if m.get("engine_match") is not None]
    match_rate = float(np.mean(matches)) if matches else None
    if len(matches) >= MIN_MOVES:
        sig["engine_match"] = _ramp(match_rate, ENGINE_MATCH_BASE, ENGINE_MATCH_HIGH)

    hp = [float(m["human_prob"]) for m in moves if m.get("human_prob") is not None]
    if len(hp) >= MIN_MOVES:
        frac = float(np.mean(np.array(hp) < LOW_HUMAN_PROB))
        s = _ramp(frac, LOW_HUMAN_FRAC_BASE, LOW_HUMAN_FRAC_HIGH)
        # insanca olmayan hamleler ancak motorla eşleşiyorsa şüphelidir
        if match_rate is not None:
            s *= _ramp(match_rate, 0.4, 0.7)
        sig["low_human_prob"] = s

    pairs = [(float(m["spent_ms"]), m.get("complexity")) for m in moves if m.get("spent_ms") is not None]
    if len(pairs) >= MIN_MOVES:
        t = np.array([p[0] for p in pairs])
        mean_t = float(t.mean())
        cv = float(t.std() / mean_t) if mean_t > 0 else 0.0
        s_cv = 1.0 - _ramp(cv, TIME_CV_LOW * 0.5, TIME_CV_LOW * 1.5)
        cx = [p[1] for p in pairs]
        s_corr = 1.0
        if all(c is not None for c in cx):
            c = np.array(cx, dtype=np.float64)
            if t.std() > 0 and c.std() > 0:
                r = float(np.corrcoef(t, c)[0, 1])
                s_corr = 1.0 - _ramp(abs(r), TIME_CORR_LOW, TIME_CORR_LOW * 3)
        # aşırı düşük CV, korelasyondan bağımsız olarak tek başına yeterli
        s_flat = 1.0 - _ramp(cv, TIME_CV_FLAT, TIME_CV_FLAT * 2.5)
        sig["constant_time"] = max(s_cv * s_corr, s_flat)

        med = float(np.median(t))
        if med < LOW_EFFORT_MEDIAN_MS and (match_rate is None or match_rate < LOW_EFFORT_MATCH):
            sig["low_effort"] = 1.0 - _ramp(med, LOW_EFFORT_MEDIAN_MS * 0.5, LOW_EFFORT_MEDIAN_MS)

    if n:
        focus = [bool(m.get("focus_lost")) for m in moves]
        ffrac = float(np.mean(focus))
        sig["focus_lost"] = _ramp(ffrac, FOCUS_FRAC_BASE, FOCUS_FRAC_HIGH)
        fm = [bool(m["engine_match"]) for m in moves
              if m.get("focus_lost") and m.get("engine_match") is not None]
        if len(fm) >= 3:
            sig["focus_then_match"] = _ramp(float(np.mean(fm)), 0.6, 0.9)

    prod = 1.0
    for k, s in sig.items():
        prod *= 1.0 - WEIGHTS[k] * s
    score = float(min(max(1.0 - prod, 0.0), 1.0))
    reasons = sorted((k for k, s in sig.items() if s >= 0.5), key=lambda k: -WEIGHTS[k] * sig[k])
    return {
        "score": score,
        "reasons": reasons,
        "flag": score >= FLAG_THRESHOLD,
        "signals": {k: round(v, 4) for k, v in sig.items()},
        "n_moves": n,
        "engine_match_rate": match_rate if match_rate is None or not math.isnan(match_rate) else None,
    }
