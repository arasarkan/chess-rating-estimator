"""Demo bankası: her senaryo yasal ve çözümü arama ile doğrulanmış olmalı."""
from collections import Counter

import chess
import pytest

from chessdex.bank import search as S
from chessdex.bank.loader import DEMO_PATH, demo_items, load_items
from chessdex.bank.models import KINDS

ITEMS = load_items(DEMO_PATH)


def test_bank_size_and_spread():
    assert len(ITEMS) >= 120
    assert len({it.id for it in ITEMS}) == len(ITEMS)
    kinds = Counter(it.kind for it in ITEMS)
    assert set(kinds) == set(KINDS)
    assert all(n >= 15 for n in kinds.values()), kinds
    ratings = [it.puzzle_rating for it in ITEMS]
    assert min(ratings) >= 600 and max(ratings) <= 2600
    assert min(ratings) <= 750 and max(ratings) >= 2350
    bands = Counter(int(r // 200) * 200 for r in ratings)
    assert all(bands.get(b, 0) >= 2 for b in range(600, 2600, 200)), bands


def test_demo_items_api():
    a, b = demo_items(), demo_items()
    assert len(a) == len(ITEMS)
    a[0].solution.append("zzzz")  # kopya döner, önbellek bozulmaz
    assert b[0].solution != a[0].solution


@pytest.mark.parametrize("it", ITEMS, ids=lambda it: it.id)
def test_item_legal_and_verified(it):
    assert it.source == "demo-generated"
    board = chess.Board(it.fen)
    assert board.is_valid() and not board.is_game_over()
    assert it.b == pytest.approx(-200 + it.puzzle_rating)
    # çözüm çizgisi yasal
    b = board.copy()
    for u in it.solution:
        assert chess.Move.from_uci(u) in b.legal_moves, (it.id, u)
        b.push_uci(u)
    assert len(it.solution) % 2 == 1  # oyuncu hamlesiyle biter

    motif = it.meta["motif"]
    if motif == "mate":
        n = it.meta["mate_in"]
        assert b.is_checkmate()
        assert len(it.solution) == 2 * n - 1
        assert S.mate_distance(board, n - 1) is None  # daha kısa mat yok
        # her oyuncu hamlesi kalan mesafeyi zorlar
        w = board.copy()
        for j in range(n):
            assert S.forces_mate(w, chess.Move.from_uci(it.solution[2 * j]), n - j), (it.id, j)
            w.push_uci(it.solution[2 * j])
            if 2 * j + 1 < len(it.solution):
                w.push_uci(it.solution[2 * j + 1])
        if n >= 2:
            # anahtar tek: mat-2 ve oyun sonunda tüm hamleler, orta oyun mat-3'te şah/alma adayları
            cands = None
            if n >= 3 and it.kind != "endgame":
                cands = [m for m in board.legal_moves if board.gives_check(m) or board.is_capture(m)]
            assert S.mate_keys(board, n, cands) == [chess.Move.from_uci(it.solution[0])]
    elif motif in ("material", "hanging"):
        scores = S.root_scores(board, it.meta["depth"])
        best = max(scores, key=scores.get)
        assert best == it.solution[0]
        v1 = scores[best]
        v2 = max((v for u, v in scores.items() if u != best), default=-S.INF)
        assert v1 - v2 >= 200
        assert v1 - S.material(board, board.turn) >= 250
    elif motif == "defense":
        assert it.kind == "defense"
        scores = S.root_scores(board, it.meta["depth"])
        best = max(scores, key=scores.get)
        assert best == it.solution[0]
        v2 = max((v for u, v in scores.items() if u != best), default=-S.INF)
        assert scores[best] - v2 >= 200
    elif motif == "positional":
        assert it.kind == "positional" and it.meta["demo_quality"] is True
        assert it.choices and len(it.choices) == 4 and len(set(it.choices)) == 4
        assert it.c == pytest.approx(0.25)
        assert set(it.move_scores) == set(it.choices)
        assert sorted(it.move_scores.values()) == [0, 1, 2, 3]
        assert it.move_scores[it.solution[0]] == 3
        for u in it.choices:
            assert chess.Move.from_uci(u) in board.legal_moves
    else:
        pytest.fail(f"bilinmeyen motif {motif}")

    if it.kind == "endgame":
        assert it.meta["tablebase_check"] == (chess.popcount(board.occupied) <= 7)
