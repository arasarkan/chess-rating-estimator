"""Stockfish analizörü (belirlenimci ayar: sabit düğüm, tek iş parçacığı, temiz hash).

Stockfish bulunamazsa `available == False` olur ve `analyse` `None` döner; sistem çökmez.
"""
from __future__ import annotations

import atexit
import functools
import math
import os
import shutil
import threading
import weakref
from pathlib import Path

import chess
import chess.engine

LICHESS_K = 0.00368208
MATE_CP = 100_000  # mat skorlarını kazanma olasılığına çevirirken kullanılan cp


def win_prob(cp: float | None) -> float:
    """Lichess formülü: 50 + 50*(2/(1+exp(-k*cp)) - 1), 0..1 ölçeğinde döner."""
    if cp is None:
        return 0.5
    x = max(min(float(cp), 10_000.0), -10_000.0)
    return (50.0 + 50.0 * (2.0 / (1.0 + math.exp(-LICHESS_K * x)) - 1.0)) / 100.0


# Projeye sabitlenmiş sürüm (scripts/setup.py ile kurulur): Stockfish 19
PINNED_DIR = Path(__file__).resolve().parents[3] / "tools" / "stockfish" / "stockfish"
PINNED_VERSION = "Stockfish 19"


def find_stockfish(path: str | None = None) -> str | None:
    """Sıra: argüman → STOCKFISH_PATH → projedeki sabit sürüm → PATH ('stockfish')."""
    for cand in (path, os.environ.get("STOCKFISH_PATH")):
        if cand and os.path.isfile(cand):
            return cand
        if cand:
            found = shutil.which(cand)
            if found:
                return found
    for pinned in sorted(PINNED_DIR.glob("stockfish-*")):
        if pinned.is_file() and pinned.suffix in ("", ".exe"):
            return str(pinned)
    return shutil.which("stockfish")


_register_exit = getattr(threading, "_register_atexit", atexit.register)


def _close_ref(ref) -> None:
    obj = ref()
    if obj is not None:
        obj.close()


class Analyzer:
    """Sabit `nodes`, `Threads=1`, sabit `Hash`; her analiz öncesi `ucinewgame`."""

    def __init__(self, path: str | None = None, nodes: int = 1_000_000, hash_mb: int = 16):
        self.nodes = int(nodes)
        self.hash_mb = int(hash_mb)
        self.path = find_stockfish(path)
        self._engine: chess.engine.SimpleEngine | None = None
        self._lock = threading.Lock()
        self._failed = False

    # -- yaşam döngüsü -------------------------------------------------------
    @property
    def available(self) -> bool:
        if self.path is None or self._failed:
            return False
        try:
            self._ensure()
        except Exception:
            return False
        return self._engine is not None

    def _ensure(self) -> chess.engine.SimpleEngine | None:
        if self._engine is None and self.path is not None and not self._failed:
            with self._lock:
                if self._engine is None:
                    try:
                        eng = chess.engine.SimpleEngine.popen_uci(self.path)
                        eng.configure({"Threads": 1, "Hash": self.hash_mb})
                        self._engine = eng
                        # Kapatılmayan motorun (daemon olmayan) arka plan iş parçacığı süreç çıkışını kilitler;
                        # atexit iş parçacıkları beklendikten sonra çalıştığı için concurrent.futures'ın
                        # kancası kullanılır.
                        _register_exit(functools.partial(_close_ref, weakref.ref(self)))
                    except Exception:
                        self._failed = True
                        raise
        return self._engine

    def close(self) -> None:
        with self._lock:
            if self._engine is not None:
                try:
                    self._engine.quit()
                except Exception:
                    pass
                self._engine = None

    def __enter__(self) -> "Analyzer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self):  # pragma: no cover
        try:
            self.close()
        except Exception:
            pass

    # -- analiz --------------------------------------------------------------
    def analyse(self, fen: str) -> dict | None:
        """{"cp","mate","best","win_prob"} — hamle sırası olan tarafın bakışından."""
        if not self.available:
            return None
        board = chess.Board(fen)
        if board.is_game_over(claim_draw=False):
            if board.is_checkmate():
                return {"cp": None, "mate": 0, "best": None, "win_prob": 0.0}
            return {"cp": 0, "mate": None, "best": None, "win_prob": 0.5}
        with self._lock:
            eng = self._engine
            if eng is None:
                return None
            # yeni `game` nesnesi → python-chess `ucinewgame` gönderir (hash temizlenir)
            info = eng.analyse(board, chess.engine.Limit(nodes=self.nodes), game=object())
        score = info["score"].pov(board.turn)
        mate = score.mate()
        cp = score.score()
        pv = info.get("pv") or []
        best = pv[0].uci() if pv else None
        return {
            "cp": cp,
            "mate": mate,
            "best": best,
            "win_prob": win_prob(score.score(mate_score=MATE_CP)),
        }

    def win_prob_loss(self, fen: str, move: str) -> float | None:
        """Hamle yapanın kazanma olasılığı kaybı (0..1, ≥ 0); motor yoksa None."""
        before = self.analyse(fen)
        if before is None:
            return None
        board = chess.Board(fen)
        board.push_uci(move)
        after = self.analyse(board.fen())
        if after is None:
            return None
        wp_after = 1.0 - after["win_prob"]  # rakip bakışından → hamle yapana çevir
        return max(0.0, before["win_prob"] - wp_after)
