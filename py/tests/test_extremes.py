import numpy as np

from chessdex.engines.human import centers_to_grid, interp_matrix
from chessdex.measure.match import PROB_FLOOR
from chessdex.sim.extremes import played_log_grid, prior_of


def test_played_log_grid_matches_production_path():
    rng = np.random.default_rng(1)
    sizes = [5, 12, 1, 30, 7]
    mats = [np.log(rng.dirichlet(np.ones(k), size=11).T + 1e-6).astype(np.float32) for k in sizes]
    played = np.array([rng.integers(k) for k in sizes], np.int32)
    d = {"maia_L": np.concatenate(mats), "maia_off": np.concatenate([[0], np.cumsum(sizes)]), "maia_played": played}
    for kl, kh, mx in [(0, 0, 400), (1.0, 0.5, 600)]:
        got = played_log_grid(d, kl, kh, mx, chunk=2)
        M = interp_matrix(kl, kh, mx)
        for i, L in enumerate(mats):
            want = np.log(np.maximum(centers_to_grid(L.astype(float), M)[played[i]], PROB_FLOOR))
            np.testing.assert_allclose(got[i], want, atol=2e-4)


def test_prior_normalized():
    assert np.isclose(np.exp(prior_of(600)).sum(), 1.0)
