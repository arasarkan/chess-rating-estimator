#!/usr/bin/env bash
# Lichess bulmaca veritabanından senaryo bankasını (py/data/bank.jsonl) yeniden üretir. Belirlenimci (sabit tohum).
# Kullanım (depo kökünden): bash scripts/build_bank.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/Scripts/python; [ -x "$PY" ] || PY=.venv/bin/python
mkdir -p data/raw
SRC=data/raw/lichess_db_puzzle.csv.zst
[ -f "$SRC" ] || curl -sSL --retry 5 -o "$SRC" https://database.lichess.org/lichess_db_puzzle.csv.zst
cd py
# 1) Sıkı filtre (plan: RD<80, NbPlays>1000, Popularity>70, Moves 2–6) ve 2) uçlar için gevşek filtre — paralel
../$PY -m chessdex.bank.filter ../$SRC ../data/raw/bank_strict.jsonl --per-band 2000 &
../$PY -m chessdex.bank.filter ../$SRC ../data/raw/bank_relaxed.jsonl --per-band 2000 --max-rd 90 --min-plays 300 --min-popularity 60 &
wait
# 3) Birleştir: gevşek havuz yalnızca eksik bantları doldurur
../$PY -m chessdex.bank.merge ../data/raw/bank_strict.jsonl ../data/raw/bank_relaxed.jsonl data/bank_puzzles.jsonl --per-band 2000
# 4) Pozisyonel senaryolar (Lichess rapid oyunları + Stockfish + Maia-2; ~30 dk). Atlamak için SKIP_POSITIONAL=1
GAMES_URL=https://database.lichess.org/standard/lichess_db_standard_rated_2026-09.pgn.zst
if [ "${SKIP_POSITIONAL:-0}" != 1 ]; then
  [ -f ../data/raw/pos_candidates.jsonl ] || ../$PY -m chessdex.bank.positional collect "$GAMES_URL" ../data/raw/pos_candidates.jsonl --per-band 700 --max-mb 800
  [ -f ../data/raw/pos_labeled.jsonl ] || ../$PY -m chessdex.bank.positional label ../data/raw/pos_candidates.jsonl ../data/raw/pos_labeled.jsonl --workers 16
  ../$PY -m chessdex.bank.positional calibrate ../data/raw/pos_labeled.jsonl ../data/raw/pos_model.json   # tanı
  if ../$PY -c "import maia2" 2>/dev/null; then
    # Maia-2 ile şık tasarımı + bulmacalara çapalanmış zorluk (docs/results/maia2.md)
    ../$PY -m chessdex.bank.maia_calib anchor data/bank_puzzles.jsonl ../data/raw/maia_anchor.json
    ../$PY -m chessdex.bank.maia_calib design ../data/raw/pos_labeled.jsonl ../data/raw/maia_anchor.json data/positional.jsonl
  else
    # yedek: köken rating'i (geçici, daha zayıf)
    ../$PY -m chessdex.bank.positional build ../data/raw/pos_labeled.jsonl ../data/raw/pos_model.json data/positional.jsonl
  fi
fi
cat data/bank_puzzles.jsonl $( [ -f data/positional.jsonl ] && echo data/positional.jsonl ) > ../data/raw/bank_unchecked.jsonl
# 5) ≤ 7 taşlı çözüm adımlarını Lichess tablebase'iyle doğrula; sonucu bozan / belirsiz senaryoları çıkar
#    (sorgular data/raw/tb_cache.json'da önbelleklenir; ilk çalıştırma ~10 dk, sonrası ağsız). Atlamak için SKIP_TABLEBASE=1
if [ "${SKIP_TABLEBASE:-0}" != 1 ]; then
  ../$PY -m chessdex.bank.tablebase ../data/raw/bank_unchecked.jsonl data/bank.jsonl --cache ../data/raw/tb_cache.json \
    --report ../docs/results/tablebase.json
else
  cp ../data/raw/bank_unchecked.jsonl data/bank.jsonl
fi
cd ..
# 6) Doğrula
$PY scripts/validate_bank.py py/data/bank.jsonl
