import math
import subprocess
import sys
from pathlib import Path

import chess
import pytest

from chessdex.engines.stockfish import Analyzer, win_prob


def test_win_prob_formula():
    assert win_prob(0) == pytest.approx(0.5)
    assert win_prob(None) == 0.5
    for cp in (-800, -100, 37, 250, 1200):
        exp = (50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)) / 100
        assert win_prob(cp) == pytest.approx(exp)
        assert win_prob(cp) + win_prob(-cp) == pytest.approx(1.0)
    assert win_prob(100000) == pytest.approx(1.0, abs=1e-9)
    assert 0 <= win_prob(-1e9) <= 1


def test_missing_binary_degrades(monkeypatch):
    import chessdex.engines.stockfish as sf
    monkeypatch.setattr(sf, "find_stockfish", lambda path=None: None)
    a = Analyzer(path="definitely-not-stockfish-xyz.exe")
    assert a.path is None
    assert a.available is False
    assert a.analyse(chess.STARTING_FEN) is None
    assert a.win_prob_loss(chess.STARTING_FEN, "e2e4") is None
    a.close()


_SF = Analyzer(nodes=20_000)
needs_sf = pytest.mark.skipif(not _SF.available, reason="Stockfish kurulu değil")


@needs_sf
def test_analyse_basic():
    mate_fen = "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"
    with Analyzer(nodes=20_000) as a:
        r = a.analyse(chess.STARTING_FEN)
        assert set(r) == {"cp", "mate", "best", "win_prob"}
        assert chess.Move.from_uci(r["best"]) in chess.Board().legal_moves
        assert 0.3 < r["win_prob"] < 0.7
        assert a.analyse(chess.STARTING_FEN) == r  # belirlenimci
        m = a.analyse(mate_fen)
        assert m["mate"] == 1 and m["best"] == "d1d8"
        assert a.win_prob_loss(mate_fen, "d1d8") < 0.01


@needs_sf
def test_pinned_version_and_1m_node_determinism():
    """Plan: sabit sürüm, sabit 1M düğüm, tek iş parçacığı → aynı pozisyon her seferinde aynı sonuç."""
    with Analyzer() as a:
        assert a._ensure().id["name"] == "Stockfish 19"
        fen = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
        assert a.analyse(fen) == a.analyse(fen)


@needs_sf
def test_process_exits_without_close():
    """Kapatılmayan motor süreç çıkışını kilitlememeli."""
    code = "import chess; from chessdex.engines.stockfish import Analyzer; Analyzer(nodes=1000).analyse(chess.STARTING_FEN)"
    r = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1], timeout=30)
    assert r.returncode == 0
