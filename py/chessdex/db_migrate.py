"""PostgreSQL göç çalıştırıcı: db/migrations/NNN_*.sql dosyalarından uygulanmamış olanları sırayla uygular.

Her dosya kendi BEGIN/COMMIT'ini taşır ve sonunda `schema_migrations`'a kendi sürümünü yazar; çalıştırıcı yalnız
`schema_migrations`'ta olmayan dosyaları çalıştırır, böylece tekrar çalıştırmak güvenlidir (idempotent).
Kullanım: CHESSDEX_PG_DSN=postgresql://... python -m chessdex.db_migrate  [--dsn ...]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    return sorted(p for p in directory.glob("[0-9][0-9][0-9]_*.sql"))


def applied(conn) -> set[str]:
    has = conn.execute("SELECT to_regclass('public.schema_migrations') IS NOT NULL").fetchone()[0]
    if not has:
        return set()
    return {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}


def migrate(dsn: str, directory: Path = MIGRATIONS_DIR, log=print) -> list[str]:
    import psycopg

    done = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        have = applied(conn)
        for f in migration_files(directory):
            if f.stem in have:
                continue
            log(f"uygulanıyor: {f.name}")
            conn.execute(f.read_text(encoding="utf-8"))
            if f.stem not in applied(conn):
                raise RuntimeError(f"{f.name} schema_migrations'a '{f.stem}' yazmadı")
            done.append(f.stem)
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PostgreSQL göçlerini uygula")
    ap.add_argument("--dsn", default=os.environ.get("CHESSDEX_PG_DSN"))
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if not args.dsn:
        print("CHESSDEX_PG_DSN ya da --dsn gerekli", file=sys.stderr)
        return 2
    done = migrate(args.dsn)
    print(f"uygulanan: {done or 'yok (güncel)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
