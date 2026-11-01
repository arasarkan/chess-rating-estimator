"""Izgara üzerinde tam sonsal dağılım."""
from __future__ import annotations

import zlib

import numpy as np

from .grid import GRID


class Posterior:
    def __init__(self, log_prior: np.ndarray):
        self.logp = np.asarray(log_prior, dtype=np.float64).copy()
        self._norm()

    def _norm(self):
        self.logp -= np.logaddexp.reduce(self.logp)

    def update(self, log_lik: np.ndarray, weight: float = 1.0) -> "Posterior":
        self.logp = self.logp + weight * np.asarray(log_lik)
        self._norm()
        return self

    def copy(self) -> "Posterior":
        return Posterior(self.logp)

    @property
    def p(self) -> np.ndarray:
        return np.exp(self.logp)

    def mean(self) -> float:
        return float(self.p @ GRID)

    def sd(self) -> float:
        p = self.p
        m = p @ GRID
        return float(np.sqrt(max(p @ (GRID - m) ** 2, 0.0)))

    def quantile(self, q: float) -> float:
        # Her ızgara noktası [x-5, x+5] aralığına yayılmış kabul edilir (doğrusal CDF).
        p = self.p
        cdf = np.cumsum(p)
        edges = np.concatenate([[GRID[0] - 5.0], GRID + 5.0])
        return float(np.interp(q, np.concatenate([[0.0], cdf]), edges))

    def median(self) -> float:
        return self.quantile(0.5)

    def summary(self) -> dict:
        return {
            "median": round(self.median()),
            "lo90": round(self.quantile(0.05)),
            "hi90": round(self.quantile(0.95)),
            "sd": round(self.sd(), 1),
        }

    def compress(self) -> bytes:
        return zlib.compress(self.p.astype(np.float32).tobytes())

    @classmethod
    def decompress(cls, blob: bytes) -> "Posterior":
        p = np.frombuffer(zlib.decompress(blob), dtype=np.float32).astype(np.float64)
        return cls(np.log(np.clip(p, 1e-300, None)))
