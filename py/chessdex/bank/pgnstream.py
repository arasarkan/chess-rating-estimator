"""Lichess aylık PGN akışını oyun oyun, ham metin olarak böler.

Neden: python-chess'te `read_headers` yalnızca başlıkları değil oyunun TAMAMINI tüketir; ardından çağrılan
`read_game` bir SONRAKİ oyunu okur (başlık ile hamleler farklı oyunlardan gelir). Bu hata 2026-10-28'de
pozisyonel aday ve geriye dönük test verisini bozdu (docs/results/backtest.md). Burada her oyunun metni
tek parça alınır; başlıklar hızlıca bu metinden ayrıştırılır, hamleler gerekirse AYNI metinden okunur.
"""
from __future__ import annotations

import io
import re
import urllib.request
from typing import Iterable, Iterator

import chess.pgn

_TAG = re.compile(r'^\[(\w+)\s+"(.*)"\]\s*$')


class RawGame:
    __slots__ = ("headers", "text")

    def __init__(self, headers: dict[str, str], text: str):
        self.headers = headers
        self.text = text

    def parse(self) -> chess.pgn.Game | None:
        return chess.pgn.read_game(io.StringIO(self.text))


def split_games(lines: Iterable[str]) -> Iterator[RawGame]:
    """Satır akışını oyunlara böler: her oyun bir `[Event ` satırıyla başlar."""
    buf: list[str] = []
    headers: dict[str, str] = {}
    for line in lines:
        if line.startswith("[Event ") and buf:
            yield RawGame(headers, "".join(buf))
            buf, headers = [], {}
        buf.append(line)
        if line.startswith("["):
            m = _TAG.match(line)
            if m:
                headers[m.group(1)] = m.group(2)
    if buf and headers:
        yield RawGame(headers, "".join(buf))


def stream_games(url: str, max_mb: int) -> Iterator[RawGame]:
    """Uzak .pgn.zst dosyasının ilk `max_mb` MB'ını akışla okur; kesik son oyun atılır."""
    import zstandard

    req = urllib.request.Request(url, headers={"Range": f"bytes=0-{max_mb * 1_000_000}"})
    with urllib.request.urlopen(req) as resp:
        text = io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(resp), encoding="utf-8", errors="replace")
        prev = None
        try:
            for g in split_games(text):
                if prev is not None:
                    yield prev
                prev = g
        except Exception:      # kesik akışın sonu (zstd çerçevesi yarım) → son oyun eksik olabilir, atılır
            return
