"""Lichess CSV filtresi ve tabakalı örnekleme testleri."""
import json
import random
from pathlib import Path

import chess
import pytest

from chessdex.bank.filter import band_of, iter_filtered, main, stratified_sample
from chessdex.bank.loader import load_items
from chessdex.bank.models import BankItem

FIX = Path(__file__).parent / "fixtures" / "puzzles_sample.csv"


def test_filter_selects_expected_rows():
    items = list(iter_filtered(FIX))
    ids = [it.id for it in items]
    assert ids == ["lichess:T0001", "lichess:T0002", "lichess:T0003", "lichess:T0004", "lichess:T0005", "lichess:T0010"]


def test_kinds_and_tablebase_flag():
    by_id = {it.id: it for it in iter_filtered(FIX)}
    assert by_id["lichess:T0001"].kind == "tactics"
    assert by_id["lichess:T0003"].kind == "endgame"
    assert by_id["lichess:T0003"].meta["tablebase_check"] is True
    assert by_id["lichess:T0004"].kind == "defense"
    assert by_id["lichess:T0010"].kind == "defense"  # savunma teması oyun sonundan önce gelir
    assert by_id["lichess:T0010"].meta["tablebase_check"] is True


def test_setup_move_applied_and_solution_player_perspective():
    it = {i.id: i for i in iter_filtered(FIX)}["lichess:T0002"]
    # Orijinal FEN siyah sırada; kurulum hamlesi (g4h2) sonrası sıra beyazda
    board = chess.Board(it.fen)
    assert board.turn == chess.WHITE
    assert it.solution == ["c4e6", "g8h7", "g5h5"]
    for u in it.solution:
        board.push_uci(u)
    assert board.is_checkmate()


def test_custom_length_bounds():
    items = list(iter_filtered(FIX, min_len=2, max_len=2))
    assert [it.id for it in items] == ["lichess:T0005"]


def test_initial_params_from_rating():
    it = next(iter(iter_filtered(FIX)))
    assert it.b == pytest.approx(-200 + 1850)
    assert it.c == pytest.approx(0.02)
    assert it.a == 1.0
    assert it.time_fast_ms > 0


def test_stratified_cap():
    rng = random.Random(0)
    base = next(iter(iter_filtered(FIX)))
    items = [BankItem(id=f"x{i}", source="t", fen=base.fen, solution=base.solution, puzzle_rating=1000 + (i % 3) * 100 + 7)
             for i in range(300)]
    bands = stratified_sample(items, per_band=20, rng=rng)
    assert sorted(bands) == [1000, 1100, 1200]
    assert all(len(v) == 20 for v in bands.values())
    assert band_of(1599.9) == 1500


def test_cli_writes_jsonl(tmp_path):
    out = tmp_path / "bank.jsonl"
    assert main([str(FIX), str(out), "--per-band", "1"]) == 0
    lines = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 6  # her biri ayrı bantta
    items = load_items(out)
    assert {i.id for i in items} == {"lichess:T0001", "lichess:T0002", "lichess:T0003", "lichess:T0004", "lichess:T0005", "lichess:T0010"}


def test_zst_input(tmp_path):
    zstd = pytest.importorskip("zstandard")
    p = tmp_path / "p.csv.zst"
    p.write_bytes(zstd.ZstdCompressor().compress(FIX.read_bytes()))
    assert len(list(iter_filtered(p))) == 6


def test_stratified_kind_quotas_and_fill():
    rng = random.Random(1)
    base = next(iter(iter_filtered(FIX)))
    def mk(i, kind):
        return BankItem(id=f"{kind}{i}", source="t", fen=base.fen, solution=base.solution, kind=kind, puzzle_rating=1234)
    items = [mk(i, "tactics") for i in range(500)] + [mk(i, "endgame") for i in range(500)] + [mk(i, "defense") for i in range(10)]
    band = stratified_sample(items, per_band=100, rng=rng)[1200]
    kinds = {k: sum(it.kind == k for it in band) for k in ("tactics", "endgame", "defense")}
    assert len(band) == 100
    assert kinds["defense"] == 10                       # elde olanın hepsi
    assert kinds["endgame"] == 27                       # kendi payı
    assert kinds["tactics"] == 63                       # 53 pay + savunma açığı
