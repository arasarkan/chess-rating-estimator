"""Oyun sonu senaryolarının tablebase doğrulaması (plan: "≤ 7 taş olanlar tablebase ile doğrulanır").

Çözümdeki her oyuncu hamlesi, pozisyonda ≤ 7 taş varsa Lichess tablebase'ine (Syzygy, herkese açık, anahtarsız)
sorulur. Hamle teorik sonucu korumalı (kazanç → kazanç, beraberlik → beraberlik); korumuyorsa senaryo yanlıştır
ve bankadan çıkarılır. Aynı sonucu koruyan başka (mat etmeyen) hamle varsa:
  - beraberlik pozisyonunda senaryo belirsizdir (başka hamle de tam doğru) → çıkarılır;
  - kazanç pozisyonunda tutulur ve sayısı kaydedilir (bulmaca üreticisi en iyi hamle ile ikinci arasında büyük
    değerlendirme farkı arar; daha yavaş kazanan hamle "çözüm" değildir — Lichess kuralı).
Mat eden alternatifler puanlamada zaten doğru sayılır (scoring.check_line), sayılmaz.

Kullanım (py/ dizininden):
  python -m chessdex.bank.tablebase data/bank.jsonl data/bank_tb.jsonl --cache ../data/raw/tb_cache.json \\
      --report ../docs/results/tablebase.json
Sorgular önbelleğe yazılır; yeniden çalıştırma ağa çıkmaz (belirlenimci).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import chess

MAX_PIECES = 7
API = "https://tablebase.lichess.ovh/standard"
USER_AGENT = "chessdex-bank-validation/1.0"
# hamle yapanın bakışından sonuç sırası
RANK = {"loss": 0, "maybe-loss": 1, "blessed-loss": 2, "draw": 3, "cursed-win": 4, "maybe-win": 5, "win": 6}
INVERT = {"loss": "win", "maybe-loss": "maybe-win", "blessed-loss": "cursed-win", "draw": "draw",
          "cursed-win": "blessed-loss", "maybe-win": "maybe-loss", "win": "loss"}


def tb_key(board: chess.Board) -> str:
    """Tablebase için anlamlı kısım (hamle sayaçları hariç) — önbellek anahtarı."""
    return " ".join(board.fen().split()[:4])


def http_probe(fen: str, timeout: float = 15.0, retries: int = 4) -> dict:
    url = f"{API}?{urllib.parse.urlencode({'fen': fen})}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == retries - 1:
                raise
            time.sleep(60)                     # API'nin istediği: 429'da bir dakika bekle
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("ulaşılamaz")           # pragma: no cover


class Prober:
    """Önbellekli tablebase sorgusu; `fetch(fen) -> dict` testte değiştirilebilir."""

    def __init__(self, cache_path: str | Path | None = None, fetch=http_probe, delay_s: float = 0.25):
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: dict = {}
        if self.cache_path and self.cache_path.exists():
            self.cache = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.fetch, self.delay_s, self.n_requests = fetch, delay_s, 0

    def __call__(self, board: chess.Board) -> dict:
        key = tb_key(board)
        hit = self.cache.get(key)
        if hit is None:
            if self.n_requests and self.delay_s:
                time.sleep(self.delay_s)
            r = self.fetch(board.fen())
            hit = {"category": r.get("category"),
                   "moves": [{"uci": m["uci"], "category": m.get("category"), "checkmate": bool(m.get("checkmate"))}
                             for m in r.get("moves", [])]}
            self.cache[key] = hit
            self.n_requests += 1
        return hit

    def save(self) -> None:
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(self.cache, f, separators=(",", ":"))


def check_item(fen: str, solution: list[str], probe) -> dict:
    """→ {"checked", "verdict": ok|wrong|ambiguous|unchecked, "reason", "alternatives", "steps"}."""
    board = chess.Board(fen)
    steps, alternatives = 0, 0
    for i, uci in enumerate(solution):
        if i % 2 == 0 and len(board.piece_map()) <= MAX_PIECES and not board.castling_rights:
            r = probe(board)
            cat = r.get("category")
            if cat in RANK:
                outcome = {m["uci"]: INVERT.get(m["category"]) for m in r["moves"] if m["category"] in INVERT}
                mine = outcome.get(uci)
                steps += 1
                if mine is None or RANK[mine] < RANK[cat]:
                    return {"checked": True, "verdict": "wrong", "alternatives": alternatives, "steps": steps,
                            "reason": f"hamle {i // 2 + 1}: {uci} sonucu {cat} → {mine} düşürüyor"}
                alts = [m["uci"] for m in r["moves"] if m["uci"] != uci and not m["checkmate"]
                        and m["uci"] in outcome and RANK[outcome[m["uci"]]] >= RANK[cat]]
                if alts and cat in ("draw", "blessed-loss", "cursed-win"):
                    why = f"hamle {i // 2 + 1}: {cat} korunuyor, başka hamleler de koruyor ({', '.join(alts[:3])})"
                    return {"checked": True, "verdict": "ambiguous", "alternatives": len(alts), "steps": steps,
                            "reason": why}
                alternatives += len(alts)
        board.push_uci(uci)
    if steps == 0:
        return {"checked": False, "verdict": "unchecked", "alternatives": 0, "steps": 0, "reason": None}
    return {"checked": True, "verdict": "ok", "alternatives": alternatives, "steps": steps, "reason": None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Oyun sonu senaryolarını tablebase ile doğrula")
    ap.add_argument("inp")
    ap.add_argument("out")
    ap.add_argument("--cache", default=None)
    ap.add_argument("--report", default=None)
    ap.add_argument("--delay", type=float, default=0.25, help="istekler arası bekleme (sn)")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    prober = Prober(args.cache, delay_s=args.delay)
    verdicts, examples, kept = Counter(), {"wrong": [], "ambiguous": []}, 0
    with open(args.inp, encoding="utf-8") as fin, open(args.out, "w", encoding="utf-8", newline="\n") as fout:
        for n, line in enumerate(fin, 1):
            d = json.loads(line)
            res = check_item(d["fen"], d["solution"], prober)
            verdicts[res["verdict"]] += 1
            if res["checked"]:
                d.setdefault("meta", {}).update(tablebase_check=True, tablebase_verdict=res["verdict"],
                                                 tablebase_alternatives=res["alternatives"])
            if res["verdict"] in examples:
                if len(examples[res["verdict"]]) < 20:
                    examples[res["verdict"]].append({"id": d["id"], "kind": d.get("kind"), "reason": res["reason"]})
                continue
            fout.write(json.dumps(d, ensure_ascii=False) + "\n")
            kept += 1
            if prober.n_requests and prober.n_requests % 100 == 0:
                prober.save()
            if n % 5000 == 0:
                print(f"{n} senaryo · {dict(verdicts)} · {prober.n_requests} istek", flush=True)
    prober.save()
    report = {"input": args.inp, "kept": kept, "verdicts": dict(verdicts), "requests": prober.n_requests,
              "cache_entries": len(prober.cache), "examples": examples}
    if args.report:
        with open(args.report, "w", encoding="utf-8", newline="\n") as f:
            json.dump(report, f, indent=1, ensure_ascii=False)
    print(json.dumps({k: v for k, v in report.items() if k != "examples"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
