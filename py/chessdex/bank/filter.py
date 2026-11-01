"""Lichess bulmaca CSV'sini akış halinde okuyup filtreler; bant başına tabakalı örnekleme CLI'ı.

Lichess biçimi: FEN rakibin kurulum hamlesinden ÖNCEKİ pozisyondur; Moves[0] rakibin hamlesi,
oyuncunun çözümü Moves[1]'den başlar. Burada kurulum hamlesi uygulanır.

Kullanım: python -m chessdex.bank.filter IN.csv[.zst] OUT.jsonl --per-band 2000
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import random
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator

import chess

from .models import BankItem

COLUMNS = [
    "PuzzleId", "FEN", "Moves", "Rating", "RatingDeviation", "Popularity",
    "NbPlays", "Themes", "GameUrl", "OpeningTags",
]
TABLEBASE_MAX_PIECES = 7


@contextmanager
def _open_text(path: str | Path):
    """.csv ya da .csv.zst dosyasını metin akışı olarak açar (zstandard isteğe bağlı)."""
    p = Path(path)
    if p.suffix == ".zst":
        try:
            import zstandard  # type: ignore
        except ImportError as e:  # pragma: no cover - ortama bağlı
            raise RuntimeError(".zst için 'pip install zstandard' gerekli") from e
        with open(p, "rb") as fh:
            reader = zstandard.ZstdDecompressor().stream_reader(fh)
            yield io.TextIOWrapper(reader, encoding="utf-8", newline="")
    else:
        with open(p, "r", encoding="utf-8", newline="") as fh:
            yield fh


def classify_kind(themes: Iterable[str], n_pieces: int) -> tuple[str, bool]:
    """Temalardan tür → (tür, tablebase_kontrolü_gerekir_mi)."""
    ts = set(themes)
    tb = "endgame" in ts and n_pieces <= TABLEBASE_MAX_PIECES
    # Savunma/sessiz hamle temaları nadir (~%3); oyun sonu teması ise yarıya yakın bulmacada var.
    # Bu yüzden savunma önceliklidir, aksi halde %15 hedefi karşılanamaz.
    if "defensiveMove" in ts or "quietMove" in ts:
        return "defense", tb
    if "endgame" in ts:
        return "endgame", tb
    return "tactics", False


def row_to_item(row: dict[str, str]) -> BankItem | None:
    """Tek CSV satırı → kurulum hamlesi uygulanmış BankItem (bozuk satırda None)."""
    try:
        moves = row["Moves"].split()
        board = chess.Board(row["FEN"])
        setup = chess.Move.from_uci(moves[0])
        if setup not in board.legal_moves:
            return None
        board.push(setup)
        fen = board.fen()
        # çözümün tümü yasal mı?
        b2 = board.copy()
        for u in moves[1:]:
            m = chess.Move.from_uci(u)
            if m not in b2.legal_moves:
                return None
            b2.push(m)
        themes = row.get("Themes", "").split()
        n_pieces = chess.popcount(board.occupied)
        kind, tb = classify_kind(themes, n_pieces)
        return BankItem(
            id=f"lichess:{row['PuzzleId']}",
            source="lichess",
            fen=fen,
            solution=moves[1:],
            kind=kind,
            themes=themes,
            puzzle_rating=float(row["Rating"]),
            rating_dev=float(row["RatingDeviation"]),
            n_plays=int(row["NbPlays"]),
            meta={
                "puzzle_id": row["PuzzleId"],
                "game_url": row.get("GameUrl") or None,
                "opening_tags": (row.get("OpeningTags") or "").split(),
                "popularity": int(row["Popularity"]),
                "n_pieces": n_pieces,
                "tablebase_check": tb,
            },
        )
    except (KeyError, ValueError, IndexError):
        return None


def passes(row: dict[str, str], *, max_rd: float, min_plays: int, min_popularity: int,
           min_len: int, max_len: int) -> bool:
    """Ham satır filtreleri. Uzunluk, plandaki gibi Lichess `Moves` alanı (kurulum hamlesi dahil) üzerinden sayılır:
    2–6 → oyuncu açısından 1–5 yarım hamlelik çözüm (mat-in-1 dahil)."""
    try:
        n = len(row["Moves"].split())
        return (
            float(row["RatingDeviation"]) < max_rd
            and int(row["NbPlays"]) > min_plays
            and int(row["Popularity"]) > min_popularity
            and min_len <= n <= max_len
        )
    except (KeyError, ValueError):
        return False


def iter_filtered(
    csv_path: str | Path,
    *,
    max_rd: float = 80,
    min_plays: int = 1000,
    min_popularity: int = 70,
    min_len: int = 2,
    max_len: int = 6,
) -> Iterator[BankItem]:
    """Filtreden geçen bulmacaları BankItem olarak akıtır (bellek sabit)."""
    with _open_text(csv_path) as fh:
        first = fh.readline()
        header = next(csv.reader([first]))
        if header and header[0] == "PuzzleId":
            reader = csv.DictReader(fh, fieldnames=header)
        else:  # başlıksız dosya
            reader = csv.DictReader(io.StringIO(first), fieldnames=COLUMNS)
            yield from _filter_rows(reader, max_rd, min_plays, min_popularity, min_len, max_len)
            reader = csv.DictReader(fh, fieldnames=COLUMNS)
        yield from _filter_rows(reader, max_rd, min_plays, min_popularity, min_len, max_len)


def _filter_rows(reader, max_rd, min_plays, min_popularity, min_len, max_len) -> Iterator[BankItem]:
    for row in reader:
        if not passes(row, max_rd=max_rd, min_plays=min_plays, min_popularity=min_popularity,
                      min_len=min_len, max_len=max_len):
            continue
        item = row_to_item(row)
        if item is not None:
            yield item


def band_of(rating: float, width: int = 100) -> int:
    """Rating bandının alt sınırı (ör. 1537 → 1500)."""
    return int(rating // width) * width


# Lichess bulmacalarından gelen türlerin bant içi hedef payları (plan payları, pozisyonel hariç yeniden ölçeklenmiş).
KIND_SHARES = {"tactics": 0.40 / 0.75, "endgame": 0.20 / 0.75, "defense": 0.15 / 0.75}


def stratified_sample(items: Iterable[BankItem], per_band: int, rng: random.Random,
                      width: int = 100, shares: dict[str, float] | None = None) -> dict[int, list[BankItem]]:
    """Her (bant, tür) için rezervuar örneklemesi (Algoritma R), sonra her bant tür paylarına göre
    `per_band`'e kadar doldurulur; bir türde yeterli senaryo yoksa açık diğer türlerden kapatılır."""
    shares = shares or KIND_SHARES
    res: dict[tuple[int, str], list[BankItem]] = {}
    seen: dict[tuple[int, str], int] = {}
    for it in items:
        key = (band_of(it.puzzle_rating, width), it.kind)
        n = seen.get(key, 0) + 1
        seen[key] = n
        bucket = res.setdefault(key, [])
        if len(bucket) < per_band:
            bucket.append(it)
        else:
            j = rng.randrange(n)
            if j < per_band:
                bucket[j] = it
    out: dict[int, list[BankItem]] = {}
    for band in sorted({b for b, _ in res}):
        pools = {k: v for (b, k), v in res.items() if b == band}
        quota = {k: int(round(per_band * shares.get(k, 0.0))) for k in pools}
        chosen = {k: pools[k][: quota[k]] for k in pools}
        free = per_band - sum(len(v) for v in chosen.values())
        for k in sorted(pools, key=lambda k: -shares.get(k, 0.0)):   # açığı büyük paylı türlerden kapat
            extra = pools[k][len(chosen[k]):][: max(free, 0)]
            chosen[k] += extra
            free -= len(extra)
        out[band] = [it for k in sorted(chosen) for it in chosen[k]]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lichess bulmacalarını filtrele ve banda göre örnekle")
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--per-band", type=int, default=2000)
    ap.add_argument("--band-width", type=int, default=100)
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--max-rd", type=float, default=80)
    ap.add_argument("--min-plays", type=int, default=1000)
    ap.add_argument("--min-popularity", type=int, default=70)
    ap.add_argument("--min-len", type=int, default=2, help="Moves alanı uzunluğu (kurulum dahil)")
    ap.add_argument("--max-len", type=int, default=6)
    args = ap.parse_args(argv)

    it = iter_filtered(args.input, max_rd=args.max_rd, min_plays=args.min_plays,
                       min_popularity=args.min_popularity, min_len=args.min_len, max_len=args.max_len)
    bands = stratified_sample(it, args.per_band, random.Random(args.seed), args.band_width)
    n = 0
    with open(args.output, "w", encoding="utf-8") as out:
        for band in sorted(bands):
            for item in sorted(bands[band], key=lambda x: x.id):
                out.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
                n += 1
    summary = ", ".join(f"{b}:{len(v)}" for b, v in sorted(bands.items()))
    print(f"{n} senaryo yazıldı -> {args.output} [{summary}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
