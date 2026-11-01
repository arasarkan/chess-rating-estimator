"""Demo senaryo bankası üreticisi (belirlenimci tohum).

Lichess indirmesi olmadan uygulamanın uçtan uca çalışması içindir; kalite gerçek bulmacalardan
düşüktür. Her senaryo python-chess ve küçük aramalarla doğrulanır.

Kullanım: python -m chessdex.bank.demo_gen [OUT.jsonl] [--seed 2026]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Callable, Iterator

import chess

from . import search as S
from .models import BankItem

DEFAULT_SEED = 2026
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "data" / "demo_bank.jsonl"

# Tür/motif başına hedef adet
QUOTAS = {
    "mate1": 16, "mate2": 16, "mate3": 8, "hanging": 8, "tactic3": 16,
    "eg_mate1": 6, "eg_mate2": 6, "eg_mate3": 6, "eg_tactic": 10,
    "defense": 20, "positional": 24,
}
TACTIC_DEPTH = 3
DEFENSE_DEPTH = 2
POSITIONAL_DEPTH = 2


# ---------------------------------------------------------------- pozisyon kaynakları

def _greedy_move(board: chess.Board, rng: random.Random) -> chess.Move:
    """Yarı açgözlü politika: çoğu zaman güvenli görünen almayı, yoksa rastgele hamleyi seçer."""
    moves = list(board.legal_moves)
    if rng.random() < 0.65:
        best, best_v = None, 0
        for m in moves:
            if not board.is_capture(m):
                continue
            victim = board.piece_type_at(m.to_square) or chess.PAWN
            v = S.VALUES[victim]
            if board.is_attacked_by(not board.turn, m.to_square):
                v -= S.VALUES[board.piece_type_at(m.from_square)]
            v += rng.randint(0, 40)
            if v > best_v:
                best, best_v = m, v
        if best is not None:
            return best
    # Rastgele hamle; geliştirme hamlelerini hafifçe tercih et
    return moves[rng.randrange(len(moves))]


def playout_positions(rng: random.Random, min_ply: int = 8, max_ply: int = 90) -> Iterator[chess.Board]:
    """Yarı rastgele oyunlardan pozisyonlar (her oyundan birkaç örnek)."""
    while True:
        b = chess.Board()
        for ply in range(max_ply):
            if b.is_game_over():
                break
            if ply >= min_ply and rng.random() < 0.25:
                yield chess.Board(b.fen())
            b.push(_greedy_move(b, rng))


def random_sparse(rng: random.Random, white: list[int], black: list[int]) -> chess.Board | None:
    """Verilen taşlarla rastgele yasal pozisyon (sıra beyazda)."""
    b = chess.Board(None)
    squares = list(range(64))
    rng.shuffle(squares)
    pieces = [(chess.KING, chess.WHITE), (chess.KING, chess.BLACK)]
    pieces += [(p, chess.WHITE) for p in white] + [(p, chess.BLACK) for p in black]
    for (pt, col), sq in zip(pieces, squares):
        if pt == chess.PAWN and chess.square_rank(sq) in (0, 7):
            return None
        b.set_piece_at(sq, chess.Piece(pt, col))
    b.turn = chess.WHITE
    if not b.is_valid() or b.is_game_over():
        return None
    return b


# ---------------------------------------------------------------- yardımcılar

def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _rating(rng: random.Random, base: float, lo: float, hi: float, sd: float = 70.0) -> float:
    return float(round(_clip(base + rng.gauss(0, sd), lo, hi)))


def _move_kind(board: chess.Board, m: chess.Move) -> str:
    if board.gives_check(m):
        return "check"
    if board.is_capture(m):
        return "capture"
    return "quiet"


def _n_checks(board: chess.Board) -> int:
    return sum(1 for m in board.legal_moves if board.gives_check(m))


def _sole(lst: list) -> bool:
    return len(lst) == 1


def _best_gap(scores: dict[str, int]) -> tuple[str, int, int]:
    """(en iyi hamle, en iyi skor, ikinci en iyi skor)."""
    ordered = sorted(scores.items(), key=lambda kv: -kv[1])
    best, v1 = ordered[0]
    v2 = ordered[1][1] if len(ordered) > 1 else -S.INF
    return best, v1, v2


def _hardest_reply(board: chess.Board, n: int) -> tuple[chess.Move, list[chess.Move]] | None:
    """Mat-n sonrası savunma: tek anahtarlı, kısaltılamayan cevaplar arasında en çok yasal hamlesi olanı seçer."""
    best = None
    for r in board.legal_moves:
        board.push(r)
        keys = S.mate_keys(board, n)
        # tek anahtar ve daha kısa mat yok → gerçek mat-n devamı
        good = len(keys) == 1 and S.mate_distance(board, n - 1) is None
        score = (good, board.legal_moves.count())
        board.pop()
        if keys and (best is None or score > best[0]):
            best = (score, r, keys)
    if best is None or not best[0][0]:
        return None
    return best[1], best[2]


# ---------------------------------------------------------------- üreticiler (her biri dict döndürür ya da None)

def gen_mate1(board: chess.Board, rng: random.Random, kind="tactics") -> dict | None:
    keys = S.mating_moves(board)
    if not _sole(keys):
        return None
    m = keys[0]
    piece = board.piece_type_at(m.from_square)
    decoys = _n_checks(board) - 1
    base = 700 + 60 * decoys + (120 if piece != chess.QUEEN else 0) + (150 if board.is_capture(m) is False and piece != chess.QUEEN else 0)
    base += 4 * (board.legal_moves.count() - 25)
    return dict(solution=[m.uci()], themes=["mate", "mateIn1", "oneMove"], kind=kind,
                rating=_rating(rng, base, 600, 1350), meta={"motif": "mate", "mate_in": 1})


def gen_mate2(board: chess.Board, rng: random.Random, kind="tactics") -> dict | None:
    if S.mating_moves(board):
        return None
    keys = S.mate_keys(board, 2)
    if not _sole(keys):
        return None
    m1 = keys[0]
    mk = _move_kind(board, m1)
    board.push(m1)
    n_replies = board.legal_moves.count()
    # Rakibin en dirençli cevabı: mat eden en az hamlesi olan
    best = None
    for r in board.legal_moves:
        board.push(r)
        mates = S.mating_moves(board)
        board.pop()
        if mates and (best is None or len(mates) < len(best[1])):
            best = (r, mates)
    board.pop()
    r1, mates = best
    base = 1300 + {"check": 0, "capture": 120, "quiet": 450}[mk] + 15 * n_replies
    return dict(solution=[m1.uci(), r1.uci(), mates[0].uci()], themes=["mate", "mateIn2"], kind=kind,
                rating=_rating(rng, base, 1050, 2350), meta={"motif": "mate", "mate_in": 2, "key": mk})


def gen_mate3(board: chess.Board, rng: random.Random, kind="tactics", forcing_only=True) -> dict | None:
    """Mat-3: anahtar adaylar (yalnız şahlar ya da tüm hamleler), anahtar tek olmalı."""
    if S.mating_moves(board) or S.has_mate_in(board, 2):
        return None
    cands = [m for m in board.legal_moves if board.gives_check(m)] if forcing_only else None
    keys = S.mate_keys(board, 3, cands)
    if not _sole(keys):
        return None
    if forcing_only:
        # şah olmayan almaların da mat-3 vermediğini kontrol et
        caps = [m for m in board.legal_moves if board.is_capture(m) and not board.gives_check(m)]
        if S.mate_keys(board, 3, caps):
            return None
    m1 = keys[0]
    mk = _move_kind(board, m1)
    board.push(m1)
    hr = _hardest_reply(board, 2)
    if hr is None:
        board.pop()
        return None
    r1, k2 = hr
    board.push(r1)
    board.push(k2[0])
    best = None
    for r in board.legal_moves:
        board.push(r)
        mates = S.mating_moves(board)
        board.pop()
        if mates and (best is None or len(mates) < len(best[1])):
            best = (r, mates)
    board.pop(); board.pop(); board.pop()
    r2, mates = best
    base = 2280 + {"check": 0, "capture": 100, "quiet": 250}[mk] - (100 if kind == "endgame" else 0)
    return dict(solution=[m1.uci(), r1.uci(), k2[0].uci(), r2.uci(), mates[0].uci()],
                themes=["mate", "mateIn3"], kind=kind, rating=_rating(rng, base, 1850, 2600, 130),
                meta={"motif": "mate", "mate_in": 3, "key": mk})


def _tactic(board: chess.Board, rng: random.Random, kind: str, require_balanced: bool) -> dict | None:
    """Malzeme kazandıran tek hamle (derinlik-3 arama, en az 250 kazanç, ikinciden 200 fark)."""
    static = S.material(board, board.turn)
    if require_balanced and abs(static) > 200:
        return None
    if board.is_check() or S.mating_moves(board):
        return None
    scores = S.root_scores(board, TACTIC_DEPTH)
    best, v1, v2 = _best_gap(scores)
    if S.is_mate_score(v1) or v1 - static < 250 or v1 - v2 < 200:
        return None
    m1 = chess.Move.from_uci(best)
    mk = _move_kind(board, m1)
    # Basit "asılı taş" mı? Alınan taş geri alınamıyorsa 1 hamlelik.
    immediate = board.is_capture(m1)
    board.push(m1)
    sol = [best]
    if not board.is_game_over():
        # Rakibin en iyi cevabı (derinlik-2)
        rsc = S.root_scores(board, TACTIC_DEPTH - 1)
        r1 = max(rsc, key=lambda u: rsc[u])
        board.push(chess.Move.from_uci(r1))
        if not board.is_game_over():
            s2 = S.root_scores(board, 1)
            b2, w1, w2 = _best_gap(s2)
            # İkinci oyuncu hamlesi de tek ve kazancı tamamlıyorsa çözüme ekle
            if w1 - w2 >= 200 and not S.is_mate_score(w1):
                sol += [r1, b2]
        board.pop()
    board.pop()
    gain = v1 - static
    one_move = len(sol) == 1
    if one_move and immediate and mk == "capture":
        motif, base = "hanging", 750 + rng.uniform(-50, 150)
    else:
        sac = immediate and S.VALUES[board.piece_type_at(m1.from_square)] > S.VALUES.get(board.piece_type_at(m1.to_square) or chess.PAWN, 100)
        base = 1250 + {"check": 0, "capture": 80, "quiet": 550}[mk] + (250 if sac else 0) - 0.15 * (gain - 300)
        motif = "material"
    if kind == "endgame":
        base += 100
    return dict(solution=sol, themes=["crushing" if gain >= 500 else "advantage"] + (["hangingPiece"] if motif == "hanging" else []),
                kind=kind, rating=_rating(rng, base, 650, 2450),
                meta={"motif": motif, "depth": TACTIC_DEPTH, "gain": int(gain), "margin": int(v1 - v2), "key": mk})


def gen_mid_tactic(board, rng):
    """Orta oyun taktiği; motife göre 'hanging' ya da 'tactic3' kovasına gider."""
    d = _tactic(board, rng, "tactics", True)
    if d:
        d["bucket"] = "hanging" if d["meta"]["motif"] == "hanging" else "tactic3"
    return d


def gen_defense(board: chess.Board, rng: random.Random) -> dict | None:
    """Tehdit altındaki tek kurtarıcı hamle (derinlik-2 arama)."""
    if board.is_check() or board.legal_moves.count() < 6:
        return None
    static = S.material(board, board.turn)
    if abs(static) > 250 or S.mating_moves(board):
        return None
    # Boş hamle: rakip şimdi oynasa ne kazanır?
    board.push(chess.Move.null())
    threat = -S.negamax(board, 1, ply=1)
    board.pop()
    if not (static - threat >= 250):
        return None
    scores = S.root_scores(board, DEFENSE_DEPTH)
    best, v1, v2 = _best_gap(scores)
    if S.is_mate_score(v1) or v1 < static - 60 or v1 - static > 150 or v1 - v2 < 200:
        return None
    # Kaç hamle kaybeder? Çoğu kaybediyorsa daha kolay değil, tersine daha az ipucu var.
    n_losing = sum(1 for v in scores.values() if v < static - 200)
    m1 = chess.Move.from_uci(best)
    mk = _move_kind(board, m1)
    mate_threat = S.is_mate_score(threat) or threat < -S.MATE // 2
    base = 1150 + {"check": -50, "capture": 50, "quiet": 350}[mk] + (150 if mate_threat else 0) + 6 * min(n_losing, 30)
    return dict(solution=[best], themes=["defensiveMove"] + (["quietMove"] if mk == "quiet" else []), kind="defense",
                rating=_rating(rng, base, 850, 2300),
                meta={"motif": "defense", "depth": DEFENSE_DEPTH, "margin": int(v1 - v2),
                      "threat": "mate" if mate_threat else "material"})


def gen_positional(board: chess.Board, rng: random.Random) -> dict | None:
    """Çoktan seçmeli 'en iyi plan' (demo kalitesi: malzeme + hareketlilik + merkez)."""
    if board.is_check() or board.legal_moves.count() < 15:
        return None
    static = S.material(board, board.turn)
    if abs(static) > 150 or chess.popcount(board.occupied) < 16:
        return None
    mat = S.root_scores(board, 2)
    _, mv1, _ = _best_gap(mat)
    if S.is_mate_score(mv1) or mv1 - static > 80:  # taktik varsa pozisyonel değil
        return None
    scores = S.root_scores(board, POSITIONAL_DEPTH, evalf=S.eval_positional)
    ordered = sorted(scores.items(), key=lambda kv: -kv[1])
    best, v1 = ordered[0]
    if len(ordered) < 2 or v1 - ordered[1][1] < 15:
        return None

    def pick(lo, hi):
        pool = [u for u, v in ordered[1:] if lo <= v1 - v < hi]
        return pool[rng.randrange(len(pool))] if pool else None

    c2, c1, c0 = pick(25, 90), pick(90, 220), pick(220, 10**9)
    if not (c2 and c1 and c0):
        return None
    choices = [best, c2, c1, c0]
    rng.shuffle(choices)
    move_scores = {best: 3, c2: 2, c1: 1, c0: 0}
    gap = v1 - scores[c2]
    base = 950 + 9 * (90 - gap) + (150 if _move_kind(board, chess.Move.from_uci(best)) == "quiet" else 0)
    return dict(solution=[best], themes=["positional", "demoQuality"], kind="positional", choices=choices,
                move_scores=move_scores, rating=_rating(rng, base, 800, 2300),
                meta={"motif": "positional", "demo_quality": True, "evals": {u: int(scores[u]) for u in choices}})


# ---------------------------------------------------------------- oyun sonu kaynakları

EG_MATE_SETS = [([chess.QUEEN], []), ([chess.ROOK], []), ([chess.ROOK, chess.PAWN], [chess.PAWN]),
                ([chess.QUEEN], [chess.PAWN]), ([chess.ROOK, chess.BISHOP], [chess.PAWN])]
EG_TACTIC_SETS = [
    ([chess.ROOK, chess.PAWN], [chess.ROOK]), ([chess.QUEEN], [chess.ROOK]), ([chess.KNIGHT, chess.PAWN], [chess.ROOK]),
    ([chess.ROOK, chess.PAWN, chess.PAWN], [chess.ROOK, chess.PAWN]), ([chess.BISHOP, chess.PAWN], [chess.KNIGHT, chess.PAWN]),
    ([chess.QUEEN, chess.PAWN], [chess.QUEEN]), ([chess.ROOK], [chess.BISHOP, chess.PAWN]),
]


def _eg_positions(rng: random.Random, sets) -> Iterator[chess.Board]:
    while True:
        w, bl = sets[rng.randrange(len(sets))]
        b = random_sparse(rng, w, bl)
        if b is not None:
            if rng.random() < 0.5:  # siyah açısından da üret
                b = b.mirror()
            yield b


def gen_eg_mate(n: int) -> Callable:
    def g(board: chess.Board, rng: random.Random) -> dict | None:
        if S.mate_distance(board, n - 1) is not None:
            return None
        if n == 1:
            d = gen_mate1(board, rng, kind="endgame")
            if d:
                d["rating"] = _rating(rng, 750 + (150 if board.pieces_mask(chess.QUEEN, board.turn) == 0 else 0), 600, 1200)
        elif n == 2:
            d = gen_mate2(board, rng, kind="endgame")
            if d:
                d["rating"] = _rating(rng, d["rating"] - 50, 1100, 2000)
        else:
            d = gen_mate3(board, rng, kind="endgame", forcing_only=False)
        if d:
            d["themes"] = ["endgame"] + d["themes"]
        return d
    return g


def gen_eg_tactic(board: chess.Board, rng: random.Random) -> dict | None:
    d = _tactic(board, rng, "endgame", False)
    if d is None or d["meta"]["motif"] == "hanging" and rng.random() < 0.7:
        return None
    d["themes"] = ["endgame"] + d["themes"]
    return d


# ---------------------------------------------------------------- ana döngü

def _make_item(idx: int, board: chess.Board, d: dict) -> BankItem:
    meta = dict(d["meta"])
    n_pieces = chess.popcount(board.occupied)
    meta["n_pieces"] = n_pieces
    if d["kind"] == "endgame":
        meta["tablebase_check"] = n_pieces <= 7
    return BankItem(
        id=f"demo:{idx:04d}", source="demo-generated", fen=board.fen(), solution=d["solution"], kind=d["kind"],
        themes=d["themes"], puzzle_rating=d["rating"], rating_dev=None, n_plays=None,
        choices=d.get("choices"), move_scores=d.get("move_scores"), meta=meta,
    )


def generate(seed: int = DEFAULT_SEED, quotas: dict[str, int] | None = None, verbose: bool = False,
             max_tries: int = 200_000) -> list[BankItem]:
    """Kotalar dolana kadar pozisyon tarar; belirlenimci."""
    q = dict(QUOTAS if quotas is None else quotas)
    rng = random.Random(seed)
    mid = playout_positions(random.Random(seed + 1))
    eg_mate = _eg_positions(random.Random(seed + 2), EG_MATE_SETS)
    eg_tac = _eg_positions(random.Random(seed + 3), EG_TACTIC_SETS)
    # (kovalar, üretici, kaynak); üretici birden çok kovayı besleyebilir (d["bucket"])
    plan: list[tuple[tuple[str, ...], Callable, Iterator[chess.Board]]] = [
        (("mate1",), gen_mate1, mid), (("mate2",), gen_mate2, mid), (("mate3",), gen_mate3, mid),
        (("hanging", "tactic3"), gen_mid_tactic, mid),
        (("defense",), gen_defense, mid), (("positional",), gen_positional, mid),
        (("eg_mate1",), gen_eg_mate(1), eg_mate), (("eg_mate2",), gen_eg_mate(2), eg_mate),
        (("eg_mate3",), gen_eg_mate(3), eg_mate), (("eg_tactic",), gen_eg_tactic, eg_tac),
    ]
    items: list[BankItem] = []
    seen: set[str] = set()
    t0 = time.time()
    for buckets, fn, source in plan:
        got = {b: 0 for b in buckets}
        tries = 0
        while any(got[b] < q.get(b, 0) for b in buckets) and tries < max_tries:
            tries += 1
            board = next(source)
            key = board.board_fen()
            if key in seen:
                continue
            d = fn(board, rng)
            if d is None:
                continue
            bucket = d.pop("bucket", buckets[0])
            if got[bucket] >= q.get(bucket, 0):
                continue
            seen.add(key)
            d["meta"]["generator"] = bucket
            items.append(_make_item(len(items), board, d))
            got[bucket] += 1
        if verbose:
            stat = ", ".join(f"{b}: {got[b]}/{q.get(b, 0)}" for b in buckets)
            print(f"{stat} ({tries} deneme, {time.time() - t0:.1f}s)", file=sys.stderr)
    return items


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Demo senaryo bankası üret")
    ap.add_argument("output", nargs="?", default=str(DEFAULT_OUT))
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = ap.parse_args(argv)
    items = generate(args.seed, verbose=True)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it.to_dict(), ensure_ascii=False) + "\n")
    print(f"{len(items)} senaryo -> {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
