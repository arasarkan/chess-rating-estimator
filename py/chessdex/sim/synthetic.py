"""Faz 1 sentetik sınav: θ'sı bilinen sanal kullanıcılar adaptif teste sokulur.

Ölçülür: MAE, %90 aralık kapsaması, 200'lük bantlarda ortalama sapma, ortalama senaryo sayısı.
Kullanım: python -m chessdex.sim.synthetic --n 2000 --seed 1
Kısa mod (zaman bütçesi): --mode short --item-s 45  (senaryo başına sabit cevap süresi, sn)
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter

import numpy as np

from chessdex.measure.irt import POSITIONAL_OFFSETS, Item, category_probs, log_lik_graded
from chessdex.measure.posterior import Posterior
from chessdex.measure.prior import default_prior
from chessdex.measure.selection import TARGET_SHARES, ItemPool, select_next
from chessdex.measure.stopping import should_stop


def make_bank(n_items: int, rng: np.random.Generator) -> list[Item]:
    kinds = rng.choice(list(TARGET_SHARES), size=n_items, p=list(TARGET_SHARES.values()))
    items = []
    for i, kind in enumerate(kinds):
        b = rng.uniform(300, 3100)
        a = float(np.clip(rng.lognormal(0, 0.25), 0.5, 2.0))
        if kind == "positional":
            items.append(Item(f"s{i}", b=b, a=a, c=0.25, kind=kind, offsets=POSITIONAL_OFFSETS))
        else:
            items.append(Item(f"s{i}", b=b, a=a, c=0.02, kind=kind))
    return items


def simulate_user(theta: float, pool: ItemPool, rng: np.random.Generator, mode: str = "full", item_s: float = 0.0):
    post = Posterior(default_prior())
    used, counts, n = set(), Counter(), 0
    th = np.array([theta])
    while not should_stop(post, n, mode, int(n * item_s * 1000)):
        item = select_next(post, pool, used, rng, counts)
        if item is None:
            break
        k = int(rng.choice(item.n_cat, p=category_probs(item, th)[:, 0]))
        post.update(log_lik_graded(item, k))
        used.add(item.id)
        counts[item.kind] += 1
        n += 1
    return post, n


def bank_items(path: str) -> list[Item]:
    """Gerçek bankanın IRT parametreleri (b = α + β·bulmaca rating'i, a = 1)."""
    from chessdex.api.engine import to_irt
    from chessdex.bank.loader import load_items
    return [to_irt(it) for it in load_items(path)]


def run(n_users: int = 2000, seed: int = 1, n_items: int = 6000,
        theta_dist: str = "uniform", bank: str | None = None, mode: str = "full", item_s: float = 0.0) -> dict:
    rng = np.random.default_rng(seed)
    pool = ItemPool(bank_items(bank) if bank else make_bank(n_items, rng))
    if theta_dist == "uniform":
        thetas = rng.uniform(400, 2800, n_users)
    else:
        thetas = np.clip(rng.normal(1500, 450, n_users), 400, 2800)
    med, lo, hi, ns = (np.empty(n_users) for _ in range(4))
    t0 = time.perf_counter()
    for i, th in enumerate(thetas):
        post, n = simulate_user(float(th), pool, rng, mode, item_s)
        med[i], lo[i], hi[i], ns[i] = post.median(), post.quantile(0.05), post.quantile(0.95), n
    elapsed = time.perf_counter() - t0
    err = med - thetas
    bands = {}
    for start in range(400, 2800, 200):
        m = (thetas >= start) & (thetas < start + 200)
        if m.any():
            bands[f"{start}-{start + 199}"] = round(float(err[m].mean()), 1)
    return {
        "n_users": n_users,
        "mae": round(float(np.abs(err).mean()), 1),
        "coverage90": round(float(((thetas >= lo) & (thetas <= hi)).mean()), 3),
        "mean_items": round(float(ns.mean()), 2),
        "mean_width90": round(float((hi - lo).mean()), 1),
        "max_abs_band_bias": max(abs(v) for v in bands.values()),
        "band_bias": bands,
        "ms_per_item_step": round(1000 * elapsed / ns.sum(), 2),
        "pool_size": len(pool),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--items", type=int, default=6000)
    ap.add_argument("--dist", default="uniform", choices=["uniform", "normal"])
    ap.add_argument("--bank", default=None, help="gerçek banka JSONL (verilirse sentetik banka yerine)")
    ap.add_argument("--mode", default="full", choices=["full", "short"])
    ap.add_argument("--item-s", type=float, default=0.0, help="senaryo başına cevap süresi (sn); kısa mod bütçesi için")
    args = ap.parse_args()
    out = run(args.n, args.seed, args.items, args.dist, args.bank, args.mode, args.item_s)
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
