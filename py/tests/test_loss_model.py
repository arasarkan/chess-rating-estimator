import numpy as np

from chessdex.measure.grid import GRID
from chessdex.measure.loss_model import K, LossModel, category


def synthetic(n=20000, seed=0):
    """Güçlü oyuncu daha az kayıp yapar: kayıp ~ üstel, ortalaması θ ile azalır."""
    rng = np.random.default_rng(seed)
    R = rng.uniform(600, 2600, n)
    mean = 0.12 * np.exp(-(R - 600) / 900)
    loss = rng.exponential(mean)
    ev = rng.normal(0, 200, n)
    return R, loss, ev


def test_category_edges():
    assert category([0.0, 0.01, 0.011, 0.5]).tolist() == [0, 0, 1, 5]


def test_fit_and_likelihood_recovers_level(tmp_path):
    R, loss, ev = synthetic()
    m = LossModel.fit(R, loss, ev)
    # hamle başına olabilirlik normalize
    lp = m.log_probs(GRID, 0.0)
    assert np.allclose(np.exp(lp).sum(1), 1.0)
    # zayıf/güçlü oyuncuların hamle dizileri doğru yöne çeker
    rng = np.random.default_rng(1)
    for true in (900, 2200):
        l = rng.exponential(0.12 * np.exp(-(true - 600) / 900), 40)
        ll = m.batch_log_lik(l, np.zeros(40)).sum(0)
        assert abs(GRID[ll.argmax()] - true) < 400
    # batch ile tekil aynı
    single = m.move_log_lik(0.05, 120.0)
    batch = m.batch_log_lik(np.array([0.05]), np.array([120.0]))[0]
    assert np.allclose(single, batch)
    p = tmp_path / "m.json"
    m.save(p, source="test")
    m2 = LossModel.load(p)
    assert np.allclose(m2.W, m.W) and m2.meta["source"] == "test" and m2.W.shape == (K, 5)
