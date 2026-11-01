"""Uç bantlarda ortalamaya çekilme. Gerçek oyunlar (Faz 2 verisi) üzerinde, hariç tutma kuralları sabitken:
  - Maia'nın uç kovaların ötesine uzatılması (κ_alt, κ_üst, uzatma mesafesi; engines/human.py: interp_matrix)
  - önsel genişliği (N(1500, sd))
  - λ_Maia, λ_kayıp
eğitimde (%70) birlikte seçilir, testte (%30) raporlanır.

Ölçüt: MAE + 1000·|kapsama − 0.9| + 0.5·ortalama |bant sapması| (300'lük bantlar) — yalnız genel MAE uçları feda edebilir.

Gerekli: bt_moves.npz'de `maia_L/maia_off/maia_played` (backtest maiafull) ve `wp_loss`.
Kullanım (py/): python -m chessdex.sim.extremes ../data/raw/bt_moves.npz ../docs/results/extremes_tune.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np

from chessdex.engines.human import interp_matrix
from chessdex.measure.grid import GRID
from chessdex.measure.loss_model import LossModel
from chessdex.measure.match import PROB_FLOOR

from .backtest import evaluate, weights

KAPPAS = [0.0, 0.5, 1.0, 1.5]
MAX_EXTS = [400.0, 600.0]
PRIOR_SDS = [450.0, 600.0, 800.0]
LAMS_M = [0.3, 0.5, 0.7]
LAMS_S = [0.1, 0.2, 0.3]


def played_log_grid(d, kl: float, kh: float, mx: float, chunk: int = 4000) -> np.ndarray:
    """Her kullanıcı hamlesi için log P(oynanan | θ) — üretimdeki centers_to_grid ile aynı hesap (tüm hamlelerle normalize)."""
    M = interp_matrix(kl, kh, mx).T.astype(np.float32)                 # (11, G)
    L, off, played = d["maia_L"], d["maia_off"], d["maia_played"]
    out = np.empty((len(played), GRID.size), np.float32)
    for a in range(0, len(played), chunk):
        b = min(a + chunk, len(played))
        rows = L[off[a]:off[b]] @ M                                    # (Σ n_hamle, G)
        starts = (off[a:b] - off[a]).astype(np.int64)
        mx_ = np.maximum.reduceat(rows, starts, axis=0)
        rep = np.repeat(mx_, np.diff(off[a:b + 1]), axis=0)
        lse = np.log(np.add.reduceat(np.exp(rows - rep), starts, axis=0)) + mx_
        out[a:b] = rows[starts + played[a:b]] - lse
    return np.maximum(out, np.log(PROB_FLOOR))


def band_bias_mean(r: dict) -> float:
    return float(np.mean([abs(v["bias"]) for v in r["bands"].values()]))


def objective(r: dict) -> float:
    return r["mae"] + 1000.0 * abs(r["coverage90"] - 0.90) + 0.5 * band_bias_mean(r)


def prior_of(sd: float) -> np.ndarray:
    lp = -0.5 * ((GRID - 1500.0) / sd) ** 2
    return lp - np.logaddexp.reduce(lp)


def run(npz: str, out_path: str, base_cfg: dict, seed: int = 5) -> dict:
    d = dict(np.load(npz))
    n = len(d["rating"])
    perm = np.random.default_rng(seed).permutation(n)
    train, test = np.sort(perm[: int(0.7 * n)]), np.sort(perm[int(0.7 * n):])
    tr = np.isin(d["game"], train) & (d["ply"] >= 8)
    lmod = LossModel.fit(d["rating"][d["game"]][tr], d["wp_loss"][tr], d["eval_cp"][tr])
    LS = lmod.batch_log_lik(d["wp_loss"], d["eval_cp"])
    results = []
    cache = {}
    for kl, kh, mx in itertools.product(KAPPAS, KAPPAS, MAX_EXTS):
        if (kl == 0 and kh == 0) and mx != MAX_EXTS[0]:
            continue                                                   # uzatma yoksa mesafe önemsiz
        LM = played_log_grid(d, kl, kh, mx).astype(np.float64)
        dd = {**d, "grid": np.exp(LM)}                                  # zorunlu hamle kuralı aynı ızgarayla
        cache[(kl, kh, mx)] = (dd, LM)
        for sd, lm, ls in itertools.product(PRIOR_SDS, LAMS_M, LAMS_S):
            r = evaluate(dd, base_cfg, train, lm, ls, LM, LS, prior=prior_of(sd))
            results.append({"kappa_low": kl, "kappa_high": kh, "max_ext": mx, "prior_sd": sd,
                            "lambda_maia": lm, "lambda_loss": ls, "objective": round(objective(r), 1),
                            "mae": r["mae"], "coverage90": r["coverage90"], "band_bias": round(band_bias_mean(r), 1)})
        print(f"  κ=({kl},{kh}) mx={mx} tamam", file=sys.stderr, flush=True)
    best = min(results, key=lambda x: x["objective"])
    cur = {"kappa_low": 0.0, "kappa_high": 0.0, "max_ext": MAX_EXTS[0], "prior_sd": 450.0, "lambda_maia": 0.5,
           "lambda_loss": 0.2}

    def test_eval(c):
        dd, LM = cache[(c["kappa_low"], c["kappa_high"], c["max_ext"])]
        return evaluate(dd, base_cfg, test, c["lambda_maia"], c["lambda_loss"], LM, LS,
                        prior=prior_of(c["prior_sd"]), boot=1000)

    # yalnız önsel genişliğinin ve yalnız uzatmanın katkısını ayırmak için ara noktalar
    only_prior = min((x for x in results if x["kappa_low"] == 0 and x["kappa_high"] == 0), key=lambda x: x["objective"])
    only_ext = min((x for x in results if x["prior_sd"] == 450.0), key=lambda x: x["objective"])
    out = {
        "current": {"config": cur, "test": test_eval(cur)},
        "only_prior_tuned": {"config": only_prior, "test": test_eval(only_prior)},
        "only_extrapolation_tuned": {"config": only_ext, "test": test_eval(only_ext)},
        "chosen": {"config": best, "test": test_eval(best)},
        "top10_train": sorted(results, key=lambda x: x["objective"])[:10],
        "n_configs": len(results),
    }
    Path(out_path).write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def full_system(d, base_cfg: dict, idx: np.ndarray, conf: dict, LS: np.ndarray, bank_path: str,
                seed: int = 11) -> dict:
    """Tam sistem: her oyuncu için gerçek bankanın IRT parametreleriyle, GERÇEK rating'inde sentetik
    senaryo cevapları (üretimdeki seçim + durdurma, önsel = N(1500, sd)) → senaryo sonsalı × GERÇEK maç olabilirliği."""
    from collections import Counter

    from chessdex.measure.irt import category_probs, log_lik_graded
    from chessdex.measure.match import MIN_ANALYZABLE, result_log_lik
    from chessdex.measure.posterior import Posterior
    from chessdex.measure.selection import ItemPool, select_next
    from chessdex.measure.stopping import should_stop
    from chessdex.sim.synthetic import bank_items

    pool = ItemPool(bank_items(bank_path))
    LM = played_log_grid(d, conf["kappa_low"], conf["kappa_high"], conf["max_ext"]).astype(np.float64)
    dd = {**d, "grid": np.exp(LM)}
    w = weights(dd, base_cfg)
    per = conf["lambda_maia"] * LM + conf["lambda_loss"] * LS
    ll = np.zeros((len(d["rating"]), GRID.size))
    np.add.at(ll, d["game"], per * w[:, None])
    full = np.bincount(d["game"], weights=(w >= 1.0).astype(float), minlength=len(d["rating"]))
    rng = np.random.default_rng(seed)
    rows = {"scen": [], "final": []}
    R = d["rating"][idx].astype(float)
    for g in idx:
        theta = float(d["rating"][g])
        post = Posterior(prior_of(conf["prior_sd"]))
        used, kinds, n = set(), Counter(), 0
        while not should_stop(post, n):
            it = select_next(post, pool, used, rng, kinds)
            if it is None:
                break
            k = int(rng.choice(it.n_cat, p=category_probs(it, np.array([theta]))[:, 0]))
            post.update(log_lik_graded(it, k)); used.add(it.id); kinds[it.kind] += 1; n += 1
        rows["scen"].append((post.quantile(0.05), post.median(), post.quantile(0.95)))
        if full[g] >= MIN_ANALYZABLE:
            post.update(ll[g] + result_log_lik(float(d["score"][g]), float(d["opp_rating"][g])))
        rows["final"].append((post.quantile(0.05), post.median(), post.quantile(0.95)))
    out = {}
    for stage, q in rows.items():
        q = np.array(q); err = q[:, 1] - R; inside = (R >= q[:, 0]) & (R <= q[:, 2])
        bands = {}
        for b0 in range(600, 2700, 300):
            m = (R >= b0) & (R < b0 + 300)
            if m.sum() >= 10:
                bands[f"{b0}-{b0 + 299}"] = {"n": int(m.sum()), "bias": round(float(err[m].mean()), 1),
                                              "mae": round(float(np.abs(err[m]).mean()), 1),
                                              "cov": round(float(inside[m].mean()), 3)}
        out[stage] = {"mae": round(float(np.abs(err).mean()), 1), "coverage90": round(float(inside.mean()), 3),
                      "width90": round(float((q[:, 2] - q[:, 0]).mean()), 1), "bias": round(float(err.mean()), 1),
                      "bands": bands}
    return out


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("npz")
    ap.add_argument("out")
    ap.add_argument("--faz2", default="../docs/results/backtest_tune.json", help="sabit hariç tutma kuralları")
    ap.add_argument("--bank", default="data/bank.jsonl", help="tam sistem testi için senaryo bankası")
    args = ap.parse_args(argv)
    cfg = dict(json.loads(Path(args.faz2).read_text(encoding="utf-8"))["variants"]["maia+loss"]["chosen"])
    cfg.pop("lambda_maia"); cfg.pop("lambda_loss")
    res = run(args.npz, args.out, cfg)
    d = dict(np.load(args.npz))
    n = len(d["rating"]); test = np.sort(np.random.default_rng(5).permutation(n)[int(0.7 * n):])
    tr = np.isin(d["game"], np.setdiff1d(np.arange(n), test)) & (d["ply"] >= 8)
    LS = LossModel.fit(d["rating"][d["game"]][tr], d["wp_loss"][tr], d["eval_cp"][tr]).batch_log_lik(d["wp_loss"], d["eval_cp"])
    res["full_system"] = {k: full_system(d, cfg, test, res[k]["config"], LS, args.bank) for k in ("current", "chosen")}
    Path(args.out).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    for k in ("current", "only_prior_tuned", "only_extrapolation_tuned", "chosen"):
        t = res[k]["test"]
        print(k, res[k]["config"] if k != "current" else "",
              {x: t[x] for x in ("mae", "mae_ci95", "coverage90", "coverage_ci95", "width90", "bias")})
        print("   bantlar:", {b: (v["bias"], v["cov"]) for b, v in t["bands"].items()})
    for k, v in res["full_system"].items():
        for stage in ("scen", "final"):
            t = v[stage]
            print(f"tam sistem [{k}/{stage}]", {x: t[x] for x in ("mae", "coverage90", "width90", "bias")},
                  {b: (u["bias"], u["cov"]) for b, u in t["bands"].items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
