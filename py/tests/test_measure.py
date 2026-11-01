from collections import Counter

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from chessdex.measure.grid import GRID
from chessdex.measure.irt import POSITIONAL_OFFSETS, Item, batch_category_probs, category_probs, log_lik_graded
from chessdex.measure.match import MoveEvidence, match_log_lik
from chessdex.measure.posterior import Posterior
from chessdex.measure.prior import default_prior, survey_prior
from chessdex.measure.scales import convert
from chessdex.measure.selection import ItemPool, select_next, target_kind
from chessdex.measure.stopping import should_stop

items_st = st.builds(
    Item, id=st.just("x"), b=st.floats(300, 3100), a=st.floats(0.3, 3.0), c=st.floats(0, 0.3),
    offsets=st.sampled_from([(0.0, 150.0), (0.0,), POSITIONAL_OFFSETS]),
)


def test_grid():
    assert GRID.size == 261 and GRID[0] == 400 and GRID[-1] == 3000


def test_default_prior():
    from chessdex.measure.prior import DEFAULT_SD
    post = Posterior(default_prior())
    # ızgara 400–3000'de kesildiği için ortalama yukarı kayar, sd daralır (sd 800 → ~620)
    assert 1500 < post.mean() < 1600
    assert 0.7 * DEFAULT_SD < post.sd() < DEFAULT_SD


def test_survey_prior_shifts():
    lo = Posterior(survey_prior({"years_playing": "lt1", "tournament": "none"})).mean()
    hi = Posterior(survey_prior({"years_playing": "gt10", "tournament": "rated"})).mean()
    assert lo < 1500 < hi


@given(items_st)
@settings(max_examples=200)
def test_category_probs_sum_to_one(item):
    p = category_probs(item)
    assert np.all(p >= 0)
    np.testing.assert_allclose(p.sum(0), 1.0, atol=1e-9)


@given(items_st)
@settings(max_examples=100)
def test_batch_matches_single(item):
    single = category_probs(item)
    off = np.full((1, 3), np.inf)
    off[0, : len(item.offsets)] = item.offsets
    batch = batch_category_probs(np.array([item.a]), np.array([item.b]), np.array([item.c]), off)[0]
    np.testing.assert_allclose(batch[: item.n_cat], single, atol=1e-9)


@given(st.lists(st.tuples(items_st, st.integers(0, 3)), min_size=1, max_size=60))
@settings(max_examples=100)
def test_posterior_stays_normalized_and_ordered(seq):
    post = Posterior(default_prior())
    for item, k in seq:
        post.update(log_lik_graded(item, min(k, item.n_cat - 1)))
    assert np.isfinite(post.logp).all()
    np.testing.assert_allclose(post.p.sum(), 1.0, atol=1e-9)
    qs = [post.quantile(q) for q in (0.05, 0.5, 0.95)]
    assert qs[0] <= qs[1] <= qs[2]
    assert 395 <= qs[0] and qs[2] <= 3005


def test_extreme_sequences_no_overflow():
    post = Posterior(default_prior())
    for _ in range(200):
        post.update(log_lik_graded(Item("x", b=2900, a=3), 2))
    assert post.median() > 2700 and np.isfinite(post.sd())
    post = Posterior(default_prior())
    for _ in range(200):
        post.update(log_lik_graded(Item("x", b=500, a=3), 0))
    assert post.median() < 600


def test_compress_roundtrip():
    post = Posterior(default_prior()).update(log_lik_graded(Item("x", b=1800), 2))
    back = Posterior.decompress(post.compress())
    assert abs(back.median() - post.median()) < 1


def test_selection_prefers_informative_and_balances_kinds():
    rng = np.random.default_rng(0)
    items = [Item(f"t{i}", b=b, kind="tactics") for i, b in enumerate(range(400, 3000, 50))]
    items += [Item(f"e{i}", b=b, kind="endgame") for i, b in enumerate(range(400, 3000, 50))]
    pool = ItemPool(items)
    post = Posterior(default_prior())
    it = select_next(post, pool, set(), rng, Counter({"tactics": 5}))
    assert it.kind == "endgame"
    assert abs(it.b - 1500) < 300
    assert target_kind(Counter())[0] == "tactics"


def test_stopping():
    post = Posterior(default_prior())
    assert not should_stop(post, 5)
    assert should_stop(post, 20)
    narrow = Posterior(-0.5 * ((GRID - 1500) / 40) ** 2)
    assert should_stop(narrow, 12) and not should_stop(narrow, 11)


def test_short_mode_time_budget():
    from chessdex.measure.stopping import SHORT_BUDGET_MS, SHORT_MIN_ITEMS
    post = Posterior(default_prior())
    over = int(SHORT_BUDGET_MS)
    assert should_stop(post, SHORT_MIN_ITEMS, "short", over)
    assert not should_stop(post, SHORT_MIN_ITEMS - 1, "short", over)       # en az senaryo sayısı korunur
    assert not should_stop(post, SHORT_MIN_ITEMS, "short", over - 1)
    assert not should_stop(post, SHORT_MIN_ITEMS, "full", over)            # tam modda bütçe yok


def test_match_requires_15_moves():
    probs = np.linspace(0.1, 0.5, GRID.size)
    ll, used = match_log_lik([MoveEvidence(i, probs) for i in range(10)])
    assert not used and not ll.any()
    ll, used = match_log_lik([MoveEvidence(i, probs) for i in range(20)], score=1.0, bot_level=1500)
    assert used and ll.argmax() == GRID.size - 1


def test_scales_fide_wider():
    s = convert({"median": 1600, "lo90": 1500, "hi90": 1700})
    w = {k: v["hi90"] - v["lo90"] for k, v in s.items()}
    assert w["fide"] > w["lichess"]


def test_match_loss_term_combines_with_maia():
    flat = np.full(GRID.size, 0.2)
    toward_high = np.where(GRID > 2000, 0.0, -1.0)            # kayıp sinyali yüksek θ'yı destekliyor
    with_loss = [MoveEvidence(i, flat, loss_ll=toward_high) for i in range(20)]
    without = [MoveEvidence(i, flat) for i in range(20)]
    ll_w, used = match_log_lik(with_loss, lam_loss=0.2)
    ll_o, _ = match_log_lik(without, lam_loss=0.2)
    assert used
    assert ll_w.argmax() > np.searchsorted(GRID, 2000) and np.ptp(ll_o) == 0
    assert np.allclose(ll_w[-1] - ll_w[0], 20 * 0.2 * 1.0)
