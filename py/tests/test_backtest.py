import numpy as np
import pytest

from chessdex.measure.grid import GRID
from chessdex.sim.backtest import PROD, _stable, evaluate, objective, weights


def fake(n_games=40, moves=30, seed=0):
    """θ'yı bilinen sentetik oyunlar: hamle olasılığı θ civarında tepe yapan ızgara."""
    rng = np.random.default_rng(seed)
    R = rng.uniform(800, 2000, n_games)
    rows = n_games * moves
    game = np.repeat(np.arange(n_games), moves).astype(np.int32)
    centers = R[game] + rng.normal(0, 300, rows)
    grid = (0.05 + 0.25 * np.exp(-0.5 * ((GRID[None, :] - centers[:, None]) / 400) ** 2)).astype(np.float32)
    return {"rating": R.astype(np.float32), "opp_rating": R.astype(np.float32), "score": np.full(n_games, 0.5, np.float32),
            "game": game, "ply": np.tile(np.arange(0, 2 * moves, 2), n_games).astype(np.int16), "grid": grid,
            "book": np.zeros(rows, bool), "n_legal": np.full(rows, 30, np.int16),
            "eval_cp": np.zeros(rows, np.float32), "clock_ms": np.full(rows, 300_000.0)}


def test_weights_rule_order():
    d = fake(2, 10)
    d["eval_cp"][3] = 900
    d["clock_ms"][4] = 5_000
    d["n_legal"][5] = 1
    d["eval_cp"][5] = 900          # zorunlu, bitmişten önce gelir
    w = weights(d, {**PROD, "open_ply": 4})
    assert w[0] == 0 and w[1] == 0  # ply 0, 2 < 4 → açılış
    assert w[3] == PROD["decided_w"] and w[4] == PROD["trouble_w"] and w[5] == 0.0 and w[6] == 1.0


def test_evaluate_recovers_ratings_and_lambda_widens():
    d = fake()
    idx = np.arange(len(d["rating"]))
    LM = np.log(d["grid"].astype(float))
    narrow = evaluate(d, PROD, idx, 1.0, 0.0, LM, None, use_result=False)
    wide = evaluate(d, PROD, idx, 0.1, 0.0, LM, None, use_result=False)
    assert narrow["n"] == len(idx) and narrow["match_used_frac"] == 1.0
    prior_only = evaluate(d, PROD, idx, 0.0, 0.0, LM, None, use_result=False)
    assert narrow["mae"] < prior_only["mae"]
    assert narrow["mae"] < 250
    assert wide["width90"] > narrow["width90"]
    assert objective(narrow) == pytest.approx(narrow["mae"] + 1000 * abs(narrow["coverage90"] - 0.9))


def test_stable_rating_proxy():
    assert _stable(1500, 1500, 1.0, "+6")        # K = 12
    assert not _stable(1500, 1500, 1.0, "+20")   # K = 40 → kararsız (yüksek RD)
    assert not _stable(1500, 1500, 0.5, "0")     # sürpriz yok → hesaplanamaz
    assert not _stable(1500, 1500, 1.0, None)
