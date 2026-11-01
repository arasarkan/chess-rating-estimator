"""Pilot veri setinden (sim/pilot_export) senaryo kalibrasyonu üretir: tür başına α, β, γ (measure/calibration.py).

Yalnız kalibrasyona uygun oturumlar kullanılır; oturumların %20'si ayrılıp uyumun gerçekten iyileştiği ölçülür
(plan: "%30 hiç dokunulmadan test için saklanır" — oran --holdout ile).

Kullanım (py/): python -m chessdex.sim.pilot_calibrate ../data/pilot/pilot.jsonl data/bank.jsonl data/item_calibration.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys

from chessdex.api.engine import to_irt
from chessdex.bank.loader import load_items
from chessdex.measure import calibration


def response_rows(pilot: list[dict], bank: dict) -> list[list[dict]]:
    """Oturum başına cevap satırları (bankadaki ham IRT parametreleriyle)."""
    out = []
    for p in pilot:
        if not p.get("calibration_eligible") or p["verified"].get("rating") is None:
            continue
        theta = float(p["verified"]["rating"])
        rows = []
        for r in p["responses"]:
            it = bank.get(r["item_id"])
            if it is None:
                continue
            irt = to_irt(it)
            rows.append({"kind": irt.kind, "theta": theta, "k": min(int(r["score"]), irt.n_cat - 1),
                         "a": irt.a, "b": irt.b, "c": irt.c, "offsets": list(irt.offsets)})
        if rows:
            out.append(rows)
    return out


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pilot")
    ap.add_argument("bank")
    ap.add_argument("out")
    ap.add_argument("--holdout", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=13)
    args = ap.parse_args(argv)
    pilot = [json.loads(line) for line in open(args.pilot, encoding="utf-8") if line.strip()]
    bank = {it.id: it for it in load_items(args.bank)}
    sessions = response_rows(pilot, bank)
    random.Random(args.seed).shuffle(sessions)
    n_hold = int(len(sessions) * args.holdout)
    hold = [r for s in sessions[:n_hold] for r in s]
    train = [r for s in sessions[n_hold:] for r in s]
    cal = calibration.fit(train, hold)
    calibration.save(cal, args.out)
    print(json.dumps({"sessions": len(sessions), "train_responses": len(train), "holdout_responses": len(hold),
                      "per_kind": cal["per_kind"], "fit": cal["fit"]}, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
