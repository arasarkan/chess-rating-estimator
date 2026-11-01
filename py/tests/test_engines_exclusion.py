import json

import chess
import numpy as np

from chessdex.engines import exclusion as X
from chessdex.engines.exclusion import OpeningBook, builtin_book, exclusion_reason

MID = "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P4/2PBPN2/PP1N1PPP/R1BQ1RK1 w - - 0 8"
G = np.full(261, 0.3)


def test_book_disabled_by_default_after_backtest():
    assert X.USE_BOOK is False
    assert exclusion_reason(0, chess.STARTING_FEN, "e2e4", G, 20, 600000) == (None, 1.0)


def test_book(monkeypatch):
    monkeypatch.setattr(X, "USE_BOOK", True)
    assert exclusion_reason(0, chess.STARTING_FEN, "e2e4", G, 20, 600000) == ("book", 0.0)
    b = chess.Board()
    b.push_san("e4")
    assert exclusion_reason(1, b.fen(), "c7c5", G, 20, 600000) == ("book", 0.0)
    assert exclusion_reason(0, chess.STARTING_FEN, "h2h4", G, 20, 600000) == (None, 1.0)
    assert exclusion_reason(8, chess.STARTING_FEN, "e2e4", G, 20, 600000) == (None, 1.0)
    assert len(builtin_book()) > 50


def test_book_json(tmp_path):
    p = tmp_path / "book.json"
    p.write_text(json.dumps({"lines": ["h4 a5"], "positions": {chess.STARTING_FEN: ["g2g4"]}}))
    bk = OpeningBook.from_json(p)
    assert bk.contains(chess.STARTING_FEN, "h2h4")
    assert bk.contains(chess.STARTING_FEN, "g2g4")
    assert not bk.contains(chess.STARTING_FEN, "e2e4")
    assert exclusion_reason(0, chess.STARTING_FEN, "h2h4", G, 0, 600000, book=str(p))[0] == "book"
    assert exclusion_reason(0, chess.STARTING_FEN, "e2e4", G, 0, 600000, book=bk) == (None, 1.0)


def test_forced_by_grid():
    gp = np.full(261, 0.95)
    assert exclusion_reason(30, MID, "d4c5", gp, 0, 600000) == ("forced", 0.0)
    gp[0] = 0.5
    assert exclusion_reason(30, MID, "d4c5", gp, 0, 600000) == (None, 1.0)


def test_forced_single_legal():
    fen = "7k/8/6K1/8/8/8/8/R7 b - - 0 1"
    b = chess.Board(fen)
    assert b.legal_moves.count() == 1
    mv = next(iter(b.legal_moves)).uci()
    assert exclusion_reason(30, fen, mv, None, None, None) == ("forced", 0.0)


def test_decided_and_time():
    assert exclusion_reason(30, MID, "d4c5", G, 650, 600000) == ("decided", X.DECIDED_WEIGHT)
    assert exclusion_reason(30, MID, "d4c5", G, -650, 600000) == ("decided", X.DECIDED_WEIGHT)
    assert exclusion_reason(30, MID, "d4c5", G, 100, X.TIME_TROUBLE_MS - 1) == ("time_trouble", X.TIME_TROUBLE_WEIGHT)
    assert exclusion_reason(30, MID, "d4c5", G, None, None) == (None, 1.0)
    assert exclusion_reason(30, MID, "d4c5", G, X.DECIDED_CP, X.TIME_TROUBLE_MS) == (None, 1.0)
