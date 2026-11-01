"""Renk takası / ayna dönüşümlerinin özellik tabanlı testleri."""
import random

import chess
import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from chessdex.bank.models import BankItem
from chessdex.bank.scoring import score_attempt
from chessdex.bank.transforms import (
    apply_transform,
    color_swap,
    map_move,
    mirror,
    random_transform,
    transform_item,
    valid_transforms,
)


def _playout(seed: int, plies: int, line_len: int):
    """Rastgele oyundan pozisyon + oradan rastgele yasal hamle dizisi."""
    rng = random.Random(seed)
    b = chess.Board()
    for _ in range(plies):
        if b.is_game_over():
            break
        b.push(rng.choice(list(b.legal_moves)))
    start = chess.Board(b.fen())
    line = []
    for _ in range(line_len):
        if b.is_game_over():
            break
        m = rng.choice(list(b.legal_moves))
        line.append(m.uci())
        b.push(m)
    return start.fen(), line


def _signature(board: chess.Board):
    return (board.is_checkmate(), board.is_stalemate(), board.is_check(), board.legal_moves.count())


def _check_transform(fen, line, name):
    tfen, tline = apply_transform(fen, line, name)
    ob, tb = chess.Board(fen), chess.Board(tfen)
    assert tb.is_valid()
    assert _signature(ob) == _signature(tb)
    for u, tu in zip(line, tline):
        assert chess.Move.from_uci(tu) in tb.legal_moves, (name, fen, line)
        assert ob.is_capture(chess.Move.from_uci(u)) == tb.is_capture(chess.Move.from_uci(tu))
        ob.push_uci(u)
        tb.push_uci(tu)
        assert _signature(ob) == _signature(tb)
    # son pozisyon = orijinal son pozisyonun dönüşümü
    expect, _ = apply_transform(ob.fen(), [], name)
    assert chess.Board(expect).board_fen() == tb.board_fen()
    assert chess.Board(expect).turn == tb.turn


@settings(max_examples=150, deadline=None)
@given(seed=st.integers(0, 10**6), plies=st.integers(0, 120), line_len=st.integers(0, 6))
def test_color_swap_preserves_legality(seed, plies, line_len):
    fen, line = _playout(seed, plies, line_len)
    _check_transform(fen, line, "color_swap")


@settings(max_examples=150, deadline=None)
@given(seed=st.integers(0, 10**6), plies=st.integers(20, 160), line_len=st.integers(0, 6))
def test_mirror_and_both_when_valid(seed, plies, line_len):
    fen, line = _playout(seed, plies, line_len)
    if chess.Board(fen).castling_rights:
        with pytest.raises(ValueError):
            mirror(fen, line)
        assert valid_transforms(fen) == ["identity", "color_swap"]
        return
    _check_transform(fen, line, "mirror")
    _check_transform(fen, line, "both")


@settings(max_examples=60, deadline=None)
@given(seed=st.integers(0, 10**6), plies=st.integers(0, 120))
def test_involution(seed, plies):
    fen, line = _playout(seed, plies, 3)
    f2, l2 = color_swap(*color_swap(fen, line))
    assert chess.Board(f2).fen() == chess.Board(fen).fen() and l2 == line
    if not chess.Board(fen).castling_rights:
        f3, l3 = mirror(*mirror(fen, line))
        assert chess.Board(f3).fen() == chess.Board(fen).fen() and l3 == line


def test_color_swap_castling_and_ep():
    fen = "r3k2r/8/8/3pP3/8/8/8/R3K2R w Kq d6 0 1"
    tfen, tm = color_swap(fen, ["e5d6", "e1g1"])
    b = chess.Board(tfen)
    assert b.turn == chess.BLACK
    assert b.has_kingside_castling_rights(chess.BLACK) and b.has_queenside_castling_rights(chess.WHITE)
    assert not b.has_kingside_castling_rights(chess.WHITE)
    assert b.ep_square == chess.D3
    assert tm == ["e4d3", "e8g8"]
    assert chess.Move.from_uci("e4d3") in b.legal_moves  # geçerken alma korunur


def test_mirror_ep_and_promotion():
    fen = "8/1P5k/8/3pP3/8/8/8/K7 w - d6 0 1"
    tfen, tm = mirror(fen, ["e5d6", "b7b8q"])
    b = chess.Board(tfen)
    assert b.ep_square == chess.E6
    assert tm == ["d5e6", "g7g8q"]
    assert map_move("b7b8q", "both") == "g2g1q"


def test_mirror_rejects_castling():
    with pytest.raises(ValueError):
        mirror(chess.STARTING_FEN, ["e2e4"])


def test_random_transform_uses_valid_options():
    rng = np.random.default_rng(1)
    names = set()
    fen = "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"
    for _ in range(80):
        f, m, name = random_transform(fen, ["d1d8"], rng)
        names.add(name)
        b = chess.Board(f)
        b.push_uci(m[0])
        assert b.is_checkmate()
    assert names == {"identity", "color_swap", "mirror", "both"}
    for _ in range(20):
        _, _, name = random_transform(chess.STARTING_FEN, ["e2e4"], random.Random(_))
        assert name in ("identity", "color_swap")


def test_transform_item_keeps_scoring():
    it = BankItem(id="t", source="t", fen="6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1", solution=["d1d8"],
                  choices=["d1d8", "d1d2", "g1f1", "h2h3"], move_scores={"d1d8": 3, "d1d2": 1, "g1f1": 0, "h2h3": 2})
    for name in ("identity", "color_swap", "mirror", "both"):
        t = transform_item(it, name)
        assert t.meta["transform"] == name
        assert set(t.choices) == set(t.move_scores)
        assert score_attempt(t, [t.solution[0]], 1000) == (3, True)
