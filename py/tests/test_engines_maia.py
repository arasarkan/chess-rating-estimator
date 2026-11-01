"""Gerçek Maia-2 adaptörü (paket ve ağırlıklar yoksa atlanır)."""
import chess
import numpy as np
import pytest

from chessdex.engines.human import MAIA_CENTERS, Maia2Model
from chessdex.measure.grid import GRID

if not Maia2Model.available():
    pytest.skip("maia2 kurulu değil", allow_module_level=True)

ITALIAN = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
BLACK_TO_MOVE = "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 3 3"


@pytest.fixture(scope="module")
def maia():
    return Maia2Model()


@pytest.mark.parametrize("fen", [ITALIAN, BLACK_TO_MOVE])
def test_matches_official_inference_within_rounding(maia, fen):
    official, _ = maia._inference.inference_each(maia._model, maia._prepared, fen, 1500, 1500)
    moves, P = maia.forward(fen, [1500], 1500)
    assert set(moves) == set(official) == {m.uci() for m in chess.Board(fen).legal_moves}
    mine = dict(zip(moves, P[0]))
    assert max(abs(official[m] - mine[m]) for m in official) <= 5e-5 + 1e-9   # yalnızca 4 ondalık yuvarlama


def test_batched_equals_single(maia):
    moves, P = maia.forward(ITALIAN, MAIA_CENTERS, 1500)
    for i, e in enumerate(MAIA_CENTERS):
        _, single = maia.forward(ITALIAN, [e], 1500)
        # FP32'de parti boyutu toplama sırasını değiştirir (~1e-6); her yol hep aynı boyutla çağrıldığı için
        # belirlenimcilik korunur (test_deterministic)
        np.testing.assert_allclose(P[i], single[0], atol=1e-5)


def test_grid_shape_and_normalized(maia):
    moves, mat = maia.move_prob_grid_all(BLACK_TO_MOVE, 1500)
    assert mat.shape == (len(moves), GRID.size)
    np.testing.assert_allclose(mat.sum(0), 1.0, atol=1e-9)
    # Maia-2 uç kovaların dışında bilgi taşımaz → olabilirlik sabit
    assert np.allclose(mat[:, 0], mat[:, np.searchsorted(GRID, 900)])


def test_deterministic(maia):
    a = maia.forward(ITALIAN, MAIA_CENTERS, 1500)[1]
    b = maia.forward(ITALIAN, MAIA_CENTERS, 1500)[1]
    assert np.array_equal(a, b)


def test_open_bucket_centers_map_to_end_buckets():
    from maia2.utils import create_elo_dict, map_to_category
    d = create_elo_dict()
    assert map_to_category(int(MAIA_CENTERS[0]), d) == 0
    assert map_to_category(int(MAIA_CENTERS[-1]), d) == max(d.values())
    assert len({map_to_category(int(c), d) for c in MAIA_CENTERS}) == 11


def test_interp_matrix_matches_old_flat_behaviour_when_kappa_zero():
    from chessdex.engines.human import centers_to_grid, interp_matrix
    rng = np.random.default_rng(0)
    L = np.log(rng.dirichlet(np.ones(20), size=11).T)          # (20 hamle, 11 merkez)
    th = np.clip(GRID, MAIA_CENTERS[0], MAIA_CENTERS[-1])
    old = np.exp(np.stack([np.interp(th, MAIA_CENTERS, L[i]) for i in range(20)]))
    old /= old.sum(0, keepdims=True)
    np.testing.assert_allclose(centers_to_grid(L, interp_matrix(0.0, 0.0)), old, atol=1e-12)


def test_extrapolation_continues_end_slope_then_flattens():
    from chessdex.engines.human import interp_matrix
    M = interp_matrix(1.0, 0.5, 300.0)
    L = np.zeros((1, 11)); L[0, 0], L[0, 1] = 0.0, -1.0          # 903→1150 arasında eğim −1/247
    lo = (M @ L[0])
    i700 = np.searchsorted(GRID, 700); i500 = np.searchsorted(GRID, 500); i400 = 0
    assert lo[i700] == pytest.approx(203 / 247, rel=1e-6)       # 903−700 = 203 Elo boyunca sürer
    assert lo[i500] == pytest.approx(lo[i400]) == pytest.approx(300 / 247, rel=1e-6)   # 300 Elo sonra sabit
    np.testing.assert_allclose(M.sum(1), 1.0)                   # sabit log olasılık korunur
