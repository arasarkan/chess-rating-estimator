"""Faz 1b: "Maia'ya karşı Maia". İnsan-hamle modeli bilinen θ'da sanal oyuncu oynatır,
bot ise tahmini seviyede oynar; maç olabilirliği θ'yı geri buluyor mu?

Maia-2 kurulu değilse HeuristicHumanModel kullanılır (yalnızca boru hattını doğrular).
Kullanım: python -m chessdex.sim.maia_vs_maia --games 60
"""
from __future__ import annotations

import argparse
import json

import chess
import numpy as np

from chessdex.engines.exclusion import exclusion_reason
from chessdex.engines.human import get_model, sample_move
from chessdex.measure.match import MoveEvidence, match_log_lik
from chessdex.measure.posterior import Posterior
from chessdex.measure.prior import default_prior

MAX_PLIES = 120


def play_game(model, theta: int, bot_level: int, rng: np.random.Generator, lam: float):
    board = chess.Board()
    user_white = bool(rng.integers(2))
    ev = []
    while not board.is_game_over(claim_draw=True) and board.ply() < MAX_PLIES:
        fen = board.fen()
        user_turn = (board.turn == chess.WHITE) == user_white
        mv = sample_move(model, fen, theta if user_turn else bot_level, bot_level if user_turn else theta, rng)
        if user_turn:
            grid = model.move_prob_grid(fen, mv, bot_level)
            reason, w = exclusion_reason(board.ply(), fen, mv, grid, None, 300_000)
            ev.append(MoveEvidence(board.ply(), grid, w, reason))
        board.push_uci(mv)
    ll, used = match_log_lik(ev, lam)
    return ll, used, len(ev)


def run(n_games: int = 60, seed: int = 7, lam: float = 0.5, noise: float = 150.0) -> dict:
    model = get_model()
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n_games):
        theta = int(rng.integers(60, 230)) * 10            # 600–2300
        bot = int(np.clip(round((theta + rng.normal(0, noise)) / 10) * 10, 400, 3000))
        ll, used, n = play_game(model, theta, bot, rng, lam)
        if not used:
            continue
        post = Posterior(default_prior()).update(ll)
        rows.append((theta, post.median(), post.quantile(0.05), post.quantile(0.95), n))
    a = np.array(rows)
    err = a[:, 1] - a[:, 0]
    return {"model": f"{model.name}-{model.version}", "lambda": lam, "games_used": len(rows),
            "mae": round(float(np.abs(err).mean()), 1), "bias": round(float(err.mean()), 1),
            "coverage90": round(float(((a[:, 0] >= a[:, 2]) & (a[:, 0] <= a[:, 3])).mean()), 3),
            "mean_width90": round(float((a[:, 3] - a[:, 2]).mean()), 1),
            "mean_user_moves": round(float(a[:, 4].mean()), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--lam", type=float, default=0.5)
    args = ap.parse_args()
    print(json.dumps(run(args.games, args.seed, args.lam), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
