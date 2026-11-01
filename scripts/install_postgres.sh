#!/usr/bin/env bash
# Geliştirme/test için taşınabilir PostgreSQL 17 (EDB resmî Windows ikili dosyaları) kurar ve yerel bir küme başlatır.
# Sistem kurulumu ya da Windows hizmeti yoktur; her şey tools/postgres altında (git'te değil).
# Kullanım (depo kökünden): bash scripts/install_postgres.sh        → kur + initdb
#                           bash scripts/install_postgres.sh start  → 127.0.0.1:5433'te başlat
#                           bash scripts/install_postgres.sh stop
# Bağlantı: CHESSDEX_PG_DSN="postgresql://chessdex@127.0.0.1:5433/chessdex"
set -euo pipefail
cd "$(dirname "$0")/.."
VER=17.11-1
PGROOT=tools/postgres
BIN=$PGROOT/pgsql/bin
DATA=$PGROOT/data
PORT=${CHESSDEX_PG_PORT:-5433}
PY=.venv/Scripts/python; [ -x "$PY" ] || PY=.venv/bin/python

case "${1:-install}" in
  start)
    "$BIN/pg_ctl" -D "$DATA" -l "$PGROOT/server.log" -o "-p $PORT -c listen_addresses=127.0.0.1" -w start
    "$BIN/psql" -h 127.0.0.1 -p "$PORT" -U chessdex -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='chessdex'" \
      | grep -q 1 || "$BIN/createdb" -h 127.0.0.1 -p "$PORT" -U chessdex chessdex
    exit 0 ;;
  stop)
    "$BIN/pg_ctl" -D "$DATA" -w stop
    exit 0 ;;
esac

ZIP=$PGROOT/dl/postgresql-$VER-windows-x64-binaries.zip
mkdir -p "$PGROOT/dl"
[ -f "$ZIP" ] || curl -sSL --retry 5 -o "$ZIP" "https://get.enterprisedb.com/postgresql/postgresql-$VER-windows-x64-binaries.zip"
if [ ! -x "$BIN/postgres.exe" ]; then
  # yalnız sunucu için gerekenler (pgAdmin / StackBuilder / doc hariç)
  "$PY" -I -c "
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
z.extractall(sys.argv[2], members=[n for n in z.namelist() if n.split('/')[1:2] and n.split('/')[1] in ('bin', 'lib', 'share')])
" "$ZIP" "$PGROOT"
fi
"$BIN/postgres" --version
# yerel küme: yalnız 127.0.0.1, parolasız (trust) — üretimde KULLANMAYIN
[ -d "$DATA" ] || "$BIN/initdb" -D "$DATA" -U chessdex -E UTF8 --locale=C -A trust >/dev/null
echo "kuruldu: $DATA  (başlatmak için: bash scripts/install_postgres.sh start)"
