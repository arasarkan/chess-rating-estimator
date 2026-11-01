"""Demo bankası için küçük arama araçları: mat arama ve malzeme odaklı alfa-beta.

Hızlı değil, yalnızca çevrimdışı üretim ve test doğrulaması için.
"""
from __future__ import annotations

import chess

VALUES = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 310, chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}
MATE = 100_000
INF = 10**9
CENTER = chess.BB_D4 | chess.BB_E4 | chess.BB_D5 | chess.BB_E5


# ---------------------------------------------------------------- mat arama

def mating_moves(board: chess.Board) -> list[chess.Move]:
    """Tek hamlede mat eden hamleler."""
    out = []
    for m in board.legal_moves:
        if board.gives_check(m):
            board.push(m)
            if board.is_checkmate():
                out.append(m)
            board.pop()
    return out


def _ordered(board: chess.Board) -> list[chess.Move]:
    # Önce şahlar, sonra almalar: mat aramasında erken bulur.
    ms = list(board.legal_moves)
    ms.sort(key=lambda m: (not board.gives_check(m), not board.is_capture(m)))
    return ms


def forces_mate(board: chess.Board, move: chess.Move, n: int) -> bool:
    """`move` oynandıktan sonra her savunmaya karşı en çok n hamlede (bu hamle dahil) mat var mı?"""
    board.push(move)
    try:
        if board.is_checkmate():
            return True
        if n <= 1 or board.is_game_over():
            return False
        for r in board.legal_moves:
            board.push(r)
            ok = has_mate_in(board, n - 1)
            board.pop()
            if not ok:
                return False
        return True
    finally:
        board.pop()


def has_mate_in(board: chess.Board, n: int) -> bool:
    """Sıradaki taraf en çok n hamlede zorla mat edebilir mi?"""
    if n <= 0:
        return False
    if n == 1:
        return bool(mating_moves(board))
    for m in _ordered(board):
        if forces_mate(board, m, n):
            return True
    return False


def mate_keys(board: chess.Board, n: int, candidates: list[chess.Move] | None = None) -> list[chess.Move]:
    """En çok n hamlede zorla mat eden tüm ilk hamleler."""
    ms = candidates if candidates is not None else list(board.legal_moves)
    return [m for m in ms if forces_mate(board, m, n)]


def mate_distance(board: chess.Board, max_n: int) -> int | None:
    """En kısa zorlamalı mat mesafesi (≤ max_n) ya da None."""
    for n in range(1, max_n + 1):
        if has_mate_in(board, n):
            return n
    return None


# ---------------------------------------------------------------- malzeme araması

def material(board: chess.Board, color: chess.Color) -> int:
    """`color` açısından malzeme farkı."""
    s = 0
    for pt, v in VALUES.items():
        s += v * (chess.popcount(board.pieces_mask(pt, color)) - chess.popcount(board.pieces_mask(pt, not color)))
    return s


def _mvv_lva(board: chess.Board, m: chess.Move) -> int:
    victim = board.piece_type_at(m.to_square)
    if victim is None and board.is_en_passant(m):
        victim = chess.PAWN
    attacker = board.piece_type_at(m.from_square)
    v = VALUES.get(victim, 0) * 10 - VALUES.get(attacker, 0) // 10
    if m.promotion:
        v += VALUES[m.promotion] * 10
    return v


def _qsearch(board: chess.Board, alpha: int, beta: int, ply: int, qdepth: int, evalf) -> int:
    if board.is_checkmate():
        return -MATE + ply
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    in_check = board.is_check()
    if not in_check:
        stand = evalf(board)
        if stand >= beta or qdepth <= 0:
            return stand
        alpha = max(alpha, stand)
        moves = [m for m in board.legal_moves if board.is_capture(m) or m.promotion]
    else:
        if qdepth <= -4:  # şah zinciri sınırı
            return evalf(board)
        moves = list(board.legal_moves)
    moves.sort(key=lambda m: -_mvv_lva(board, m))
    for m in moves:
        board.push(m)
        sc = -_qsearch(board, -beta, -alpha, ply + 1, qdepth - 1, evalf)
        board.pop()
        if sc >= beta:
            return sc
        alpha = max(alpha, sc)
    return alpha


def eval_material(board: chess.Board) -> int:
    """Sıradaki taraf açısından malzeme."""
    return material(board, board.turn)


def eval_positional(board: chess.Board) -> int:
    """Malzeme + hareketlilik + merkez (demo kalitesi)."""
    us = board.turn
    mob_us = board.pseudo_legal_moves.count()
    board.turn = not us
    mob_them = board.pseudo_legal_moves.count()
    board.turn = us
    center = 0
    for sq in chess.scan_forward(CENTER):
        center += len(board.attackers(us, sq)) - len(board.attackers(not us, sq))
    return material(board, us) + 4 * (mob_us - mob_them) + 6 * center


def negamax(board: chess.Board, depth: int, alpha: int = -INF, beta: int = INF, ply: int = 0,
            evalf=eval_material, qdepth: int = 6) -> int:
    """Alfa-beta + yakalama aramalı negamax; skor sıradaki taraf açısından."""
    if board.is_checkmate():
        return -MATE + ply
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    if depth <= 0:
        return _qsearch(board, alpha, beta, ply, qdepth, evalf)
    moves = list(board.legal_moves)
    moves.sort(key=lambda m: (-(board.gives_check(m)) * 500 - _mvv_lva(board, m)))
    best = -INF
    for m in moves:
        board.push(m)
        sc = -negamax(board, depth - 1, -beta, -alpha, ply + 1, evalf, qdepth)
        board.pop()
        if sc > best:
            best = sc
        alpha = max(alpha, sc)
        if alpha >= beta:
            break
    return best


def root_scores(board: chess.Board, depth: int, evalf=eval_material) -> dict[str, int]:
    """Her kök hamle için tam pencereli skor (hamleyi yapan taraf açısından)."""
    out: dict[str, int] = {}
    for m in board.legal_moves:
        board.push(m)
        out[m.uci()] = -negamax(board, depth - 1, ply=1, evalf=evalf)
        board.pop()
    return out


def is_mate_score(s: int) -> bool:
    return abs(s) > MATE - 1000
