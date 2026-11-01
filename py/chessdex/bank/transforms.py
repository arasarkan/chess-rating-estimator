"""Ezberi önleme dönüşümleri: renk takası ve yatay ayna (a↔h)."""
from __future__ import annotations

import dataclasses
from typing import Any, Callable, Sequence

import chess

TRANSFORMS = ("identity", "color_swap", "mirror", "both")


def _map_uci(uci: str, sq_map: Callable[[int], int]) -> str:
    m = chess.Move.from_uci(uci)
    return chess.Move(sq_map(m.from_square), sq_map(m.to_square), promotion=m.promotion, drop=m.drop).uci()


def _flip_file(sq: int) -> int:
    return chess.square(7 - chess.square_file(sq), chess.square_rank(sq))


def color_swap(fen: str, moves: Sequence[str]) -> tuple[str, list[str]]:
    """Tahtayı dikey çevirir, renkleri/sırayı/rok haklarını/geçerken alma karesini değiştirir."""
    board = chess.Board(fen)
    swapped = board.mirror()  # python-chess: dikey çevirme + renk takası + sıra + rok + ep
    return swapped.fen(), [_map_uci(u, chess.square_mirror) for u in moves]


def mirror(fen: str, moves: Sequence[str]) -> tuple[str, list[str]]:
    """a↔h aynası; yalnızca rok hakkı yoksa geçerli (aksi halde ValueError)."""
    board = chess.Board(fen)
    if board.castling_rights:
        raise ValueError("rok hakkı olan pozisyonda yatay ayna geçersiz")
    flipped = board.transform(chess.flip_horizontal)
    return flipped.fen(), [_map_uci(u, _flip_file) for u in moves]


def valid_transforms(fen: str) -> list[str]:
    """Bu pozisyonda geçerli dönüşüm adları."""
    if chess.Board(fen).castling_rights:
        return ["identity", "color_swap"]
    return list(TRANSFORMS)


def apply_transform(fen: str, moves: Sequence[str], name: str) -> tuple[str, list[str]]:
    """Adıyla dönüşüm uygular."""
    if name == "identity":
        return chess.Board(fen).fen(), list(moves)
    if name == "color_swap":
        return color_swap(fen, moves)
    if name == "mirror":
        return mirror(fen, moves)
    if name == "both":
        f, m = mirror(fen, moves)
        return color_swap(f, m)
    raise ValueError(f"bilinmeyen dönüşüm: {name}")


def map_move(uci: str, name: str) -> str:
    """Tek bir hamleyi dönüşümle eşler (dönüşümler kendi tersidir)."""
    if name == "identity":
        return uci
    if name == "color_swap":
        return _map_uci(uci, chess.square_mirror)
    if name == "mirror":
        return _map_uci(uci, _flip_file)
    if name == "both":
        return _map_uci(_map_uci(uci, _flip_file), chess.square_mirror)
    raise ValueError(f"bilinmeyen dönüşüm: {name}")


def _pick(rng: Any, n: int) -> int:
    if hasattr(rng, "integers"):  # numpy Generator
        return int(rng.integers(n))
    return int(rng.randrange(n))  # random.Random


def random_transform(fen: str, moves: Sequence[str], rng: Any) -> tuple[str, list[str], str]:
    """Geçerli dönüşümlerden birini rastgele seçip uygular → (fen, moves, ad)."""
    options = valid_transforms(fen)
    name = options[_pick(rng, len(options))]
    f, m = apply_transform(fen, moves, name)
    return f, m, name


def transform_item(item: Any, name: str) -> Any:
    """BankItem'ın dönüştürülmüş kopyası (fen, çözüm, seçenekler, hamle puanları)."""
    fen, sol = apply_transform(item.fen, item.solution, name)
    choices = [map_move(u, name) for u in item.choices] if item.choices else item.choices
    scores = {map_move(u, name): s for u, s in item.move_scores.items()} if item.move_scores else item.move_scores
    meta = dict(item.meta)
    meta["transform"] = name
    return dataclasses.replace(item, fen=fen, solution=sol, choices=choices, move_scores=scores, meta=meta)
