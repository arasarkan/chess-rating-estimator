"""Sıkı ve gevşek filtre çıktılarını birleştirir: sıkı senaryolar önceliklidir, gevşek havuz yalnızca
bant başına `per_band`'in altında kalan (genelde uç) bantları doldurur. Eklenenler `meta.relaxed = True`.

Kullanım: python -m chessdex.bank.merge STRICT.jsonl RELAXED.jsonl OUT.jsonl --per-band 2000
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict

from .filter import KIND_SHARES, band_of
from .loader import load_items
from .models import BankItem


def merge(strict: list[BankItem], relaxed: list[BankItem], per_band: int, width: int = 100) -> list[BankItem]:
    bands: dict[int, list[BankItem]] = defaultdict(list)
    for it in strict:
        bands[band_of(it.puzzle_rating, width)].append(it)
    have = {it.id for it in strict}
    extra: dict[int, list[BankItem]] = defaultdict(list)
    for it in relaxed:
        if it.id not in have:
            extra[band_of(it.puzzle_rating, width)].append(it)
    for band, pool in extra.items():
        cur = bands[band]
        while len(cur) < per_band and pool:
            counts = defaultdict(int)
            for it in cur:
                counts[it.kind] += 1
            # hedef payından en çok geride kalan türü seç
            avail = {it.kind for it in pool}
            kind = min(avail, key=lambda k: counts[k] - KIND_SHARES.get(k, 0.0) * (len(cur) + 1))
            i = next(j for j, it in enumerate(pool) if it.kind == kind)
            it = pool.pop(i)
            it.meta = {**it.meta, "relaxed": True}
            cur.append(it)
    return [it for b in sorted(bands) for it in sorted(bands[b], key=lambda x: x.id)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("strict")
    ap.add_argument("relaxed")
    ap.add_argument("output")
    ap.add_argument("--per-band", type=int, default=2000)
    args = ap.parse_args(argv)
    items = merge(load_items(args.strict), load_items(args.relaxed), args.per_band)
    with open(args.output, "w", encoding="utf-8") as out:
        for it in items:
            out.write(json.dumps(it.to_dict(), ensure_ascii=False) + "\n")
    n_rel = sum(bool(it.meta.get("relaxed")) for it in items)
    print(f"{len(items)} senaryo ({n_rel} gevşek filtreden) -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
