import numpy as np

from chessdex.engines.integrity import integrity_score


def _game(n, match_p, hp, spent, focus=0.0, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        cx = float(rng.uniform(0.5, 3.0))
        out.append({
            "engine_match": bool(rng.random() < match_p),
            "human_prob": hp(rng),
            "spent_ms": int(spent(cx, rng)),
            "complexity": cx,
            "focus_lost": bool(rng.random() < focus),
        })
    return out


def test_human_like_clean():
    g = _game(40, 0.45, lambda r: float(r.uniform(0.05, 0.6)),
              lambda cx, r: 3000 * cx * r.lognormal(0, 0.4))
    res = integrity_score(g)
    assert not res["flag"] and res["score"] < 0.3


def test_engine_user_flagged():
    g = _game(40, 0.97, lambda r: float(r.uniform(0.001, 0.04)),
              lambda cx, r: 6000 + r.normal(0, 200), focus=0.4)
    res = integrity_score(g)
    assert res["flag"] and res["score"] > 0.8
    assert "engine_match" in res["reasons"]
    assert "constant_time" in res["reasons"]


def test_low_effort_flagged():
    g = _game(30, 0.1, lambda r: float(r.uniform(0.0, 0.1)), lambda cx, r: 400 + r.uniform(0, 300))
    res = integrity_score(g)
    assert res["flag"] and "low_effort" in res["reasons"]


def test_short_and_missing_inputs():
    row = {"engine_match": None, "human_prob": None, "spent_ms": None,
           "complexity": None, "focus_lost": False}
    res = integrity_score([row] * 5)
    assert 0 <= res["score"] <= 1 and not res["flag"]
    assert integrity_score([])["score"] == 0.0
