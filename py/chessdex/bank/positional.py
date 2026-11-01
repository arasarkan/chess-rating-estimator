"""Pozisyonel "en iyi plan" senaryoları: gerçek rapid oyunlardan pozisyon → Stockfish etiketi → veriden zorluk.

Adımlar (her biri JSONL üretir, belirlenimci):
  collect   Lichess aylık PGN'inin başını akışla okur; rapid oyunlardan, oyuncunun karar verdiği sakin
            orta oyun pozisyonlarını (oyuncu rating'i, oynanan hamle, kalan süre ile) rating bandı kotasıyla toplar.
  label     Stockfish (sabit düğüm, tek iş parçacığı, çoklu varyant) ile etiketler; taktik pozisyonları eler,
            4 şık ve 0–3 puanları üretir. Paralel süreç havuzu.
  calibrate Tanı: oyunlarda P(oyuncu en iyi hamleyi buldu) için lojistik model + bant bazında puan oranları.
            2026-09 doğru verisinde rating etkisi belirgin (en iyi hamle oranı 0.31 → 0.71; w_R = 0.32).
            (Önceki "etki yok / seçim yanlılığı" sonucu PGN okuma hatasıydı; bkz. pgnstream.py.)
  build     Senaryoları yazar. Geçici zorluk "köken rating"idir: pozisyonun ortaya çıktığı oyundaki oyuncu rating'i R.
            Her bantta P(puan ≥ 2 | kendi pozisyonu) ≈ 0.66 olduğundan b = R − ORIGIN_SHIFT (L(a(R−b)) = 0.66).
            a = 1 (plan varsayılanı). Gerçek kalibrasyon: Maia-2 veya pilot cevapları.

Kullanım (py/ dizininden):
  python -m chessdex.bank.positional collect URL ../data/raw/pos_candidates.jsonl --per-band 700
  python -m chessdex.bank.positional label ../data/raw/pos_candidates.jsonl ../data/raw/pos_labeled.jsonl --workers 16
  python -m chessdex.bank.positional calibrate ../data/raw/pos_labeled.jsonl ../data/raw/pos_model.json
  python -m chessdex.bank.positional build ../data/raw/pos_labeled.jsonl ../data/raw/pos_model.json data/positional.jsonl
"""
from __future__ import annotations

import argparse
import atexit
import json
import math
import random
import sys
import threading
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import numpy as np

from .models import BankItem

# ---- toplama ----
RAPID_MIN_BASE_S = 480            # Lichess rapid: tahmini süre 8–25 dk
RAPID_MAX_BASE_S = 1500
PLY_MIN, PLY_MAX = 16, 70         # açılış kitabı sonrası, oyun sonu öncesi
MIN_CLOCK_S = 60                  # zaman sıkışmasındaki kararlar gürültülü
MIN_PIECES = 14                   # orta oyun
BAND_LO, BAND_HI, BAND_W = 600, 2700, 100
POS_PER_GAME = 1

# ---- etiketleme ----
LABEL_NODES = 400_000             # etiketleme için (canlı puanlamadaki 1M'den ucuz; etiket bir kez üretilip saklanır)
MULTIPV = 8
MAX_ABS_EVAL_CP = 250             # kabaca dengeli (kazanma olasılığı ~%28–72); gerçek oyunlarda ±150 verimi %19a düşürüyor
MAX_TOP_GAP = 0.20                # en iyi ile ikinci arasında bundan büyük fark → "tek hamle" taktiği, pozisyonel değil
SCORE_EDGES = (0.02, 0.06, 0.15)  # kazanma olasılığı kaybı → 3 / 2 / 1 / 0 puan
N_CHOICES = 4


def wp(cp: int) -> float:
    return 1.0 / (1.0 + math.exp(-0.00368208 * cp))


def loss_score(loss: float) -> int:
    for s, edge in zip((3, 2, 1), SCORE_EDGES):
        if loss <= edge:
            return s
    return 0


# =========================================================== collect
def _rapid(h: chess.pgn.Headers) -> bool:
    if "Rated Rapid" not in h.get("Event", "") or h.get("Termination") != "Normal":
        return False
    try:
        base, inc = (int(x) for x in h.get("TimeControl", "-").split("+"))
    except ValueError:
        return False
    est = base + 40 * inc
    return RAPID_MIN_BASE_S <= est <= RAPID_MAX_BASE_S and h.get("WhiteRatingDiff") and h.get("BlackRatingDiff")


def _candidates(game: chess.pgn.Game, rng: random.Random) -> list[dict]:
    h = game.headers
    ratings = {chess.WHITE: int(h["WhiteElo"]), chess.BLACK: int(h["BlackElo"])}
    out = []
    board = game.board()
    for node in game.mainline():
        ply = board.ply()
        move = node.move
        clk = node.clock()
        if (PLY_MIN <= ply <= PLY_MAX and clk is not None and clk >= MIN_CLOCK_S
                and not board.is_check() and len(board.piece_map()) >= MIN_PIECES
                and board.legal_moves.count() >= 8):
            out.append({"fen": board.fen(), "played": move.uci(), "rating": ratings[board.turn],
                        "opp_rating": ratings[not board.turn], "clock_s": clk, "ply": ply,
                        "game": h.get("Site", "")})
        board.push(move)
    rng.shuffle(out)
    return out[:POS_PER_GAME]


def collect(url: str, out_path: str, per_band: int, max_mb: int, seed: int = 7) -> dict:
    from .pgnstream import stream_games

    rng = random.Random(seed)
    counts: dict[int, int] = {}
    want = {b: per_band for b in range(BAND_LO, BAND_HI, BAND_W)}
    n_games = n_rapid = 0
    with open(out_path, "w", encoding="utf-8") as out:
        for raw in stream_games(url, max_mb):
            h = raw.headers
            n_games += 1
            if not _rapid(h):
                continue
            n_rapid += 1
            try:
                band_w = int(h["WhiteElo"]) // BAND_W * BAND_W
                band_b = int(h["BlackElo"]) // BAND_W * BAND_W
            except (KeyError, ValueError):
                continue
            if counts.get(band_w, 0) >= want.get(band_w, 0) and counts.get(band_b, 0) >= want.get(band_b, 0):
                continue
            game = raw.parse()                    # başlık ve hamleler AYNI oyun metninden (pgnstream)
            if game is None or game.headers.get("Site") != h.get("Site"):
                continue
            for c in _candidates(game, rng):
                band = c["rating"] // BAND_W * BAND_W
                if counts.get(band, 0) < want.get(band, 0):
                    counts[band] = counts.get(band, 0) + 1
                    out.write(json.dumps(c) + "\n")
            if all(counts.get(b, 0) >= n for b, n in want.items()):
                break
    return {"games_read": n_games, "rapid": n_rapid, "positions": sum(counts.values()),
            "per_band": dict(sorted(counts.items()))}


# =========================================================== label
_ENGINE = None


def _engine(path: str):
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = chess.engine.SimpleEngine.popen_uci(path)
        _ENGINE.configure({"Threads": 1, "Hash": 16})
        # İşçi süreç çıkarken motoru kapat; yoksa daemon olmayan iş parçacığı havuzun kapanmasını kilitler
        getattr(threading, "_register_atexit", atexit.register)(_ENGINE.quit)
    return _ENGINE


def _pov_cp(score: chess.engine.PovScore, turn: bool) -> int:
    return score.pov(turn).score(mate_score=100_000)


def label_one(args) -> dict | None:
    rec, path, nodes = args
    eng = _engine(path)
    board = chess.Board(rec["fen"])
    infos = eng.analyse(board, chess.engine.Limit(nodes=nodes), multipv=MULTIPV, game=object())
    moves = {}
    for info in infos:
        if "pv" in info and info["pv"]:
            moves[info["pv"][0].uci()] = _pov_cp(info["score"], board.turn)
    if not moves:
        return None
    played = rec["played"]
    if played not in moves:
        info = eng.analyse(board, chess.engine.Limit(nodes=nodes), root_moves=[chess.Move.from_uci(played)],
                           game=object())
        moves[played] = _pov_cp(info["score"], board.turn)
    best_cp = max(moves.values())
    wbest = wp(best_cp)
    loss = {m: max(0.0, wbest - wp(cp)) for m, cp in moves.items()}
    ranked = sorted(moves, key=lambda m: (-moves[m], m))
    best = ranked[0]
    second_gap = loss[ranked[1]] if len(ranked) > 1 else 1.0
    bm = chess.Move.from_uci(best)
    feats = {
        "abs_eval": abs(best_cp) if abs(best_cp) < 100_000 else 10_000,
        "gap2": second_gap,
        "n_good": sum(1 for m in loss if loss[m] <= SCORE_EDGES[1]),
        "n_legal": board.legal_moves.count(),
        "pieces": len(board.piece_map()),
        "best_capture": board.is_capture(bm),
        "best_check": board.gives_check(bm),
    }
    return {**rec, "evals": moves, "loss": loss, "best": best, "played_loss": loss[played],
            "played_score": loss_score(loss[played]), "features": feats,
            "label": {"engine": "Stockfish 19", "nodes": nodes, "multipv": MULTIPV}}


def is_positional(r: dict) -> bool:
    f = r["features"]
    return (f["abs_eval"] <= MAX_ABS_EVAL_CP and not f["best_capture"] and not f["best_check"]
            and f["gap2"] <= MAX_TOP_GAP and len(r["evals"]) >= N_CHOICES)


def choose_options(r: dict, rng: random.Random) -> dict[str, int] | None:
    """Tam bir 3 puanlık şık + biri ≤1 puanlı olmak üzere 3 çeldirici. İnsan hatası (oynanan kötü hamle) tercih edilir."""
    scores = {m: loss_score(l) for m, l in r["loss"].items()}
    best = r["best"]
    others = [m for m in sorted(scores) if m != best and scores[m] < 3]
    if len(others) < N_CHOICES - 1 or min(scores[m] for m in others) > 1:
        return None
    pick: list[str] = []
    if r["played"] != best and r["played"] in others:
        pick.append(r["played"])
    low = [m for m in others if scores[m] <= 1 and m not in pick]
    if not any(scores[m] <= 1 for m in pick) and low:
        pick.append(rng.choice(low))
    rest = [m for m in others if m not in pick]
    rng.shuffle(rest)
    rest.sort(key=lambda m: -scores[m])             # kalan yerleri en makul (yüksek puanlı) hamlelerle doldur
    pick += rest[: N_CHOICES - 1 - len(pick)]
    return {best: 3, **{m: scores[m] for m in pick}}


def label(in_path: str, out_path: str, workers: int, nodes: int, engine_path: str | None) -> dict:
    from chessdex.engines.stockfish import find_stockfish

    path = find_stockfish(engine_path)
    if path is None:
        raise SystemExit("Stockfish bulunamadı (python scripts/setup.py)")
    recs = [json.loads(l) for l in open(in_path, encoding="utf-8") if l.strip()]
    n_ok = 0
    with ProcessPoolExecutor(max_workers=workers) as ex, open(out_path, "w", encoding="utf-8") as out:
        for i, r in enumerate(ex.map(label_one, [(rec, path, nodes) for rec in recs], chunksize=8)):
            if r is not None:
                out.write(json.dumps(r) + "\n")
                n_ok += 1
            if (i + 1) % 1000 == 0:
                print(f"  {i + 1}/{len(recs)}", file=sys.stderr, flush=True)
    return {"input": len(recs), "labeled": n_ok}


# =========================================================== calibrate
FEATURES = ("gap2", "n_good_frac", "abs_eval_100", "pieces_10")


def feature_vec(r: dict) -> list[float]:
    f = r["features"]
    return [f["gap2"], f["n_good"] / max(f["n_legal"], 1), f["abs_eval"] / 100.0, f["pieces"] / 10.0]


def calibrate(in_path: str, out_path: str) -> dict:
    """Tüm etiketli pozisyonlarda (pozisyonel olsun olmasın, en çok veri için) P(oyuncu en iyi hamleyi oynadı)."""
    from scipy.optimize import minimize

    rows = [json.loads(l) for l in open(in_path, encoding="utf-8") if l.strip()]
    rows = [r for r in rows if is_positional(r)]
    X = np.array([[1.0, (r["rating"] - 1500) / 400.0, *feature_vec(r)] for r in rows])
    y = np.array([1.0 if r["played_score"] == 3 else 0.0 for r in rows])

    def nll(w):
        z = X @ w
        return float(np.sum(np.logaddexp(0, z) - y * z)) + 1e-3 * float(w @ w)

    def grad(w):
        p = 1 / (1 + np.exp(-(X @ w)))
        return X.T @ (p - y) + 2e-3 * w

    res = minimize(nll, np.zeros(X.shape[1]), jac=grad, method="L-BFGS-B")
    w = res.x
    # hamle bazlı rating etkisinin kontrolü: bant başına gözlenen "en iyi hamle" oranı
    bands = {}
    for lo in range(BAND_LO, BAND_HI, 300):
        m = (X[:, 1] * 400 + 1500 >= lo) & (X[:, 1] * 400 + 1500 < lo + 300)
        if m.any():
            bands[f"{lo}-{lo + 299}"] = round(float(y[m].mean()), 3)
    model = {"w0": w[0], "w_R": w[1], "w": dict(zip(FEATURES, w[2:].tolist())), "n": int(len(y)),
             "base_rate": float(y.mean()), "best_rate_by_band": bands, "a": float(w[1] / math.log(10))}
    Path(out_path).write_text(json.dumps(model, indent=1), encoding="utf-8")
    return model


def difficulty(r: dict, model: dict) -> float:
    lin = model["w0"] + sum(model["w"][k] * v for k, v in zip(FEATURES, feature_vec(r)))
    return 1500.0 - 400.0 * lin / model["w_R"]


# =========================================================== build
A_MIN, A_MAX = 0.3, 1.5
B_MIN, B_MAX = 300.0, 2900.0
ORIGIN_P2 = 0.66                                             # gözlenen P(puan ≥ 2) oyuncunun kendi pozisyonunda
ORIGIN_SHIFT = 400.0 * math.log10(ORIGIN_P2 / (1 - ORIGIN_P2))   # ≈ 115 Elo


def origin_difficulty(r: dict) -> float:
    return float(r["rating"]) - ORIGIN_SHIFT


def build(in_path: str, model_path: str, out_path: str, seed: int = 11, method: str = "origin") -> dict:
    """method: 'origin' (varsayılan, geçici) ya da 'logistic' (yalnızca rating etkisi anlamlıysa)."""
    model = json.loads(Path(model_path).read_text(encoding="utf-8"))
    rng = random.Random(seed)
    if method == "logistic" and model["a"] < A_MIN:
        raise SystemExit(f"lojistik modelde rating etkisi yok (a={model['a']:.3f}); 'origin' kullanın")
    a = 1.0 if method == "origin" else float(np.clip(model["a"], A_MIN, A_MAX))
    n, seen = 0, set()
    with open(out_path, "w", encoding="utf-8") as out:
        for line in open(in_path, encoding="utf-8"):
            r = json.loads(line)
            key = " ".join(r["fen"].split()[:4])
            if not is_positional(r) or key in seen:
                continue
            opts = choose_options(r, rng)
            if opts is None:
                continue
            seen.add(key)
            choices = sorted(opts)
            rng.shuffle(choices)
            raw_b = origin_difficulty(r) if method == "origin" else difficulty(r, model)
            b = float(np.clip(raw_b, B_MIN, B_MAX))
            item = BankItem(
                id=f"pos:{r['game'].rsplit('/', 1)[-1]}:{r['ply']}",
                source="lichess-games+stockfish", fen=r["fen"], solution=[r["best"]], kind="positional",
                themes=["positional"], puzzle_rating=b, choices=choices, move_scores=opts, b=b, a=a,
                meta={"player_rating": r["rating"], "played": r["played"], "played_score": r["played_score"],
                      "loss": {m: round(r["loss"][m], 4) for m in opts}, "label": r["label"],
                      "b_source": "origin-rating-v1" if method == "origin" else "game-logistic-v1",
                      "provisional": True},
            )
            out.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
            n += 1
    return {"items": n, "a": a, "method": method}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect"); c.add_argument("url"); c.add_argument("out")
    c.add_argument("--per-band", type=int, default=700); c.add_argument("--max-mb", type=int, default=600)
    l = sub.add_parser("label"); l.add_argument("inp"); l.add_argument("out")
    l.add_argument("--workers", type=int, default=8); l.add_argument("--nodes", type=int, default=LABEL_NODES)
    l.add_argument("--engine", default=None)
    k = sub.add_parser("calibrate"); k.add_argument("inp"); k.add_argument("out")
    b = sub.add_parser("build"); b.add_argument("inp"); b.add_argument("model"); b.add_argument("out")
    b.add_argument("--method", default="origin", choices=["origin", "logistic"])
    args = ap.parse_args(argv)
    if args.cmd == "collect":
        res = collect(args.url, args.out, args.per_band, args.max_mb)
    elif args.cmd == "label":
        res = label(args.inp, args.out, args.workers, args.nodes, args.engine)
    elif args.cmd == "calibrate":
        res = calibrate(args.inp, args.out)
    else:
        res = build(args.inp, args.model, args.out, method=args.method)
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
