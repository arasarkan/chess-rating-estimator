"""score_attempt testleri."""
import chess

from chessdex.bank.models import BankItem, default_time_fast_ms
from chessdex.bank.scoring import check_line, opponent_reply, score_attempt

# Mat-2 (fixture T0002, kurulum sonrası): Fe6+ Şh7 Vh5#
_b = chess.Board("rn3bkr/p1p3p1/1p2p3/5pQ1/2B3n1/N6P/PPK4R/1RB1N3 b - - 1 21")
_b.push_uci("g4h2")
MATE2 = BankItem(id="m2", source="t", fen=_b.fen(),
                 solution=["c4e6", "g8h7", "g5h5"], puzzle_rating=1400, time_fast_ms=10_000)

# Birden çok mat eden hamle: Va8#, Vg7#, Vh7# (siyah şah h8)
MULTI_MATE = BankItem(id="mm", source="t", fen="7k/Q7/6K1/8/8/8/8/8 w - - 0 1", solution=["a7a8"],
                      puzzle_rating=700, time_fast_ms=5_000)


def test_fast_slow_wrong():
    assert score_attempt(MATE2, ["c4e6", "g5h5"], 5_000) == (2, True)
    assert score_attempt(MATE2, ["c4e6", "g5h5"], 20_000) == (1, True)
    assert score_attempt(MATE2, ["g5g6", "g5h5"], 5_000) == (0, False)


def test_incomplete_and_illegal():
    assert score_attempt(MATE2, ["c4e6"], 1_000) == (0, False)
    assert score_attempt(MATE2, [], 1_000) == (0, False)
    assert score_attempt(MATE2, ["a1a8"], 1_000) == (0, False)
    assert score_attempt(MATE2, ["xx"], 1_000) == (0, False)


def test_full_line_format():
    assert score_attempt(MATE2, ["c4e6", "g8h7", "g5h5"], 1_000, include_opponent=True) == (2, True)


def test_alternative_mate_accepted():
    assert score_attempt(MULTI_MATE, ["a7g7"], 1_000) == (2, True)
    assert score_attempt(MULTI_MATE, ["a7h7"], 1_000) == (2, True)
    assert score_attempt(MULTI_MATE, ["a7b7"], 1_000) == (0, False)


def test_partial_flow():
    assert check_line(MATE2, ["c4e6"]) == (True, False)
    assert opponent_reply(MATE2, ["c4e6"]) == "g8h7"
    assert opponent_reply(MATE2, ["g5g6"]) is None
    assert opponent_reply(MATE2, ["c4e6", "g5h5"]) is None


def test_graded_positional():
    it = BankItem(id="p", source="t", fen=chess.STARTING_FEN, solution=["e2e4"], kind="positional",
                  choices=["e2e4", "d2d4", "a2a3", "g1h3"], move_scores={"e2e4": 3, "d2d4": 2, "a2a3": 1, "g1h3": 0})
    assert it.c == 0.25
    assert score_attempt(it, ["e2e4"], 99_999) == (3, True)
    assert score_attempt(it, ["d2d4"], 1) == (2, False)
    assert score_attempt(it, ["g1h3"], 1) == (0, False)
    assert score_attempt(it, ["b2b3"], 1) == (0, False)  # seçenek dışı


def test_default_time_threshold_monotone():
    assert default_time_fast_ms(600, 1) < default_time_fast_ms(1500, 1) < default_time_fast_ms(2500, 1)
    assert default_time_fast_ms(1500, 1) < default_time_fast_ms(1500, 5)
