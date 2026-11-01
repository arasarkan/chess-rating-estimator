import time

import chess
import numpy as np
import pytest

from chessdex.engines import human as H
from chessdex.measure.grid import GRID

FENS = [
    chess.STARTING_FEN,
    "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4",
    "r1bq1rk1/pp2bppp/2n1pn2/2pp4/3P4/2PBPN2/PP1N1PPP/R1BQ1RK1 w - - 0 8",
    "r2q1rk1/1b2bppp/p1n1pn2/1pp5/3P4/1BP1PN2/PP3PPP/RNBQR1K1 w - - 0 11",
    "rnbqkb1r/pp2pppp/3p1n2/8/3NP3/8/PPP2PPP/RNBQKB1R w KQkq - 1 5",
    "r1bqr1k1/pp1n1pbp/2pp1np1/4p3/2PPP3/2N1BP2/PP1QN1PP/R3KB1R w KQ - 2 9",
    "2rq1rk1/pp1bppbp/3p1np1/n7/3NP3/1BN1BP2/PPPQ2PP/2KR3R w - - 6 12",
    "r3k2r/pp1n1ppp/2p1pn2/q2p4/2PP4/2N1PN2/PPQ2PPP/R3KB1R b KQkq - 1 9",
    "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
]


@pytest.fixture(scope="module")
def model():
    return H.HeuristicHumanModel()


def test_protocol(model):
    assert isinstance(model, H.HumanMoveModel)
    assert model.name and model.version


@pytest.mark.parametrize("fen", FENS)
def test_probs_sum_and_legal(model, fen):
    legal = {m.uci() for m in chess.Board(fen).legal_moves}
    for elo in (400, 800, 1500, 2400, 3000):
        p = model.move_probs(fen, elo, 1500)
        assert set(p) == legal
        assert abs(sum(p.values()) - 1.0) < 1e-9
        assert min(p.values()) > 0
    moves, mat = model.move_prob_grid_all(fen, 1500)
    assert set(moves) == legal
    assert mat.shape == (len(legal), GRID.size)
    np.testing.assert_allclose(mat.sum(axis=0), 1.0, atol=1e-9)


def test_grid_matches_move_probs(model):
    fen = FENS[2]
    moves, mat = model.move_prob_grid_all(fen, 1500)
    i = int(np.searchsorted(GRID, 1500))
    p = model.move_probs(fen, 1500, 1500)
    for k, m in enumerate(moves):
        assert abs(mat[k, i] - p[m]) < 1e-12
    row = model.move_prob_grid(fen, moves[0], 1500)
    assert row.shape == (261,)
    np.testing.assert_allclose(row, mat[0])
    with pytest.raises(ValueError):
        model.move_prob_grid(fen, "a1a8", 1500)


@pytest.mark.parametrize("fen", FENS[1:])
def test_monotone_concentration(model, fen):
    moves, sc = model.scores(fen)
    best = int(np.argmax(sc))
    _, mat = model.move_prob_grid_all(fen, 1500)
    assert np.all(np.diff(mat[best]) >= -1e-12), "en iyi hamle olasılığı θ ile artmalı"
    ent = -(mat * np.log(mat)).sum(axis=0)
    assert np.all(np.diff(ent) <= 1e-9), "entropi θ ile azalmalı"


def test_calibration_band(model):
    top = {800: [], 2400: []}
    for fen in FENS[1:]:
        for th in top:
            top[th].append(max(model.move_probs(fen, th, th).values()))
    assert 0.18 <= np.median(top[800]) <= 0.42
    assert 0.50 <= np.median(top[2400]) <= 0.82


def test_mate_in_one_preferred(model):
    fen = "6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1"  # Rd8#
    p = model.move_probs(fen, 2400, 2400)
    assert max(p, key=p.get) == "d1d8"
    assert p["d1d8"] > 0.5


def test_hanging_queen_avoided(model):
    # Siyah vezir e5'te, beyaz Nf3 saldırıyor: en iyi hamle vezirle kaçmak.
    fen = "rnb1kbnr/pppp1ppp/8/4q3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 0 3"
    moves, sc = model.scores(fen)
    assert moves[int(np.argmax(sc))].startswith("e5")


def test_free_piece_captured(model):
    # Beyaz vezir d5'te korumasız; Nf6xd5 bariz.
    fen = "rnbqkb1r/pppp1ppp/5n2/3Qp3/4P3/8/PPPP1PPP/RNB1KBNR b KQkq - 0 3"
    p = model.move_probs(fen, 1500, 1500)
    assert max(p, key=p.get) == "f6d5"


def test_determinism():
    a = H.HeuristicHumanModel().move_prob_grid_all(FENS[3], 1500)
    b = H.HeuristicHumanModel().move_prob_grid_all(FENS[3], 1500)
    assert a[0] == b[0]
    np.testing.assert_array_equal(a[1], b[1])


def test_speed():
    m = H.HeuristicHumanModel()
    times = []
    for fen in FENS:
        t = time.perf_counter()
        m.move_prob_grid_all(fen, 1500)
        times.append(time.perf_counter() - t)
    assert np.median(times) < 0.150
    t = time.perf_counter()
    m.move_prob_grid_all(FENS[3], 1500)
    assert time.perf_counter() - t < 0.005  # önbellek


def test_game_over(model):
    fen = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"  # mat
    assert model.move_probs(fen, 1500, 1500) == {}
    moves, mat = model.move_prob_grid_all(fen, 1500)
    assert moves == [] and mat.shape == (0, 261)


def test_sample_move_deterministic(model):
    fen = FENS[1]
    a = [H.sample_move(model, fen, 1200, 1200, np.random.default_rng(7)) for _ in range(3)]
    b = [H.sample_move(model, fen, 1200, 1200, np.random.default_rng(7)) for _ in range(3)]
    assert a == b
    rng = np.random.default_rng(1)
    picks = {H.sample_move(model, fen, 800, 800, rng) for _ in range(60)}
    assert len(picks) > 3  # argmax değil, örnekleme


def test_think_time_and_entropy(model):
    rng = np.random.default_rng(0)
    for fen in FENS:
        e = model.entropy(fen, 1500)
        assert e >= 0
        assert 1000 <= H.think_time_ms(fen, e, rng) <= 8000
    lo = np.mean([H.think_time_ms(FENS[2], 0.1, np.random.default_rng(i)) for i in range(50)])
    hi = np.mean([H.think_time_ms(FENS[2], 3.3, np.random.default_rng(i)) for i in range(50)])
    assert hi > lo


def test_get_model_fallback(monkeypatch):
    monkeypatch.setenv("CHESSDEX_HUMAN_MODEL", "heuristic")
    H._reset_model_for_tests()
    m = H.get_model()
    assert isinstance(m, H.HeuristicHumanModel)
    assert H.get_model() is m
    H._reset_model_for_tests()


def test_maia_available_flag():
    assert isinstance(H.Maia2Model.available(), bool)
