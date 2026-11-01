"""Faz 2: geriye dönük test. Rating'i kararlı oyuncuların gerçek rapid oyunlarında maç olabilirliği
(Maia-2 + hariç tutma kuralları + λ) oyuncunun rating'ini ne kadar iyi geri buluyor?

Adımlar:
  collect  Lichess aylık PGN'inin başını akışla okur. Rapid, normal bitişli, ≥ 20 hamlelik oyunlar; rating kararlılığı
           vekili: K_etkin = |RatingDiff| / |sonuç − beklenen| ≤ K_MAX (PGN'de RD yok; Glicko'da K≈14 @RD50, ≈31 @RD75).
           Oyun başına rastgele bir taraf "kullanıcı"; kullanıcı rating bandı başına kota.
  process  Her kullanıcı hamlesi için ham sinyaller: Maia-2 ızgarası P(hamle | θ) (üretimdeki kod yolu, rakip = gerçek
           rakip rating'i), kitapta mı, yasal hamle sayısı, Stockfish değerlendirmesi (backtest için 100k düğüm), saat.
           Paralel süreçler; çıktı .npz.
  tune     λ ve hariç tutma kuralları ızgarada taranır: eğitim (%70) ile seçilir, test (%30) ile raporlanır.
           Ölçüt (plan): MAE ve %90 kapsamanın hedefe yakınlığı birlikte.

Kullanım (py/):
  python -m chessdex.sim.backtest collect URL ../data/raw/bt_games.jsonl --per-band 60
  python -m chessdex.sim.backtest process ../data/raw/bt_games.jsonl ../data/raw/bt_moves.npz --workers 10
  python -m chessdex.sim.backtest tune ../data/raw/bt_moves.npz ../docs/results/backtest_tune.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import chess
import chess.pgn
import numpy as np

from chessdex.measure.grid import GRID

K_MAX = 25.0                 # kararlı rating vekili
MIN_SURPRISE = 0.15          # |sonuç − beklenen| bundan küçükse K_etkin hesaplanamaz → oyun alınmaz
MIN_FULL_MOVES = 20
BAND_LO, BAND_HI, BAND_W = 600, 2700, 100
BT_NODES = 100_000           # yalnızca |eval| > 5 piyon kuralı için; üretim 1M kullanır


# ================================================================= collect
def _rapid(h) -> bool:
    if "Rated Rapid" not in h.get("Event", "") or h.get("Termination") != "Normal":
        return False
    try:
        base, inc = (int(x) for x in h.get("TimeControl", "-").split("+"))
    except ValueError:
        return False
    return 480 <= base + 40 * inc <= 1500


def _stable(rating: int, opp: int, score: float, diff: str | None) -> bool:
    if diff is None:
        return False
    e = 1.0 / (1.0 + 10 ** ((opp - rating) / 400))
    surprise = abs(score - e)
    if surprise < MIN_SURPRISE:
        return False
    return abs(int(diff)) / surprise <= K_MAX


def collect(url: str, out_path: str, per_band: int, max_mb: int, seed: int = 21) -> dict:
    from chessdex.bank.pgnstream import stream_games

    rng = random.Random(seed)
    want = {b: per_band for b in range(BAND_LO, BAND_HI, BAND_W)}
    got: dict[int, int] = {}
    n_games = n_rapid = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for raw in stream_games(url, max_mb):
            h = raw.headers
            n_games += 1
            if not _rapid(h) or h.get("Result") not in ("1-0", "0-1", "1/2-1/2"):
                continue
            n_rapid += 1
            try:
                wr, br = int(h["WhiteElo"]), int(h["BlackElo"])
            except (KeyError, ValueError):
                continue
            color = rng.choice(("white", "black"))
            r, o = (wr, br) if color == "white" else (br, wr)
            ws = {"1-0": 1.0, "0-1": 0.0, "1/2-1/2": 0.5}[h["Result"]]
            score = ws if color == "white" else 1.0 - ws
            diff = h.get("WhiteRatingDiff" if color == "white" else "BlackRatingDiff")
            band = r // BAND_W * BAND_W
            if got.get(band, 0) >= want.get(band, 0) or not _stable(r, o, score, diff):
                continue
            game = raw.parse()
            if game is None or game.headers.get("Site") != h.get("Site"):
                continue
            nodes = list(game.mainline())
            if len(nodes) < 2 * MIN_FULL_MOVES:
                continue
            moves, clocks = [], []
            for nd in nodes:
                moves.append(nd.move.uci())
                c = nd.clock()
                clocks.append(None if c is None else int(c * 1000))
            out.write(json.dumps({"site": h.get("Site"), "color": color, "rating": r, "opp_rating": o,
                                  "score": score, "tc": h.get("TimeControl"), "moves": moves,
                                  "clocks_ms": clocks}) + "\n")
            got[band] = got.get(band, 0) + 1
            if all(got.get(b, 0) >= n for b, n in want.items()):
                break
    return {"games_read": n_games, "rapid": n_rapid, "kept": sum(got.values()), "per_band": dict(sorted(got.items()))}


# ================================================================= process
_W = {}


def _worker_init():
    import atexit
    import threading

    import chess.engine

    from chessdex.engines.exclusion import builtin_book
    from chessdex.engines.human import Maia2Model
    from chessdex.engines.stockfish import find_stockfish

    _W["maia"] = Maia2Model()
    eng = chess.engine.SimpleEngine.popen_uci(find_stockfish())
    eng.configure({"Threads": 1, "Hash": 16})
    getattr(threading, "_register_atexit", atexit.register)(eng.quit)
    _W["sf"] = eng
    _W["book"] = builtin_book()


def process_game(g: dict) -> dict | None:
    import chess.engine

    maia, sf, book = _W["maia"], _W["sf"], _W["book"]
    board = chess.Board()
    user_white = g["color"] == "white"
    rows = []
    for ply, (uci, clk) in enumerate(zip(g["moves"], g["clocks_ms"])):
        if (board.turn == chess.WHITE) == user_white:
            fen = board.fen()
            try:
                grid = maia.move_prob_grid(fen, uci, g["opp_rating"])
            except ValueError:
                return None
            pov = board.turn
            info = sf.analyse(board, chess.engine.Limit(nodes=BT_NODES), game=object())
            sc = info["score"].pov(pov)
            ev = 10_000 if sc.is_mate() else sc.score()
            before_cp = sc.score(mate_score=100_000)
            n_legal = board.legal_moves.count()
            board.push_uci(uci)
            if board.is_game_over():
                after_cp = 100_000 if board.is_checkmate() else 0
            else:
                after_cp = sf.analyse(board, chess.engine.Limit(nodes=BT_NODES), game=object())["score"] \
                    .pov(pov).score(mate_score=100_000)
            rows.append({"ply": ply, "grid": grid.astype(np.float32), "book": book.contains(fen, uci),
                         "n_legal": n_legal, "eval_cp": ev, "clock_ms": clk,
                         "wp_loss": max(0.0, _wp(before_cp) - _wp(after_cp))})
            continue
        board.push_uci(uci)
    return {"rating": g["rating"], "opp_rating": g["opp_rating"], "score": g["score"], "rows": rows}


def process(in_path: str, out_path: str, workers: int) -> dict:
    games = [json.loads(l) for l in open(in_path, encoding="utf-8") if l.strip()]
    res = []
    with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init) as ex:
        for i, r in enumerate(ex.map(process_game, games, chunksize=4)):
            if r is not None:
                res.append(r)
            if (i + 1) % 100 == 0:
                print(f"  {i + 1}/{len(games)}", file=sys.stderr, flush=True)
    # düz diziler: oyun indeksi + hamle başına sinyaller
    gi = np.concatenate([[k] * len(r["rows"]) for k, r in enumerate(res)]).astype(np.int32)
    rows = [row for r in res for row in r["rows"]]
    np.savez_compressed(
        out_path,
        rating=np.array([r["rating"] for r in res], np.float32),
        opp_rating=np.array([r["opp_rating"] for r in res], np.float32),
        score=np.array([r["score"] for r in res], np.float32),
        game=gi, ply=np.array([x["ply"] for x in rows], np.int16),
        grid=np.stack([x["grid"] for x in rows]),
        book=np.array([x["book"] for x in rows], bool),
        n_legal=np.array([x["n_legal"] for x in rows], np.int16),
        eval_cp=np.array([x["eval_cp"] for x in rows], np.float32),
        clock_ms=np.array([-1 if x["clock_ms"] is None else x["clock_ms"] for x in rows], np.float64),
        wp_loss=np.array([x["wp_loss"] for x in rows], np.float32),
    )
    return {"games": len(res), "moves": len(rows)}


# ================================================================= Maia tam geçiş (uç kova dışına uzatma için)
def _maia_init():
    from chessdex.engines.human import Maia2Model
    _W["maia"] = Maia2Model()


def maia_full_game(g: dict) -> list[tuple[int, np.ndarray, int]]:
    """Kullanıcı hamleleri için: (ply, tüm yasal hamlelerin 11 kovadaki log P matrisi (n_hamle, 11), oynanan hamle indeksi)."""
    from chessdex.engines.human import MAIA_CENTERS

    maia = _W["maia"]
    board = chess.Board()
    user_white = g["color"] == "white"
    out = []
    for ply, uci in enumerate(g["moves"]):
        if (board.turn == chess.WHITE) == user_white:
            moves, P = maia.forward(board.fen(), MAIA_CENTERS, g["opp_rating"])
            out.append((ply, np.log(P.T + 1e-6).astype(np.float32), moves.index(uci)))
        board.push_uci(uci)
    return out


def maiafull(in_path: str, npz_path: str, workers: int) -> dict:
    """bt_moves.npz'ye ragged dizi olarak ekler: maia_L (Σ n_hamle, 11), maia_off (n+1), maia_played (n)."""
    games = [json.loads(l) for l in open(in_path, encoding="utf-8") if l.strip()]
    d = dict(np.load(npz_path))
    with ProcessPoolExecutor(max_workers=workers, initializer=_maia_init) as ex:
        res = list(ex.map(maia_full_game, games, chunksize=4))
    ply = np.array([p for r in res for p, _, _ in r])
    game = np.concatenate([[k] * len(r) for k, r in enumerate(res)])
    if not (np.array_equal(ply, d["ply"]) and np.array_equal(game, d["game"])):
        raise SystemExit("hamle sırası npz ile uyuşmuyor")
    mats = [L for r in res for _, L, _ in r]
    d["maia_L"] = np.concatenate(mats)
    d["maia_off"] = np.concatenate([[0], np.cumsum([len(L) for L in mats])]).astype(np.int64)
    d["maia_played"] = np.array([i for r in res for _, _, i in r], np.int32)
    np.savez_compressed(npz_path, **d)
    return {"moves": int(len(ply)), "legal_total": int(d["maia_off"][-1])}


def _wp(cp: float) -> float:
    return 1.0 / (1.0 + math.exp(-0.00368208 * cp))


# ================================================================= tune
def weights(d, cfg: dict) -> np.ndarray:
    """Hamle ağırlıkları (kural sırası üretimdekiyle aynı: kitap/açılış → zorunlu → bitmiş → zaman)."""
    w = np.ones(len(d["ply"]))
    opening = d["ply"] < cfg["open_ply"]
    if cfg["book"]:
        opening |= d["book"] & (d["ply"] < 8)
    forced = (d["n_legal"] <= 1) | (d["grid"].min(axis=1) > cfg["forced_p"])
    decided = np.abs(d["eval_cp"]) > cfg["decided_cp"]
    trouble = (d["clock_ms"] >= 0) & (d["clock_ms"] < cfg["trouble_ms"])
    w[trouble] = cfg["trouble_w"]
    w[decided] = cfg["decided_w"]
    w[forced] = 0.0
    w[opening] = 0.0
    return w




def evaluate(d, cfg: dict, idx: np.ndarray, lam_m: float, lam_s: float, LM: np.ndarray, LS: np.ndarray | None,
             use_result: bool = True, boot: int = 0, prior: np.ndarray | None = None) -> dict:
    """Tüm `idx` oyunları değerlendirilir: tam ağırlıklı hamle < 15 ise maç kullanılmaz ve tahmin önseldir
    (üretimdeki gibi; burada senaryo yok, yalnız önsel). LM/LS: hamle başına GRID log olabilirlikleri (Maia / kayıp)."""
    from chessdex.measure.match import MIN_ANALYZABLE, result_log_lik
    from chessdex.measure.prior import default_prior

    w = weights(d, cfg)
    per_move = lam_m * LM
    if LS is not None and lam_s:
        per_move = per_move + lam_s * LS
    ll = np.zeros((len(d["rating"]), GRID.size))
    np.add.at(ll, d["game"], per_move * w[:, None])
    full = np.bincount(d["game"], weights=(w >= 1.0).astype(float), minlength=len(d["rating"]))
    prior = default_prior() if prior is None else prior
    edges = np.concatenate([[GRID[0] - 5.0], GRID + 5.0])
    q = np.empty((len(idx), 3))
    used = np.zeros(len(idx), bool)
    for j, g in enumerate(idx):
        lp = prior.copy()
        if full[g] >= MIN_ANALYZABLE:
            used[j] = True
            lp = lp + ll[g]
            if use_result:
                lp = lp + result_log_lik(float(d["score"][g]), float(d["opp_rating"][g]))
        p = np.exp(lp - lp.max())
        p /= p.sum()
        q[j] = np.interp([0.05, 0.5, 0.95], np.concatenate([[0.0], np.cumsum(p)]), edges)
    R = d["rating"][idx].astype(float)
    lo, med, hi = q[:, 0], q[:, 1], q[:, 2]
    err = med - R
    inside = (R >= lo) & (R <= hi)
    bands = {}
    for b0 in range(600, 2700, 300):
        m = (R >= b0) & (R < b0 + 300)
        if m.sum() >= 10:
            bands[f"{b0}-{b0 + 299}"] = {"n": int(m.sum()), "bias": round(float(err[m].mean()), 1),
                                          "mae": round(float(np.abs(err[m]).mean()), 1),
                                          "cov": round(float(inside[m].mean()), 3)}
    out = {"n": int(len(idx)), "match_used_frac": round(float(used.mean()), 3),
           "mae": round(float(np.abs(err).mean()), 1), "bias": round(float(err.mean()), 1),
           "coverage90": round(float(inside.mean()), 3), "width90": round(float((hi - lo).mean()), 1),
           "corr": round(float(np.corrcoef(med, R)[0, 1]), 3) if med.std() > 0 else 0.0, "bands": bands}
    if boot:
        rng = np.random.default_rng(0)
        bm, bc = [], []
        for _ in range(boot):
            k = rng.integers(0, len(err), len(err))
            bm.append(np.abs(err[k]).mean())
            bc.append(inside[k].mean())
        out["mae_ci95"] = [round(float(np.percentile(bm, 2.5)), 1), round(float(np.percentile(bm, 97.5)), 1)]
        out["coverage_ci95"] = [round(float(np.percentile(bc, 2.5)), 3), round(float(np.percentile(bc, 97.5)), 3)]
    return out


def objective(r: dict) -> float:
    """Plan: yalnızca MAE değil, kapsamanın %90'a yakınlığı da. 1 puan kapsama sapması ≈ 10 Elo MAE."""
    return r["mae"] + 1000.0 * abs(r["coverage90"] - 0.90)


PROD = {"open_ply": 0, "book": True, "forced_p": 0.9, "decided_cp": 500, "decided_w": 0.25,
        "trouble_ms": 10_000, "trouble_w": 0.3}
SPACE = {"open_ply": [0, 8, 12, 16, 20], "book": [True, False], "forced_p": [0.9, 0.7],
         "decided_cp": [300, 500, 800], "decided_w": [0.0, 0.25, 0.5, 1.0],
         "trouble_ms": [10_000, 30_000], "trouble_w": [0.0, 0.3, 1.0]}
LAMS_M = [0.0, 0.05, 0.1, 0.2, 0.5]
LAMS_S = [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]


def _search(d, train, LM, LS, lam_ms, lam_ss, cfg0) -> tuple[dict, float, float, list]:
    """Koordinat iniş: λ ızgarası → her kural tek tek → λ ızgarası; 2 tur. Yalnız eğitim oyunları."""
    cfg, history = dict(cfg0), []

    def score(c, lm, ls):
        return objective(evaluate(d, c, train, lm, ls, LM, LS))

    grid = {(lm, ls): score(cfg, lm, ls) for lm in lam_ms for ls in lam_ss}
    lam_m, lam_s = min(grid, key=grid.get)
    for _ in range(2):
        for key, vals in SPACE.items():
            sc = {v: score({**cfg, key: v}, lam_m, lam_s) for v in vals}
            cfg[key] = min(sc, key=sc.get)
            history.append({"param": key, "chosen": cfg[key], "scores": {str(k): round(v, 1) for k, v in sc.items()}})
        grid = {(lm, ls): score(cfg, lm, ls) for lm in lam_ms for ls in lam_ss}
        lam_m, lam_s = min(grid, key=grid.get)
        history.append({"param": "lambdas", "chosen": [lam_m, lam_s],
                        "scores": {f"{k[0]}/{k[1]}": round(v, 1) for k, v in grid.items()}})
    return cfg, lam_m, lam_s, history


def tune(npz: str, out_path: str, seed: int = 5, model_out: str | None = None) -> dict:
    from chessdex.measure.loss_model import LossModel
    from chessdex.measure.match import PROB_FLOOR

    d = dict(np.load(npz))
    n = len(d["rating"])
    perm = np.random.default_rng(seed).permutation(n)
    train, test = np.sort(perm[: int(0.7 * n)]), np.sort(perm[int(0.7 * n):])
    LM = np.log(np.clip(d["grid"].astype(np.float64), PROB_FLOOR, 1.0))
    LS, lm_info = None, None
    if "wp_loss" in d:
        # kayıp modeli YALNIZCA eğitim oyunlarından öğrenilir (test sızıntısı yok)
        tr_moves = np.isin(d["game"], train) & (d["ply"] >= 8)
        lmod = LossModel.fit(d["rating"][d["game"]][tr_moves], d["wp_loss"][tr_moves], d["eval_cp"][tr_moves])
        LS = lmod.batch_log_lik(d["wp_loss"], d["eval_cp"])
        lm_info = lmod.meta
        if model_out:
            lmod.save(model_out, source="lichess 2026-08 rapid backtest (eğitim %70)", bt_nodes=BT_NODES)
    variants = {"maia_only": ([l for l in LAMS_M if l > 0] + [0.7, 1.0], [0.0])}
    if LS is not None:
        variants["loss_only"] = ([0.0], [l for l in LAMS_S if l > 0])
        variants["maia+loss"] = (LAMS_M, LAMS_S)
    result = {"data": {"games": int(n), "moves": int(len(d["ply"])), "train": int(len(train)), "test": int(len(test))},
              "loss_model": lm_info,
              "prior_only_test": evaluate(d, PROD, test, 0.0, 0.0, LM, None, use_result=False, boot=1000),
              "baseline_prod_test": evaluate(d, PROD, test, 0.5, 0.0, LM, None, boot=1000),
              "variants": {}}
    for name, (lms, lss) in variants.items():
        cfg, lm, ls, hist = _search(d, train, LM, LS, lms, lss, PROD)
        result["variants"][name] = {
            "chosen": {"lambda_maia": lm, "lambda_loss": ls, **cfg},
            "train": evaluate(d, cfg, train, lm, ls, LM, LS),
            "test": evaluate(d, cfg, test, lm, ls, LM, LS, boot=1000),
            "test_no_result": evaluate(d, cfg, test, lm, ls, LM, LS, use_result=False),
            "history": hist,
        }
    Path(out_path).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect"); c.add_argument("url"); c.add_argument("out")
    c.add_argument("--per-band", type=int, default=60); c.add_argument("--max-mb", type=int, default=600)
    p = sub.add_parser("process"); p.add_argument("inp"); p.add_argument("out"); p.add_argument("--workers", type=int, default=8)
    mf = sub.add_parser("maiafull"); mf.add_argument("inp"); mf.add_argument("npz"); mf.add_argument("--workers", type=int, default=10)
    t = sub.add_parser("tune"); t.add_argument("npz"); t.add_argument("out")
    t.add_argument("--model-out", default=None, help="öğrenilen kayıp modelini buraya yaz (ör. data/loss_model.json)")
    args = ap.parse_args(argv)
    if args.cmd == "collect":
        res = collect(args.url, args.out, args.per_band, args.max_mb)
    elif args.cmd == "process":
        res = process(args.inp, args.out, args.workers)
    elif args.cmd == "maiafull":
        res = maiafull(args.inp, args.npz, args.workers)
    else:
        r = tune(args.npz, args.out, model_out=args.model_out)
        res = {"data": r["data"], "prior_only_test": r["prior_only_test"], "baseline_prod_test": r["baseline_prod_test"],
               **{k: {"chosen": v["chosen"], "test": v["test"]} for k, v in r["variants"].items()}}
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
