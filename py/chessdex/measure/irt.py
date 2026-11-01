"""Senaryo olabilirliği: 3PL + sıralı (graded response) model, Elo skalasında.

P(X >= k | θ) = c_k + (1 - c_k) · 1 / (1 + 10^(-a (θ - b_k) / 400))
b_k = b + offsets[k-1] artan, c_1 = c, c_k = 0 (k >= 2) → kümülatifler monoton.
İkili + süre: kategoriler 0 = yanlış, 1 = yavaş doğru, 2 = hızlı doğru.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .grid import GRID

FAST_OFFSET = 150.0          # hızlı doğru için ek zorluk (pilotla ayarlanacak)
POSITIONAL_OFFSETS = (-200.0, 0.0, 200.0)   # 0–3 puanlı pozisyonel senaryolar
EPS = 1e-12


@dataclass
class Item:
    id: str
    b: float
    a: float = 1.0
    c: float = 0.02
    kind: str = "tactics"
    offsets: tuple[float, ...] = field(default=(0.0, FAST_OFFSET))

    @property
    def n_cat(self) -> int:
        return len(self.offsets) + 1


def _logistic(a, theta, b):
    return 1.0 / (1.0 + 10.0 ** (-a * (theta - b) / 400.0))


def cumulative(item: Item, theta: np.ndarray = GRID) -> np.ndarray:
    """(K-1, G): P(X >= k), k = 1..K-1."""
    out = np.empty((len(item.offsets), theta.size))
    for j, off in enumerate(item.offsets):
        c = item.c if j == 0 else 0.0
        out[j] = c + (1 - c) * _logistic(item.a, theta, item.b + off)
    return out


def category_probs(item: Item, theta: np.ndarray = GRID) -> np.ndarray:
    """(K, G): P(X = k)."""
    cum = cumulative(item, theta)
    upper = np.vstack([np.ones(theta.size), cum])
    lower = np.vstack([cum, np.zeros(theta.size)])
    return np.clip(upper - lower, EPS, 1.0)


def log_lik_graded(item: Item, k: int) -> np.ndarray:
    return np.log(category_probs(item)[k])


def log_lik_binary(item: Item, x: int) -> np.ndarray:
    p = item.c + (1 - item.c) * _logistic(item.a, GRID, item.b)
    return np.log(np.clip(p if x else 1 - p, EPS, 1.0))


def batch_category_probs(a, b, c, offsets: np.ndarray, theta: np.ndarray = GRID) -> np.ndarray:
    """Vektörel: a,b,c (n,), offsets (n, Kmax-1; kullanılmayan = +inf) → (n, Kmax, G)."""
    n, km1 = offsets.shape
    thr = b[:, None] + offsets                                   # (n, K-1)
    z = -a[:, None, None] * (theta[None, None, :] - thr[:, :, None]) / 400.0
    lg = 1.0 / (1.0 + np.power(10.0, np.clip(z, -300, 300)))
    cs = np.zeros((n, km1))
    cs[:, 0] = c
    cum = cs[:, :, None] + (1 - cs[:, :, None]) * lg
    cum = np.where(np.isinf(offsets)[:, :, None], 0.0, cum)
    ones = np.ones((n, 1, theta.size))
    zeros = np.zeros((n, 1, theta.size))
    return np.clip(np.concatenate([ones, cum], 1) - np.concatenate([cum, zeros], 1), 0.0, 1.0)
