"""Altın kayıt: aynı girdi → aynı tahmin (model sürümü başına).

Belirlenimci bir oturumu uçtan uca koşturur (demo bankası, sabit kimlikler ve saat, gerçek Maia-2 + Stockfish):
senaryolar → maç (kullanıcı = Maia 1500'ün en olası hamlesi, bot = üretimdeki örnekleme) → terk → rapor.
Ayrık çıktılar (seçilen senaryolar, puanlar, hamleler, motor değerlendirmeleri) ve sonsal özeti kaydedilir.
Torch / Maia-2 / Stockfish sürümü ya da ölçüm kodu değişirse test fark eder; değişiklik bilinçliyse yeniden üretin:

    PYTHONPATH=py .venv/Scripts/python -m chessdex.sim.golden --write
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from unittest import mock

import chess
import numpy as np

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "golden_session.json"
USER_LEVEL = 1500
GAME_PLIES = 50


class _Clock:
    """Engine'in gördüğü saat: her çağrıda 1 sn ilerler (senaryo süreleri ve puanlar belirlenimci olsun)."""

    def __init__(self):
        self.t = 1_000_000.0

    def time(self) -> float:
        self.t += 1.0
        return self.t


def _versions(model_version: dict) -> dict:
    from importlib.metadata import version

    out = {"model": model_version}
    for pkg in ("torch", "maia2", "numpy", "chess"):
        try:
            out[pkg] = version(pkg)
        except Exception:                                                  # pragma: no cover
            out[pkg] = None
    return out


def run() -> dict:
    from chessdex.api import engine as engine_mod
    from chessdex.bank.loader import demo_items
    from chessdex.measure.grid import GRID

    counter = itertools.count()
    with mock.patch.object(engine_mod.secrets, "token_urlsafe", lambda n=16: f"g{next(counter):06d}"), \
            mock.patch.object(engine_mod, "time", _Clock()):
        eng = engine_mod.Engine(bank=demo_items(), workers=1)
        if not (eng.model.name.startswith("maia2") and eng.analyzer.available):
            raise RuntimeError("altın kayıt gerçek Maia-2 ve Stockfish gerektirir")
        s = eng.create("full")
        items = []
        while True:
            r = eng.next_item(s)
            if r["done"]:
                break
            it = r["item"]
            p = s.pending.item
            # çift sıradakiler doğru çözüm, tekler ilk yasal hamle/şık: karışık cevaplar
            if len(items) % 2 == 0:
                moves = list(p.solution)
            else:
                moves = [it["choices"][0]] if it.get("choices") else [next(iter(chess.Board(it["fen"]).legal_moves)).uci()]
            res = eng.respond(s, it["token"], moves, 5000)
            items.append({"item_id": s.responses[-1]["item_id"], "transform": s.responses[-1]["transform"],
                          "score": res["score"]})

        g = eng.start_game(s)
        board = chess.Board()
        user = chess.WHITE if g.user_color == "white" else chess.BLACK
        ui = int(np.searchsorted(GRID, USER_LEVEL))
        for ply in range(GAME_PLIES):
            if board.is_game_over():
                break
            fen = board.fen()
            if board.turn == user:
                moves, mat = eng.model.move_prob_grid_all(fen, g.bot_level)
                uci = moves[int(np.argmax(mat[:, ui]))]
                eng.user_move(g.id, ply, fen, uci, 3000, 600_000)
            else:
                uci = eng.bot_move(g.id, fen, ply)["uci"]
            board.push_uci(uci)
        eng.finish(g.id, "0-1" if user == chess.WHITE else "1-0", "resign", None)
        rep = eng.report(s)
        eng.analyzer.close()
        eng.pool_exec.shutdown()

    return {
        "versions": _versions(rep["model_version"]),
        "items": items,
        "game": {"user_color": g.user_color, "bot_level": g.bot_level, "moves": [m.uci() for m in board.move_stack]},
        "user_moves": [{"ply": m["ply"], "weight": m["weight"], "reason": m["reason"], "eval_cp": m["eval_cp"],
                        "engine_best": m["engine_best"],
                        "win_prob_loss": None if m["win_prob_loss"] is None else round(m["win_prob_loss"], 6)}
                       for m in g.moves],
        "match_used": s.match_used,
        "estimate": rep["estimate"],
        "posterior_mean": round(s.final.mean(), 4),
        "items_posterior_mean": round(s.post.mean(), 4),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--write", action="store_true", help="altın kaydı yeniden üret")
    args = ap.parse_args(argv)
    out = run()
    if args.write:
        with open(GOLDEN_PATH, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, indent=1, ensure_ascii=False)
            f.write("\n")
        print(f"yazıldı: {GOLDEN_PATH}")
    else:
        json.dump(out["estimate"], sys.stdout, ensure_ascii=False)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
