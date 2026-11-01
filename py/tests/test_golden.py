"""Altın test: belirlenimci uçtan uca oturum kayıtlı çıktıyla aynı olmalı (chessdex.sim.golden).

Başarısızlık = ölçümü etkileyen bir şey değişti (kod, torch/Maia-2/Stockfish sürümü, banka, sabitler).
Değişiklik bilinçliyse kaydı yeniden üretin: `PYTHONPATH=py .venv/Scripts/python -m chessdex.sim.golden --write`.
"""
import json

import pytest

from chessdex.engines.human import Maia2Model
from chessdex.engines.stockfish import find_stockfish
from chessdex.sim.golden import GOLDEN_PATH, run

if not (Maia2Model.available() and find_stockfish()):
    pytest.skip("altın test gerçek Maia-2 ve Stockfish gerektirir", allow_module_level=True)


@pytest.fixture(scope="module")
def pair():
    expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return expected, json.loads(json.dumps(run()))


def test_versions_match(pair):
    exp, got = pair
    assert got["versions"] == exp["versions"], "model/paket sürümü değişti: altın kaydı bilinçli olarak yeniden üretin"


def test_items_identical(pair):
    exp, got = pair
    assert got["items"] == exp["items"]
    assert got["items_posterior_mean"] == pytest.approx(exp["items_posterior_mean"], abs=1e-3)


def test_game_identical(pair):
    exp, got = pair
    assert got["game"] == exp["game"]
    assert got["user_moves"] == exp["user_moves"]
    assert got["match_used"] is exp["match_used"] is True


def test_estimate_identical(pair):
    exp, got = pair
    assert got["estimate"] == exp["estimate"]
    assert got["posterior_mean"] == pytest.approx(exp["posterior_mean"], abs=1e-3)
