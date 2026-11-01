"""Pilot kalibrasyonu: bilinen gerçek düzeltmelerle üretilmiş sentetik pilottan α, β, γ geri kazanılır."""
import json

import numpy as np
import pytest

from chessdex.api.engine import Engine, to_irt
from chessdex.bank.models import BankItem
from chessdex.measure import calibration
from chessdex.measure.irt import category_probs
from chessdex.sim.pilot_calibrate import main as calibrate_main

MATE1 = "6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1"
TRUE = {"tactics": {"alpha": 120.0, "beta": 0.85, "gamma": 0.7},
        "positional": {"alpha": -150.0, "beta": 1.0, "gamma": 1.0}}


def bank(n=160, seed=0):
    rng = np.random.default_rng(seed)
    items = []
    for i in range(n):
        r = float(rng.uniform(600, 2600))
        if i % 2:
            items.append(BankItem(id=f"t{i}", source="t", fen=MATE1, solution=["a1a8"], kind="tactics", puzzle_rating=r))
        else:
            items.append(BankItem(id=f"p{i}", source="t", fen=MATE1, solution=["a1a8"], kind="positional", puzzle_rating=r,
                                  b=r, choices=["a1a8", "g1f1", "a1a2", "g1h1"],
                                  move_scores={"a1a8": 3, "g1f1": 1, "a1a2": 2, "g1h1": 0}))
    return items


def simulate_pilot(items, n_players=400, per_player=16, seed=1):
    """Cevaplar GERÇEK (düzeltilmiş) parametrelerle üretilir; pilot satırları sim/pilot_export biçiminde."""
    rng = np.random.default_rng(seed)
    cal_true = {"per_kind": TRUE}
    rows = []
    for pnum in range(n_players):
        theta = float(rng.uniform(700, 2300))
        resp = []
        for it in rng.choice(items, per_player, replace=False):
            true_item = to_irt(it, cal_true)
            k = int(rng.choice(true_item.n_cat, p=category_probs(true_item, np.array([theta]))[:, 0]))
            resp.append({"item_id": it.id, "transform": "id", "score": k, "elapsed_ms": 5000, "kind": it.kind})
        rows.append({"session": f"s{pnum}", "calibration_eligible": True, "verified": {"rating": theta},
                     "responses": resp})
    return rows


def test_recovers_true_corrections(tmp_path):
    items = bank()
    pilot = tmp_path / "pilot.jsonl"
    pilot.write_text("\n".join(json.dumps(r) for r in simulate_pilot(items)), encoding="utf-8")
    bank_path = tmp_path / "bank.jsonl"
    bank_path.write_text("\n".join(json.dumps(it.to_dict()) for it in items), encoding="utf-8")
    out = tmp_path / "cal.json"
    assert calibrate_main([str(pilot), str(bank_path), str(out)]) == 0
    cal = calibration.load(out)
    # α ve β birlikte tahmin edilir (β'daki küçük sapma α'yı kaydırır); anlamlı olan eşlenmiş zorluktur
    for kind in ("tactics", "positional"):
        got, true = cal["per_kind"][kind], TRUE[kind]
        for b in (1000.0, 1500.0, 2000.0):
            assert got["alpha"] + got["beta"] * b == pytest.approx(true["alpha"] + true["beta"] * b, abs=50), (kind, b)
        assert got["beta"] == pytest.approx(true["beta"], abs=0.1)
        assert got["gamma"] == pytest.approx(true["gamma"], abs=0.12)
        assert got["converged"]
    for kind in ("tactics", "positional"):
        before, after = cal["fit"][kind]["holdout_ll"]
        assert after > before                                         # ayrılmış oyuncularda uyum iyileşti


def test_too_few_responses_keeps_identity():
    rows = [{"kind": "defense", "theta": 1500.0, "k": 1, "a": 1.0, "b": 1500.0, "c": 0.02, "offsets": [0.0, 150.0]}] * 5
    cal = calibration.fit(rows)
    assert "defense" not in cal["per_kind"] and "skipped" in cal["fit"]["defense"]


def test_engine_applies_calibration_file(tmp_path, monkeypatch):
    path = tmp_path / "cal.json"
    calibration.save({"version": "test-v1", "per_kind": {"tactics": {"alpha": 100, "beta": 0.5, "gamma": 2.0}}}, path)
    monkeypatch.setenv("CHESSDEX_ITEM_CALIBRATION", str(path))
    it = BankItem(id="x", source="t", fen=MATE1, solution=["a1a8"], kind="tactics", puzzle_rating=1700)
    e = Engine(bank=[it])
    item = e.pool.items[0]
    assert item.b == pytest.approx(100 + 0.5 * it.b) and item.a == pytest.approx(2.0 * it.a)
    assert item.offsets[1] == pytest.approx(0.5 * 150.0)              # eşikler de ölçeklenir
    assert e.calibration["version"] == "test-v1"


def test_shipped_calibration_is_valid_and_positional_only():
    """Depodaki pilot öncesi sağlamlık ayarı: yalnız pozisyonel ayırt ediciliği düşürür (docs/results/pos_freeplay.md)."""
    from chessdex.measure import calibration as cal_mod
    from chessdex.measure.irt import Item

    cal = cal_mod.load()
    assert cal is not None and cal["version"].startswith("robust-positional")
    assert set(cal["per_kind"]) == {"positional"}
    p = cal["per_kind"]["positional"]
    assert p["alpha"] == 0.0 and p["beta"] == 1.0 and 0 < p["gamma"] < 1
    pos = Item("x", b=1500, a=0.5, c=0.25, kind="positional", offsets=(-50.0, 0.0, 300.0))
    tac = Item("y", b=1500, a=1.0, c=0.02, kind="tactics")
    assert cal_mod.apply(pos, cal).a == 0.5 * p["gamma"] and cal_mod.apply(pos, cal).b == 1500
    assert cal_mod.apply(tac, cal) == tac
