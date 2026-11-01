import random

import pytest

from chessdex.bank.positional import SCORE_EDGES, choose_options, difficulty, is_positional, loss_score, wp


def rec(loss, best="e2e4", played="d2d4", **feat):
    f = {"abs_eval": 40, "gap2": 0.03, "n_good": 3, "n_legal": 30, "pieces": 28,
         "best_capture": False, "best_check": False, **feat}
    return {"loss": loss, "evals": {m: 0 for m in loss}, "best": best, "played": played, "features": f}


LOSS = {"e2e4": 0.0, "d2d4": 0.04, "g1f3": 0.01, "a2a3": 0.10, "h2h4": 0.30, "b1c3": 0.05}


def test_loss_score_edges():
    assert [loss_score(x) for x in (0, SCORE_EDGES[0], 0.05, 0.1, 0.5)] == [3, 3, 2, 1, 0]
    assert wp(0) == pytest.approx(0.5) and wp(300) > 0.7


def test_choose_options_one_best_and_a_low_option_and_human_move():
    opts = choose_options(rec(LOSS), random.Random(0))
    assert len(opts) == 4 and opts["e2e4"] == 3
    assert list(opts.values()).count(3) == 1                # g1f3 (kayıp 0.01 → 3) şık olamaz
    assert min(opts.values()) <= 1
    assert "d2d4" in opts                                   # oyuncunun gerçek hatası çeldirici


def test_choose_options_rejects_when_all_alternatives_fine():
    fine = {"e2e4": 0.0, "d2d4": 0.03, "g1f3": 0.04, "b1c3": 0.05}
    assert choose_options(rec(fine), random.Random(0)) is None


def test_is_positional_filters_tactics():
    assert is_positional(rec(LOSS))
    assert not is_positional(rec(LOSS, best_capture=True))
    assert not is_positional(rec(LOSS, gap2=0.5))           # tek hamle taktiği
    assert not is_positional(rec(LOSS, abs_eval=400))       # dengesiz pozisyon


def test_difficulty_monotone_in_intercept():
    model = {"w0": 0.0, "w_R": 1.0, "w": {"gap2": 0, "n_good_frac": 0, "abs_eval_100": 0, "pieces_10": 0}}
    assert difficulty(rec(LOSS), model) == pytest.approx(1500)
    easier = {**model, "w0": 1.0}                            # her rating'de bulma olasılığı daha yüksek
    assert difficulty(rec(LOSS), easier) == pytest.approx(1100)


def test_origin_difficulty_anchor():
    from chessdex.bank.positional import ORIGIN_P2, origin_difficulty
    from chessdex.measure.irt import _logistic
    r = {"rating": 1700}
    b = origin_difficulty(r)
    assert _logistic(1.0, 1700, b) == pytest.approx(ORIGIN_P2)   # kendi seviyesinde P(≥2) gözlenen orana eşit
