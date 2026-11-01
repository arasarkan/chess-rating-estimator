"""Senaryo bankasını doğrular ve özet çıkarır.

Kontroller: FEN geçerli, çözüm çizgisi yasal, son oyuncu hamlesi sonrası pozisyon tutarlı,
her geçerli dönüşüm (renk takası/ayna) sonrası çözüm hâlâ yasal ve mat korunuyor.
Kullanım: .venv/Scripts/python scripts/validate_bank.py py/data/bank.jsonl
"""
import json
import sys
from collections import Counter
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))
from chessdex.bank.loader import load_items  # noqa: E402
from chessdex.bank.transforms import apply_transform, valid_transforms  # noqa: E402


def play(fen, moves):
    b = chess.Board(fen)
    for u in moves:
        m = chess.Move.from_uci(u)
        if m not in b.legal_moves:
            return None
        b.push(m)
    return b


def main(path):
    sys.stdout.reconfigure(encoding="utf-8")
    items = load_items(path)
    bad, kinds, bands, lens, mates, tb = [], Counter(), Counter(), Counter(), 0, 0
    ids = Counter(it.id for it in items)
    dup = [i for i, c in ids.items() if c > 1]
    for it in items:
        end = play(it.fen, it.solution)
        if end is None:
            bad.append((it.id, "çözüm yasal değil"))
            continue
        if it.choices:
            legal = {m.uci() for m in chess.Board(it.fen).legal_moves}
            if not set(it.choices) <= legal:
                bad.append((it.id, "yasal olmayan şık"))
            if it.move_scores and (set(it.move_scores) != set(it.choices)
                                   or list(it.move_scores.values()).count(3) != 1
                                   or it.move_scores.get(it.solution[0]) != 3):
                bad.append((it.id, "şık puanları tutarsız"))
        mate = end.is_checkmate()
        mates += mate
        for name in valid_transforms(it.fen):
            f, sol = apply_transform(it.fen, it.solution, name)
            e2 = play(f, sol)
            if e2 is None or e2.is_checkmate() != mate:
                bad.append((it.id, f"dönüşüm bozuk: {name}"))
        kinds[it.kind] += 1
        bands[int(it.puzzle_rating // 200 * 200)] += 1
        lens[len(it.solution)] += 1
        tb += bool(it.meta.get("tablebase_check"))
    print(json.dumps({
        "n": len(items), "hatalı": len(bad), "örnek_hatalar": bad[:10], "yinelenen_id": len(dup),
        "tür": dict(kinds), "çözüm_uzunluğu(yarım hamle)": dict(sorted(lens.items())),
        "mat_ile_biten": mates, "tablebase_bekleyen": tb,
        "200lük_bant": {f"{k}-{k + 199}": v for k, v in sorted(bands.items())},
        "b_aralığı": [min(i.b for i in items), max(i.b for i in items)],
    }, ensure_ascii=False, indent=1))
    return 1 if bad or dup else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
