"""Gecikme ölçümü: cevap → sonraki senaryo (plan hedefi p95 < 200 ms). Gerçek bankayla çalışır."""
import sys
import time
from pathlib import Path

import chess
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))
from chessdex.api.engine import Engine  # noqa: E402

t = time.perf_counter()
e = Engine()
print(f"yükleme {time.perf_counter() - t:.1f} s, {len(e.pool)} senaryo ({e.bank_source})")
lat = []
for u in range(int(sys.argv[1]) if len(sys.argv) > 1 else 20):
    s = e.create("full")
    pending = None
    while True:
        t = time.perf_counter()
        if pending:
            e.respond(s, pending["token"], [next(iter(chess.Board(pending["fen"]).legal_moves)).uci()], 5000)
        r = e.next_item(s)
        lat.append(time.perf_counter() - t)
        if r["done"]:
            break
        pending = r["item"]
a = np.array(lat) * 1000
print(f"cevap→sonraki senaryo ms: medyan {np.median(a):.1f}  p95 {np.percentile(a, 95):.1f}  max {a.max():.1f}  (n={a.size})")
