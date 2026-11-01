"""Pozisyonel senaryoların Maia-2 ile tasarımı ve zorluk kalibrasyonu (insan verisiyle çapalanmış).

Bulgular (docs/results/maia2.md):
- (Düzeltildi 2026-10-29: "oyun verisi rating etkisi göstermez" bulgusu PGN okuma hatasıydı; doğru veride etki güçlü
  ve bu çapalı b'ler gerçek oyun kararlarıyla doğrulandı — docs/results/backtest.md.)
- Maia-2'nin pozisyon içi seviye duyarlılığı gerçek insan farklarından çok zayıftır: Lichess bulmacalarında
  (insan ayırt ediciliği bilinen) Maia eğimi medyan a ≈ 0.07, üçte biri ters. Bu yüzden Maia'dan a ALINMAZ.
- Maia-2 zorluk SIRALAMASINI taşır: bir hamlenin bulunma olasılığı gerçek bulmaca rating'iyle ilişkilidir.

Yöntem:
  anchor  Lichess bulmacalarında (zorluğu milyonlarca insan denemesiyle ölçülmüş) serbest yanıt
          P_maia(ilk çözüm hamlesi | θ_j) eğrisinin seviyeler üzerindeki ortalama logit'i L̄ ile bulmaca
          rating'i arasında doğrusal eşleme kurar: rating ≈ α + β·L̄.
  design  Her pozisyon için şıklar: doğru = Stockfish en iyisi (3); çeldiriciler = puanı < 3 aday hamlelerden
          zayıf seviyenin güçlüye göre en çok tercih ettikleri (log P_903 − log P_2137), en az biri ≤ 1 puanlı.
          Ters ayırt eden (4 şıklı seçimde güçlüler doğru şıkkı daha AZ seçiyor) senaryolar dışlanır.
          Zorluk: serbest yanıtta P(puan ≥ k) eğrilerinin L̄_k'sı çapa ile b_k'ya çevrilir;
          b = b_2, offsets = (b_1 − b_2, 0, b_3 − b_2), c = 1/4.
          a: çapanın artık sapması σ_b (~476 Elo) kadar b belirsizliği cevap eğrisine marjinalleştirilir
          (probit yaklaşımı): a = 1 / √(1 + (σ_b / (400/ln10 · 1.702))²) ≈ 0.53 — model bu senaryolara
          bilinen belirsizliği kadar az güvenir.
          Senaryolar `provisional` işaretlidir; gerçek a ve b pilot cevaplarıyla öğrenilir.

Kullanım (py/):
  python -m chessdex.bank.maia_calib anchor data/bank_puzzles.jsonl ../data/raw/maia_anchor.json
  python -m chessdex.bank.maia_calib design ../data/raw/pos_labeled.jsonl ../data/raw/maia_anchor.json data/positional.jsonl
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

from chessdex.engines.human import MAIA_CENTERS, Maia2Model

from .loader import load_items
from .models import BankItem

B_MIN, B_MAX = 300.0, 2900.0
OFFSET_MAX = 1000.0
CLIP = 0.005             # logit için olasılık kırpma
ANCHOR_N = 3000          # çapa için örneklenen bulmaca sayısı


def logit10(p: np.ndarray) -> np.ndarray:
    p = np.clip(p, CLIP, 1 - CLIP)
    return np.log10(p / (1 - p))


def slope(F: np.ndarray, theta: np.ndarray = MAIA_CENTERS) -> float:
    """Satırlar ortak eğimli logit doğrusu; Elo ölçeğinde a (= 400·eğim). Yalnızca tanı/işaret için."""
    K, J = F.shape
    X = np.zeros((K * J, 1 + K))
    X[:, 0] = np.tile(theta, K)
    for k in range(K):
        X[k * J:(k + 1) * J, 1 + k] = 1.0
    coef, *_ = np.linalg.lstsq(X, logit10(F).ravel(), rcond=None)
    return float(400.0 * coef[0])


# ------------------------------------------------------------------ çapa
def fit_anchor(maia: Maia2Model, puzzles: list[BankItem], n: int = ANCHOR_N, seed: int = 3) -> dict:
    pool = [p for p in puzzles if not p.meta.get("relaxed")]
    random.Random(seed).shuffle(pool)
    L, R, A = [], [], []
    for it in pool[:n]:
        moves, P = maia.forward(it.fen, MAIA_CENTERS, MAIA_CENTERS)
        F = P[:, moves.index(it.solution[0])][None, :]
        L.append(float(logit10(F).mean()))
        R.append(it.puzzle_rating)
        A.append(slope(F))
    L, R, A = map(np.array, (L, R, A))
    beta, alpha = np.polyfit(L, R, 1)
    resid = R - (alpha + beta * L)
    return {"alpha": float(alpha), "beta": float(beta), "r": float(np.corrcoef(L, R)[0, 1]),
            "resid_sd": float(resid.std()), "n": int(len(R)),
            "puzzle_maia_a": {"median": float(np.median(A)), "p10": float(np.percentile(A, 10)),
                              "p90": float(np.percentile(A, 90)), "negative_frac": float((A < 0).mean())}}


def anchor_b(L: float, anchor: dict) -> float:
    return anchor["alpha"] + anchor["beta"] * L


def marginal_a(resid_sd: float, a: float = 1.0) -> float:
    """b ~ N(b̂, σ_b²) belirsizliği altında lojistik eğrinin etkin eğimi (lojistik ≈ Φ(z/1.702))."""
    scale = 400.0 / np.log(10) * 1.702 / a
    return float(a / np.sqrt(1.0 + (resid_sd / scale) ** 2))


# ------------------------------------------------------------------ tasarım
def design_from_labeled(maia: Maia2Model, rec: dict, anchor: dict) -> tuple[BankItem | None, str]:
    """(senaryo, durum): durum ∈ {ok, not_positional, few_options, no_low, reversed}."""
    from .positional import N_CHOICES, is_positional, loss_score

    if not is_positional(rec):
        return None, "not_positional"
    moves, P = maia.forward(rec["fen"], MAIA_CENTERS, MAIA_CENTERS)
    col = {m: i for i, m in enumerate(moves)}
    scores = {m: loss_score(l) for m, l in rec["loss"].items() if m in col}
    best = rec["best"]
    others = [m for m in scores if m != best and scores[m] < 3]
    if len(others) < N_CHOICES - 1:
        return None, "few_options"
    lure = {m: float(np.log(P[0, col[m]] + 1e-9) - np.log(P[-1, col[m]] + 1e-9)) for m in others}
    ranked = sorted(others, key=lambda m: (-lure[m], m))
    pick = ranked[: N_CHOICES - 1]
    if min(scores[m] for m in pick) > 1:
        low = [m for m in ranked if scores[m] <= 1]
        if not low:
            return None, "no_low"
        pick = pick[:-1] + [low[0]]
    opts = {best: 3, **{m: scores[m] for m in pick}}
    choices = sorted(opts)

    # 4 şıklı seçim (Luce): güçlüler doğru şıkkı daha az seçiyorsa "doğru" cevap insan gözüyle tartışmalı → dışla
    Q = P[:, [col[c] for c in choices]]
    Q = Q / Q.sum(axis=1, keepdims=True)
    sc = np.array([opts[c] for c in choices])
    mc = np.stack([Q[:, sc >= k].sum(axis=1) for k in (1, 2, 3)])
    mc_a = slope(mc)
    if mc_a < 0:
        return None, "reversed"

    # Serbest yanıt: tüm yasal hamleler (aday listesinde olmayanlar 8. adaydan kötü → 0 puan sayılır)
    full = np.array([scores.get(m, 0) for m in moves])
    free = np.stack([P[:, full >= k].sum(axis=1) for k in (1, 2, 3)])
    b1, b2, b3 = (anchor_b(float(logit10(free[k]).mean()), anchor) for k in range(3))
    b = float(np.clip(b2, B_MIN, B_MAX))
    item = BankItem(
        id=f"pos:{rec['game'].rsplit('/', 1)[-1]}:{rec['ply']}", source="lichess-games+stockfish+maia2",
        fen=rec["fen"], solution=[best], kind="positional", themes=["positional"], choices=choices,
        move_scores=opts, puzzle_rating=b, b=b, a=marginal_a(anchor["resid_sd"]),
        offsets=[float(np.clip(min(b1 - b2, 0.0), -OFFSET_MAX, 0.0)), 0.0,
                 float(np.clip(max(b3 - b2, 0.0), 0.0, OFFSET_MAX))],
        meta={"player_rating": rec["rating"], "played": rec["played"], "played_score": rec["played_score"],
              "loss": {m: round(rec["loss"][m], 4) for m in opts}, "label": rec["label"],
              "design": "maia-lure-v1", "b_source": "maia2-puzzle-anchor-v1", "provisional": True,
              "maia": {"mc_a": round(mc_a, 3), "b_raw": [round(b1), round(b2), round(b3)],
                       "p_mc_best": [round(float(mc[2, 0]), 3), round(float(mc[2, -1]), 3)]}},
    )
    return item, "ok"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("anchor"); a.add_argument("puzzles"); a.add_argument("out")
    a.add_argument("--n", type=int, default=ANCHOR_N)
    d = sub.add_parser("design"); d.add_argument("labeled"); d.add_argument("anchor"); d.add_argument("out")
    args = ap.parse_args(argv)
    maia = Maia2Model()
    if args.cmd == "anchor":
        res = fit_anchor(maia, load_items(args.puzzles), args.n)
        Path(args.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0
    anchor = json.loads(Path(args.anchor).read_text(encoding="utf-8"))
    recs = [json.loads(l) for l in open(args.labeled, encoding="utf-8") if l.strip()]
    status: dict[str, int] = {}
    seen, out = set(), []
    with open(args.out, "w", encoding="utf-8") as fh:
        for i, rec in enumerate(recs):
            key = " ".join(rec["fen"].split()[:4])
            if key in seen:
                status["duplicate"] = status.get("duplicate", 0) + 1
                continue
            seen.add(key)
            item, st = design_from_labeled(maia, rec, anchor)
            status[st] = status.get(st, 0) + 1
            if item is not None:
                out.append(item)
                fh.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
            if (i + 1) % 2000 == 0:
                print(f"  {i + 1}/{len(recs)}", file=sys.stderr, flush=True)
    b = np.array([it.b for it in out])
    origin = np.array([it.meta["player_rating"] for it in out], dtype=float)
    print(json.dumps({
        "durum": status, "senaryo": len(out),
        "b": {"medyan": round(float(np.median(b))), "p10": round(float(np.percentile(b, 10))),
              "p90": round(float(np.percentile(b, 90))), "300'e_kırpılan": int((b <= B_MIN).sum())},
        "b_200lük_bant": {int(k): int(v) for k, v in zip(*np.unique((b // 200 * 200).astype(int), return_counts=True))},
        "b_ile_köken_rating_korelasyonu": round(float(np.corrcoef(b, origin)[0, 1]), 3),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
