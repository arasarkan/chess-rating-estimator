"""Maç olabilirliği: hamle başına iki sinyal λ'larla yumuşatılarak toplanır.

- Maia-2: P(hamle | pozisyon, θ)                         (λ = DEFAULT_LAMBDA)
- Stockfish kazanma olasılığı kaybı: P(kayıp kategorisi | θ) (λ = LOSS_LAMBDA; measure/loss_model.py)
λ'lar Faz 2 geriye dönük testinde seçildi (docs/results/backtest.md): tutulan 372 oyunda tek maçla MAE 250,
%90 kapsama 0.85 (yalnız Maia: 265; plan varsayılanları: 361)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .grid import GRID

DEFAULT_LAMBDA = 0.7       # Maia-2 hamle olabilirliği (docs/results/extremes.md)
LOSS_LAMBDA = 0.2          # Stockfish kayıp olabilirliği
MIN_ANALYZABLE = 15        # bundan az hamle → maç sinyali kullanılmaz
RESULT_WEIGHT = 0.5        # oyun sonucu zayıf olabilirlik
DRAW_WIDTH = 0.15          # beraberlik olasılığının tepe değeri (kaba)
PROB_FLOOR = 1e-4          # tek bir hamlenin olabilirliği çökertmesini önler


@dataclass
class MoveEvidence:
    ply: int
    grid_probs: np.ndarray      # (G,) P(m_t | s_t, θ)
    weight: float = 1.0         # hariç tutma kurallarından gelen ağırlık (0 = hariç)
    reason: str | None = None
    loss_ll: np.ndarray | None = None   # (G,) log P(kayıp kategorisi | θ); Stockfish yoksa None


def n_analyzable(moves: list[MoveEvidence]) -> int:
    return sum(1 for m in moves if m.weight >= 1.0)


def moves_log_lik(moves: list[MoveEvidence], lam: float = DEFAULT_LAMBDA,
                  lam_loss: float = LOSS_LAMBDA) -> np.ndarray:
    total = np.zeros(GRID.size)
    for m in moves:
        if m.weight <= 0:
            continue
        ll = lam * np.log(np.clip(m.grid_probs, PROB_FLOOR, 1.0))
        if m.loss_ll is not None:
            ll = ll + lam_loss * m.loss_ll
        total += m.weight * ll
    return total


def result_log_lik(score: float, bot_level: float) -> np.ndarray:
    """score: 1 kazandı, 0.5 berabere, 0 kaybetti (kullanıcı açısından)."""
    e = 1.0 / (1.0 + 10.0 ** (-(GRID - bot_level) / 400.0))
    p_draw = DRAW_WIDTH * 4 * e * (1 - e)
    p_win = (1 - p_draw) * e
    p_loss = (1 - p_draw) * (1 - e)
    p = {1.0: p_win, 0.5: p_draw, 0.0: p_loss}[score]
    return RESULT_WEIGHT * np.log(np.clip(p, 1e-12, 1.0))


def match_log_lik(moves: list[MoveEvidence], lam: float = DEFAULT_LAMBDA,
                  score: float | None = None, bot_level: float | None = None,
                  lam_loss: float = LOSS_LAMBDA) -> tuple[np.ndarray, bool]:
    """(log olabilirlik, kullanıldı mı). Analiz edilebilir hamle < 15 ise sıfır döner."""
    if n_analyzable(moves) < MIN_ANALYZABLE:
        return np.zeros(GRID.size), False
    ll = moves_log_lik(moves, lam, lam_loss)
    if score is not None and bot_level is not None:
        ll = ll + result_log_lik(score, bot_level)
    return ll, True
