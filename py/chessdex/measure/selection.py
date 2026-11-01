"""Adaptif senaryo seçimi: beklenen sonsal varyansı en çok düşüren,
en iyi 5 aday arasından rastgele (maruziyet kontrolü), tür dengesi korunarak."""
from __future__ import annotations

from collections import Counter
from typing import Sequence

import numpy as np

from .grid import GRID
from .irt import Item, batch_category_probs
from .posterior import Posterior

TARGET_SHARES = {"tactics": 0.40, "endgame": 0.20, "defense": 0.15, "positional": 0.25}
TOP_K = 5
WINDOW = 450.0   # sonsal ortalamanın ± bu kadarındaki senaryolar aday olur
MAX_CANDIDATES = 300   # büyük havuzda EPV yalnızca bu kadar rastgele aday için hesaplanır (gecikme bütçesi)
SUPPORT_EPS = 1e-9     # sonsal olasılığı max'ın bu katından küçük ızgara noktaları hesaba girmez


class ItemPool:
    """Senaryo parametrelerini vektörel hesap için dizilerde tutar."""

    def __init__(self, items: Sequence[Item]):
        self.items = list(items)
        n = len(self.items)
        kmax = max(it.n_cat for it in self.items) - 1
        self.a = np.array([it.a for it in self.items], dtype=float)
        self.b = np.array([it.b for it in self.items], dtype=float)
        self.c = np.array([it.c for it in self.items], dtype=float)
        self.offsets = np.full((n, kmax), np.inf)
        for i, it in enumerate(self.items):
            self.offsets[i, : len(it.offsets)] = it.offsets
        self.kind = np.array([it.kind for it in self.items])
        self.index = {it.id: i for i, it in enumerate(self.items)}

    def __len__(self):
        return len(self.items)


def expected_posterior_variance(p: np.ndarray, probs: np.ndarray, grid: np.ndarray = GRID) -> np.ndarray:
    """p (G,), probs (n, K, G) → (n,) beklenen sonsal varyans."""
    joint = probs * p[None, None, :]                 # (n, K, G)
    pk = joint.sum(-1)                               # (n, K)
    safe = np.where(pk > 0, pk, 1.0)
    m1 = (joint * grid).sum(-1) / safe
    m2 = (joint * grid**2).sum(-1) / safe
    var = np.maximum(m2 - m1**2, 0.0)
    return (pk * var).sum(-1)


def target_kind(counts: Counter, shares: dict = TARGET_SHARES) -> list[str]:
    """Hedef paydan en çok geride kalan türden başlayarak sıralı liste."""
    n = sum(counts.values()) + 1
    return sorted(shares, key=lambda k: counts.get(k, 0) - shares[k] * n)


def select_next(post: Posterior, pool: ItemPool, used: set[str], rng: np.random.Generator,
                kind_counts: Counter | None = None, top_k: int = TOP_K) -> Item | None:
    mean = post.mean()
    avail = np.ones(len(pool), dtype=bool)
    used_idx = [pool.index[u] for u in used if u in pool.index]
    if used_idx:
        avail[used_idx] = False
    near = avail & (np.abs(pool.b - mean) < max(WINDOW, 2.5 * post.sd()))
    cand_mask = near if near.any() else avail
    if not cand_mask.any():
        return None
    for kind in target_kind(kind_counts or Counter()):
        m = cand_mask & (pool.kind == kind)
        if m.any():
            cand_mask = m
            break
    idx = np.flatnonzero(cand_mask)
    if idx.size > MAX_CANDIDATES:
        idx = np.sort(rng.choice(idx, MAX_CANDIDATES, replace=False))
    p = post.p
    support = p > SUPPORT_EPS * p.max()
    grid, ps = GRID[support], p[support] / p[support].sum()
    probs = batch_category_probs(pool.a[idx], pool.b[idx], pool.c[idx], pool.offsets[idx], grid)
    epv = expected_posterior_variance(ps, probs, grid)
    best = idx[np.argsort(epv)[:top_k]]
    return pool.items[int(rng.choice(best))]
