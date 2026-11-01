"""Olabilirliğe girmeyen / düşük ağırlıklı hamleler (PLAN: "Olabilirliğe girmeyen hamleler").

Kurallar (sırayla, ilk eşleşen döner):
1. `book`         — USE_BOOK ise ilk BOOK_MAX_PLY yarım hamlede kitapta olan hamle → ağırlık 0
2. `forced`       — tek yasal hamle ya da tüm θ'da P(hamle) > FORCED_PROB → ağırlık 0
3. `decided`      — |eval| > DECIDED_CP → ağırlık DECIDED_WEIGHT
4. `time_trouble` — kalan süre < TIME_TROUBLE_MS → ağırlık TIME_TROUBLE_WEIGHT
Aksi halde (None, 1.0).

Değerler Faz 2 geriye dönük testinde (1.238 kararlı rating'li gerçek rapid oyun, eğitim %70) seçildi;
docs/results/backtest.md. Plan varsayımlarından farklar: kitap dışlaması ve "bitmiş pozisyon" ağırlık düşürmesi
tutulan test grubunda isabeti artırmadı (kapalı); zaman sıkışması 10 sn yerine 30 sn ve tamamen dışlanıyor.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import chess
import numpy as np

USE_BOOK = False           # backtest: kitap dışlaması isabeti artırmadı (Maia açılışı zaten Elo'ya duyarlı)
BOOK_MAX_PLY = 8          # ply 0'dan başlar: ply < 8 kitap kontrolüne girer
FORCED_PROB = 0.9
DECIDED_CP = 300          # etiket için tutulur; ağırlık 1 (backtest: düşürmek isabeti artırmadı)
DECIDED_WEIGHT = 1.0
TIME_TROUBLE_MS = 30_000  # backtest: son 30 sn'deki hamleler gürültü
TIME_TROUBLE_WEIGHT = 0.0

# Yerleşik küçük kitap: popüler açılışların ilk 8 yarım hamlesi (SAN).
BUILTIN_LINES: tuple[str, ...] = (
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6",        # İspanyol
    "e4 e5 Nf3 Nc6 Bb5 Nf6 O-O Nxe4",      # Berlin
    "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6",        # İtalyan
    "e4 e5 Nf3 Nc6 Bc4 Nf6 d3 Bc5",
    "e4 e5 Nf3 Nc6 Bc4 Nf6 Ng5 d5",        # İki at
    "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Nf6",      # İskoç
    "e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4",      # Petrov
    "e4 e5 Nf3 d6 d4 exd4 Nxd4 Nf6",       # Philidor
    "e4 e5 Nc3 Nf6 f4 d5 fxe5 Nxe4",       # Viyana
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6",       # Sicilya
    "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6",
    "e4 c5 Nf3 e6 d4 cxd4 Nxd4 Nc6",
    "e4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7",         # Kapalı Sicilya
    "e4 c5 c3 Nf6 e5 Nd5 d4 cxd4",         # Alapin
    "e4 e6 d4 d5 Nc3 Nf6 Bg5 Be7",         # Fransız
    "e4 e6 d4 d5 e5 c5 c3 Nc6",
    "e4 e6 d4 d5 Nd2 Nf6 e5 Nfd7",
    "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5",       # Caro-Kann
    "e4 c6 d4 d5 e5 Bf5 Nf3 e6",
    "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6",      # İskandinav
    "e4 d6 d4 Nf6 Nc3 g6 Be3 Bg7",         # Pirc
    "e4 g6 d4 Bg7 Nc3 d6 Be3 Nf6",         # Modern
    "e4 Nf6 e5 Nd5 d4 d6 Nf3 Bg4",         # Alekhine
    "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7",         # Vezir gambiti reddi
    "d4 d5 c4 dxc4 Nf3 Nf6 e3 e6",         # VGK
    "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4",        # Slav
    "d4 d5 Nf3 Nf6 Bf4 e6 e3 c5",          # Londra
    "d4 d5 Bf4 Nf6 e3 e6 Nf3 c5",
    "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6",          # Kral Hint
    "d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O",         # Nimzo-Hint
    "d4 Nf6 c4 e6 Nf3 b6 g3 Bb7",          # Vezir Hint
    "d4 Nf6 c4 e6 g3 d5 Bg2 Be7",          # Katalan
    "d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5",       # Grünfeld
    "d4 Nf6 c4 c5 d5 e6 Nc3 exd5",         # Benoni
    "d4 f5 g3 Nf6 Bg2 g6 Nf3 Bg7",         # Hollanda
    "c4 e5 Nc3 Nf6 Nf3 Nc6 g3 d5",         # İngiliz
    "c4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7",
    "c4 Nf6 Nc3 e6 e4 d5 e5 d4",
    "Nf3 d5 g3 Nf6 Bg2 e6 O-O Be7",        # Réti
    "Nf3 Nf6 c4 g6 Nc3 Bg7 e4 d6",
)


def _key(board_or_fen) -> str:
    fen = board_or_fen.fen() if isinstance(board_or_fen, chess.Board) else board_or_fen
    return " ".join(fen.split()[:4])


class OpeningBook:
    """Pozisyon anahtarı (FEN'in ilk 4 alanı) → kitap hamleleri (UCI) kümesi."""

    def __init__(self, entries: dict[str, Iterable[str]] | None = None):
        self._d: dict[str, set[str]] = {}
        for k, v in (entries or {}).items():
            self._d.setdefault(_key(k), set()).update(v)

    def add_line(self, line: str | Iterable[str], max_ply: int = BOOK_MAX_PLY) -> None:
        """SAN (veya UCI) hamle dizisini ilk `max_ply` yarım hamlesiyle ekler."""
        toks = line.split() if isinstance(line, str) else list(line)
        b = chess.Board()
        for tok in toks[:max_ply]:
            try:
                mv = b.parse_san(tok)
            except ValueError:
                mv = chess.Move.from_uci(tok)
                if mv not in b.legal_moves:
                    raise ValueError(f"geçersiz kitap hamlesi: {tok}") from None
            self._d.setdefault(_key(b), set()).add(mv.uci())
            b.push(mv)

    @classmethod
    def from_lines(cls, lines: Iterable[str], max_ply: int = BOOK_MAX_PLY) -> "OpeningBook":
        bk = cls()
        for ln in lines:
            bk.add_line(ln, max_ply)
        return bk

    @classmethod
    def from_json(cls, path: str | Path, include_builtin: bool = False) -> "OpeningBook":
        """JSON biçimi: {"lines": ["e4 e5 ..."], "positions": {"<fen>": ["e2e4"]}}
        ya da doğrudan {"<fen>": ["uci", ...]}."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        bk = cls.from_lines(BUILTIN_LINES) if include_builtin else cls()
        if isinstance(data, list):
            data = {"lines": data}
        if "lines" in data or "positions" in data:
            for ln in data.get("lines", []):
                bk.add_line(ln)
            positions = data.get("positions", {})
        else:
            positions = data
        for k, v in positions.items():
            bk._d.setdefault(_key(k), set()).update(v)
        return bk

    def contains(self, fen: str, move: str) -> bool:
        return move in self._d.get(_key(fen), ())

    def __len__(self) -> int:
        return len(self._d)


_BUILTIN: OpeningBook | None = None


def builtin_book() -> OpeningBook:
    global _BUILTIN
    if _BUILTIN is None:
        _BUILTIN = OpeningBook.from_lines(BUILTIN_LINES)
    return _BUILTIN


def _resolve_book(book) -> OpeningBook:
    if book is None:
        return builtin_book()
    if isinstance(book, OpeningBook):
        return book
    if isinstance(book, (str, Path)):
        return OpeningBook.from_json(book)
    if isinstance(book, dict):
        return OpeningBook(book)
    raise TypeError("book: OpeningBook | dict | JSON yolu | None olmalı")


def exclusion_reason(
    ply: int,
    fen: str,
    move: str,
    grid_probs: np.ndarray | None,
    eval_cp: float | None,
    clock_ms: int | None,
    book=None,
) -> tuple[str | None, float]:
    """Hamlenin dışlanma nedeni ve olabilirlik ağırlığı.

    ply: 0'dan başlayan yarım hamle indeksi; grid_probs: θ ızgarasında P(hamle) (log değil);
    eval_cp: hamle öncesi değerlendirme (herhangi bir bakış, mutlak değer kullanılır; None → atla);
    clock_ms: hamle sonrası kalan süre (None → atla).
    """
    if (USE_BOOK or book is not None) and ply < BOOK_MAX_PLY and _resolve_book(book).contains(fen, move):
        return "book", 0.0
    board = chess.Board(fen)
    if board.legal_moves.count() <= 1:
        return "forced", 0.0
    if grid_probs is not None:
        gp = np.asarray(grid_probs, dtype=np.float64)
        if gp.size and float(gp.min()) > FORCED_PROB:
            return "forced", 0.0
    if eval_cp is not None and abs(float(eval_cp)) > DECIDED_CP:
        return "decided", DECIDED_WEIGHT
    if clock_ms is not None and clock_ms < TIME_TROUBLE_MS:
        return "time_trouble", TIME_TROUBLE_WEIGHT
    return None, 1.0
