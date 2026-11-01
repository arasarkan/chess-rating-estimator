"""Senaryo cevabı puanlama: k ∈ {0: yanlış, 1: yavaş doğru, 2: hızlı doğru}; kademelide 0–3."""
from __future__ import annotations

from typing import Sequence

import chess

from .models import BankItem


def _player_moves(item: BankItem, given: Sequence[str], include_opponent: bool) -> list[str]:
    if include_opponent:
        return list(given[0::2])
    return list(given)


def check_line(item: BankItem, player_moves: Sequence[str]) -> tuple[bool, bool]:
    """Oyuncu hamlelerini çözüme karşı yürütür → (şu ana kadar doğru mu, çözüm tamamlandı mı).

    Rakip cevapları çözümden (tek indeksler) uygulanır. Herhangi bir oyuncu hamlesinde
    mat eden hamle doğru kabul edilir ve çözümü bitirir (Lichess kuralı)."""
    board = chess.Board(item.fen)
    sol = item.solution
    for j, uci in enumerate(player_moves):
        i = 2 * j
        if i >= len(sol):
            return True, True  # fazla hamle yok sayılır
        try:
            mv = chess.Move.from_uci(uci)
        except ValueError:
            return False, True
        if mv not in board.legal_moves:
            return False, True
        if uci == sol[i]:
            board.push(mv)
        else:
            board.push(mv)
            if board.is_checkmate():
                return True, True
            return False, True
        if board.is_checkmate() or i + 1 >= len(sol):
            return True, True
        board.push(chess.Move.from_uci(sol[i + 1]))  # rakibin cevabı
    return True, False


def score_attempt(
    item: BankItem,
    given_moves: Sequence[str],
    elapsed_ms: int,
    *,
    include_opponent: bool = False,
) -> tuple[int, bool]:
    """Cevabı puanlar → (k, doğru_mu).

    `given_moves` varsayılan olarak yalnızca oyuncu hamleleridir; `include_opponent=True` ise
    tam çizgi (oyuncu + rakip) verilmiştir. Kademeli senaryolarda (`item.move_scores`)
    ilk hamlenin puanı (0–3) döner; doğru = en yüksek puan."""
    moves = _player_moves(item, given_moves, include_opponent)
    if item.move_scores:
        if not moves:
            return 0, False
        s = int(item.move_scores.get(moves[0], 0))
        return s, s >= max(item.move_scores.values())
    if not moves:
        return 0, False
    ok, done = check_line(item, moves)
    if not (ok and done):
        return 0, False
    fast = item.time_fast_ms is not None and elapsed_ms <= item.time_fast_ms
    return (2 if fast else 1), True


def opponent_reply(item: BankItem, player_moves: Sequence[str]) -> str | None:
    """Kısmi cevapta (şu ana kadar doğruysa) rakibin sıradaki cevabı; yoksa None."""
    ok, done = check_line(item, player_moves)
    if not ok or done:
        return None
    i = 2 * len(player_moves) - 1
    return item.solution[i] if 0 <= i < len(item.solution) else None
