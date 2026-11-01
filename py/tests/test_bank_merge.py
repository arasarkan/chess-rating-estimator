import chess

from chessdex.bank.merge import merge
from chessdex.bank.models import BankItem


def mk(i, r, kind="tactics"):
    return BankItem(id=f"x{i}", source="t", fen=chess.STARTING_FEN, solution=["e2e4"], kind=kind, puzzle_rating=r)


def test_merge_fills_only_thin_bands_and_marks():
    strict = [mk(i, 1500) for i in range(10)] + [mk(100 + i, 2600) for i in range(3)]
    relaxed = [mk(i, 1500) for i in range(20, 40)] + [mk(200 + i, 2600, "defense") for i in range(5)] + [mk(100, 2600)]
    out = merge(strict, relaxed, per_band=10)
    full = [it for it in out if it.puzzle_rating == 1500]
    edge = [it for it in out if it.puzzle_rating == 2600]
    assert len(full) == 10 and not any(it.meta.get("relaxed") for it in full)
    assert len(edge) == 8                                  # 3 sıkı + 5 gevşek (x100 yinelenen, alınmaz)
    assert sum(bool(it.meta.get("relaxed")) for it in edge) == 5
    assert len({it.id for it in out}) == len(out)
