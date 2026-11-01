import numpy as np
import pytest

from chessdex.bank.maia_calib import anchor_b, logit10, marginal_a, slope
from chessdex.engines.human import MAIA_CENTERS


def curve(a, b):
    return 1 / (1 + 10 ** (-a * (MAIA_CENTERS - b) / 400))


def test_slope_recovers_discrimination_and_sign():
    F = np.stack([curve(0.8, 1200), curve(0.8, 1500), curve(0.8, 1800)])
    assert slope(F) == pytest.approx(0.8, abs=0.02)
    assert slope(F[:, ::-1]) < 0                       # ters ayırt eden


def test_marginal_a():
    assert marginal_a(0.0) == pytest.approx(1.0)
    assert marginal_a(476) == pytest.approx(0.528, abs=0.005)
    assert marginal_a(1000) < marginal_a(200) < 1.0


def test_anchor_mapping_and_logit():
    anchor = {"alpha": 1600.0, "beta": -240.0}
    assert anchor_b(0.0, anchor) == 1600.0
    assert anchor_b(1.0, anchor) < anchor_b(-1.0, anchor)   # bulunması kolay → düşük zorluk
    assert logit10(np.array([0.5]))[0] == pytest.approx(0.0)
    assert np.isfinite(logit10(np.array([0.0, 1.0]))).all()
