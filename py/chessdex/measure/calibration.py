"""Senaryo parametrelerinin pilot cevaplarıyla kalibrasyonu.

Plan: "α ve β pilot verisinden öğrenilir"; item_params sürümlüdür.

Doğrulanmış rating'i (θ) bilinen oyuncuların kademeli cevaplarından tür başına doğrusal bir düzeltme öğrenilir:
  b' = α + β·b,   eşikler' = β·eşikler,   a' = γ·a
(β zorluk ölçeğini, α kaymayı, γ ayırt ediciliği düzeltir). Az veriyle uçuk değer çıkmasın diye parametreler zayıf bir
önselle kimliğe (α=0, β=1, γ=1) çekilir; bir türde MIN_RESPONSES'tan az cevap varsa o tür değiştirilmez.
Kalibrasyon sürümlü bir JSON'dur; API açılışta yükler
(`CHESSDEX_ITEM_CALIBRATION`, vars. py/data/item_calibration.json).
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np

from .irt import Item

MIN_RESPONSES = 30
PRIOR_SD = {"alpha": 300.0, "log_beta": 0.5, "log_gamma": 0.7}
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "item_calibration.json"
EPS = 1e-12


def apply(item: Item, cal: dict | None) -> Item:
    if not cal:
        return item
    p = (cal.get("per_kind") or {}).get(item.kind)
    if not p:
        return item
    beta = float(p["beta"])
    return replace(item, b=float(p["alpha"]) + beta * item.b, a=float(p["gamma"]) * item.a,
                   offsets=tuple(beta * o for o in item.offsets))


def load(path: str | Path | None = None) -> dict | None:
    p = Path(path) if path else DEFAULT_PATH
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save(cal: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(cal, indent=1, ensure_ascii=False), encoding="utf-8")


def _log_lik(theta, k, a, b, c, offsets, alpha, beta, gamma) -> np.ndarray:
    """Her cevap için log P(X = k | θ) — irt.category_probs ile aynı model, satır başına θ."""
    n, km1 = offsets.shape
    thr = (alpha + beta * b)[:, None] + beta * offsets                         # (n, K-1)
    z = -(gamma * a)[:, None] * (theta[:, None] - thr) / 400.0
    lg = 1.0 / (1.0 + np.power(10.0, np.clip(z, -300, 300)))
    cs = np.zeros((n, km1))
    cs[:, 0] = c
    cum = cs + (1 - cs) * lg
    cum = np.where(np.isinf(offsets), 0.0, cum)
    upper = np.concatenate([np.ones((n, 1)), cum], 1)
    lower = np.concatenate([cum, np.zeros((n, 1))], 1)
    p = np.take_along_axis(upper - lower, k[:, None], 1)[:, 0]
    return np.log(np.clip(p, EPS, 1.0))


def _arrays(rows: list[dict]):
    kmax = max(len(r["offsets"]) for r in rows)
    off = np.full((len(rows), kmax), np.inf)
    for i, r in enumerate(rows):
        off[i, : len(r["offsets"])] = r["offsets"]
    f = lambda key: np.array([r[key] for r in rows], float)                    # noqa: E731
    return f("theta"), np.array([r["k"] for r in rows], int), f("a"), f("b"), f("c"), off


def fit_kind(rows: list[dict]) -> dict:
    from scipy.optimize import minimize

    theta, k, a, b, c, off = _arrays(rows)

    def nll(v):
        # α 100 Elo biriminde optimize edilir: üç parametre aynı mertebede olsun (Nelder-Mead adım boyu)
        alpha, lb, lg = 100.0 * v[0], v[1], v[2]
        ll = _log_lik(theta, k, a, b, c, off, alpha, np.exp(lb), np.exp(lg)).sum()
        prior = (alpha / PRIOR_SD["alpha"]) ** 2 + (lb / PRIOR_SD["log_beta"]) ** 2 + (lg / PRIOR_SD["log_gamma"]) ** 2
        return -ll + 0.5 * prior

    res = minimize(nll, np.zeros(3), method="Nelder-Mead",
                   options={"xatol": 1e-4, "fatol": 1e-6, "maxiter": 8000,
                            "initial_simplex": np.array([[0, 0, 0], [1, 0, 0], [0, 0.2, 0], [0, 0, 0.2]], float)})
    alpha, lb, lg = 100.0 * res.x[0], res.x[1], res.x[2]
    return {"alpha": float(alpha), "beta": float(np.exp(lb)), "gamma": float(np.exp(lg)), "n": len(rows),
            "converged": bool(res.success)}


def mean_log_lik(rows: list[dict], params: dict | None) -> float:
    if not rows:
        return float("nan")
    theta, k, a, b, c, off = _arrays(rows)
    p = params or {"alpha": 0.0, "beta": 1.0, "gamma": 1.0}
    return float(_log_lik(theta, k, a, b, c, off, p["alpha"], p["beta"], p["gamma"]).mean())


def fit(rows: list[dict], holdout: list[dict] | None = None, version: str | None = None) -> dict:
    """rows/holdout: {"kind","theta","k","a","b","c","offsets"} sözlükleri (bankadaki ham parametrelerle)."""
    per_kind, report = {}, {}
    for kind in sorted({r["kind"] for r in rows}):
        kr = [r for r in rows if r["kind"] == kind]
        hr = [r for r in (holdout or []) if r["kind"] == kind]
        if len(kr) < MIN_RESPONSES:
            report[kind] = {"n": len(kr), "skipped": f"< {MIN_RESPONSES} cevap"}
            continue
        p = fit_kind(kr)
        per_kind[kind] = p
        report[kind] = {**p, "train_ll": (mean_log_lik(kr, None), mean_log_lik(kr, p)),
                        "holdout_ll": (mean_log_lik(hr, None), mean_log_lik(hr, p)) if hr else None}
    return {"version": version or time.strftime("pilot-%Y%m%d-%H%M%S"), "created": time.time(),
            "model": "b'=alpha+beta*b, offsets'=beta*offsets, a'=gamma*a", "per_kind": per_kind, "fit": report}
