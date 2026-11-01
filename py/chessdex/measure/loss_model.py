"""Hamle kalitesi olabilirliği: P(kazanma olasılığı kaybı kategorisi | θ, pozisyon).

Faz 2 bulgusu (docs/results/backtest.md): Maia-2'nin Elo koşullaması bireysel oyuncunun rating'ini ayırt etmiyor;
Stockfish'in hamle başına kazanma olasılığı kaybı ise rating'le güçlü ilişkili. Bu modül, gerçek oyunlardan öğrenilen
çok terimli lojistik bir modelle kaybı θ ızgarası üzerinde olabilirliğe çevirir:

  kategori k ∈ {≤1%, ≤3%, ≤7%, ≤15%, ≤30%, >30%}
  log P(k | θ, x) ∝ α_k + β_k·z + γ_k·z² + δ_k·e + η_k·e·z,   z = (θ − 1500)/400,  e = min(|eval|, 1000)/500

Parametreler sürümlü bir JSON'da (`py/data/loss_model.json`) tutulur; `fit` eğitim oyunlarından öğrenir.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .grid import GRID

EDGES = np.array([0.01, 0.03, 0.07, 0.15, 0.30])
K = len(EDGES) + 1
N_FEAT = 5
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "loss_model.json"


def category(wp_loss) -> np.ndarray:
    return np.searchsorted(EDGES, np.asarray(wp_loss, dtype=float), side="left")


def _features(z: np.ndarray, e: np.ndarray) -> np.ndarray:
    """z, e aynı şekilde → (..., N_FEAT)."""
    return np.stack([np.ones_like(z), z, z * z, e, e * z], axis=-1)


def _ev(eval_cp) -> np.ndarray:
    return np.minimum(np.abs(np.asarray(eval_cp, dtype=float)), 1000.0) / 500.0


class LossModel:
    def __init__(self, W: np.ndarray, meta: dict | None = None):
        self.W = np.asarray(W, dtype=float).reshape(K, N_FEAT)   # satır 0 referans (sıfır)
        self.meta = meta or {}

    # --------------------------------------------------------- olabilirlik
    def log_probs(self, theta: np.ndarray, eval_cp) -> np.ndarray:
        """θ (G,) ve tek bir eval → (G, K) log olasılık."""
        z = (np.asarray(theta, dtype=float) - 1500.0) / 400.0
        F = _features(z, np.full_like(z, float(_ev(eval_cp))))
        L = F @ self.W.T
        return L - np.logaddexp.reduce(L, axis=1, keepdims=True)

    def move_log_lik(self, wp_loss: float, eval_cp: float) -> np.ndarray:
        """Tek hamlenin GRID üzerindeki log olabilirliği."""
        return self.log_probs(GRID, eval_cp)[:, int(category(wp_loss))]

    def batch_log_lik(self, wp_loss: np.ndarray, eval_cp: np.ndarray) -> np.ndarray:
        """(n,) hamle → (n, G) log olabilirlik (geriye dönük test için vektörel)."""
        z = (GRID - 1500.0) / 400.0                                   # (G,)
        e = _ev(eval_cp)                                              # (n,)
        F = _features(np.broadcast_to(z, (len(e), len(z))), np.broadcast_to(e[:, None], (len(e), len(z))))
        L = F @ self.W.T                                              # (n, G, K)
        L = L - np.logaddexp.reduce(L, axis=2, keepdims=True)
        k = category(wp_loss)
        return np.take_along_axis(L, k[:, None, None], axis=2)[..., 0]

    # --------------------------------------------------------- öğrenme
    @classmethod
    def fit(cls, rating, wp_loss, eval_cp, weight=None, l2: float = 1e-3) -> "LossModel":
        from scipy.optimize import minimize

        z = (np.asarray(rating, dtype=float) - 1500.0) / 400.0
        F = _features(z, _ev(eval_cp))                                # (n, F)
        y = category(wp_loss)
        w = np.ones(len(y)) if weight is None else np.asarray(weight, dtype=float)
        Y = np.zeros((len(y), K)); Y[np.arange(len(y)), y] = 1.0

        def unpack(v):
            return np.vstack([np.zeros(N_FEAT), v.reshape(K - 1, N_FEAT)])

        def f(v):
            W = unpack(v)
            L = F @ W.T
            lse = np.logaddexp.reduce(L, axis=1)
            nll = -np.sum(w * (np.sum(Y * L, axis=1) - lse))
            P = np.exp(L - lse[:, None])
            G = ((P - Y) * w[:, None]).T @ F                          # (K, F)
            return nll + l2 * float(v @ v), (G[1:].ravel() + 2 * l2 * v)

        res = minimize(f, np.zeros((K - 1) * N_FEAT), jac=True, method="L-BFGS-B")
        return cls(unpack(res.x), {"n": int(len(y)), "nll_per_move": float(res.fun / max(w.sum(), 1)),
                                   "edges": EDGES.tolist()})

    # --------------------------------------------------------- kalıcılık
    def save(self, path: str | Path = DEFAULT_PATH, **extra) -> None:
        Path(path).write_text(json.dumps({"W": self.W.tolist(), "meta": {**self.meta, **extra}}, indent=1),
                              encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path = DEFAULT_PATH) -> "LossModel | None":
        p = Path(path)
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        return cls(np.array(d["W"]), d.get("meta"))
