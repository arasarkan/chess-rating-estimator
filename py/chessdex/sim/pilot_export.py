"""Pilot verisi: kalıcı oturum deposundan (SQLite) doğrulanmış hesaplı, tamamlanmış oturumları kalibrasyon veri setine
aktarır ve plan ölçütlerini (MAE, %90 kapsama, bant sapması) yalnız kalibrasyona uygun olanlarla hesaplar.

Kişisel veri en aza indirilir: oturum kimliği ve kullanıcı adı tuzlu özetle (`CHESSDEX_EXPORT_SALT`) anonimleştirilir;
cevaplar yalnız senaryo kimliği, dönüşüm, puan ve süre olarak çıkar.

Kullanım (py/): python -m chessdex.sim.pilot_export data/sessions.sqlite3 ../data/pilot/pilot.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sqlite3
import sys
from pathlib import Path

import numpy as np


def _anon(x: str, salt: str) -> str:
    return hashlib.sha256((salt + x).encode()).hexdigest()[:16]


def rows_from_db(path: str, salt: str) -> list[dict]:
    db = sqlite3.connect(path)
    out = []
    for (blob,) in db.execute("SELECT data FROM sessions"):
        try:
            s = pickle.loads(blob)
        except Exception:
            continue
        ext = getattr(s, "external", None)
        if s.stage != "done" or not ext or s.final is None:
            continue
        sm = s.final.summary()
        out.append({
            "session": _anon(s.id, salt), "account": _anon(f"{ext['platform']}:{ext['username']}", salt),
            "mode": s.mode, "n_items": len(s.responses), "match_used": s.match_used, "flags": list(s.flags),
            "estimate": sm, "verified": {k: ext.get(k) for k in ("platform", "rating", "rd", "games", "provisional")},
            "calibration_eligible": bool(ext.get("calibration_eligible")) and "low_reliability" not in s.flags,
            "responses": [{k: r[k] for k in ("item_id", "transform", "score", "elapsed_ms", "kind")} for r in s.responses],
        })
    db.close()
    return out


def metrics(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["calibration_eligible"] and r["verified"]["rating"] is not None]
    if not ok:
        return {"n_eligible": 0}
    R = np.array([r["verified"]["rating"] for r in ok], float)
    med = np.array([r["estimate"]["median"] for r in ok], float)
    lo = np.array([r["estimate"]["lo90"] for r in ok], float)
    hi = np.array([r["estimate"]["hi90"] for r in ok], float)
    err = med - R
    bands = {}
    for b0 in range(400, 2800, 200):
        m = (R >= b0) & (R < b0 + 200)
        if m.any():
            bands[f"{b0}-{b0 + 199}"] = {"n": int(m.sum()), "bias": round(float(err[m].mean()), 1)}
    return {"n_eligible": len(ok), "n_total": len(rows), "mae": round(float(np.abs(err).mean()), 1),
            "coverage90": round(float(((R >= lo) & (R <= hi)).mean()), 3), "bias": round(float(err.mean()), 1),
            "band_bias": bands,
            "targets": {"mae": "<= 150", "coverage90": "0.87-0.93", "band_bias": "|.| <= 50"}}


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db")
    ap.add_argument("out")
    args = ap.parse_args(argv)
    salt = os.environ.get("CHESSDEX_EXPORT_SALT", "")
    if not salt:
        print("UYARI: CHESSDEX_EXPORT_SALT yok; anonimleştirme tuzsuz (yalnız yerel deneme için)", file=sys.stderr)
    rows = rows_from_db(args.db, salt)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps(metrics(rows), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
