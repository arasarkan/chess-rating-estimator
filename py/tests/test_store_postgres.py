"""PgSessionStore ve göç çalıştırıcı — gerçek PostgreSQL'e karşı (CHESSDEX_TEST_PG_DSN yoksa atlanır).

Yerel sunucu: `bash scripts/install_postgres.sh && bash scripts/install_postgres.sh start`, sonra
CHESSDEX_TEST_PG_DSN=postgresql://chessdex@127.0.0.1:5433/postgres (testler kendi geçici veritabanını kurar ve siler).
"""
import os
import time
import uuid

import pytest

DSN = os.environ.get("CHESSDEX_TEST_PG_DSN")
if not DSN:
    pytest.skip("CHESSDEX_TEST_PG_DSN tanımlı değil", allow_module_level=True)

psycopg = pytest.importorskip("psycopg")

from chessdex import db_migrate  # noqa: E402
from chessdex.api.store import PgSessionStore  # noqa: E402
from tests.test_api import NoEngine, tiny_bank  # noqa: E402


@pytest.fixture()
def fresh_dsn():
    name = f"chessdex_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f'CREATE DATABASE "{name}"')
    dsn = DSN.rsplit("/", 1)[0] + "/" + name
    yield dsn
    with psycopg.connect(DSN, autocommit=True) as c:
        c.execute(f'DROP DATABASE "{name}" WITH (FORCE)')


def test_migrations_apply_once_and_are_idempotent(fresh_dsn):
    first = db_migrate.migrate(fresh_dsn, log=lambda m: None)
    assert first == [f.stem for f in db_migrate.migration_files()]
    assert db_migrate.migrate(fresh_dsn, log=lambda m: None) == []
    with psycopg.connect(fresh_dsn) as c:
        tables = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")}
    assert {"sessions", "responses", "games", "moves", "estimates", "live_sessions"} <= tables


def test_store_requires_migration(fresh_dsn):
    with pytest.raises(RuntimeError, match="db_migrate"):
        PgSessionStore(fresh_dsn)


def test_engine_sessions_survive_restart_on_postgres(fresh_dsn):
    from chessdex.api.engine import Engine

    db_migrate.migrate(fresh_dsn, log=lambda m: None)
    eng = Engine(bank=tiny_bank(), pg_dsn=fresh_dsn)
    eng.analyzer = NoEngine()
    s = eng.create("full")
    it = eng.next_item(s)["item"]
    eng.respond(s, it["token"], ["a1a8"], 5000)
    pending = eng.next_item(s)["item"]["token"]
    eng.store.close()

    eng2 = Engine(bank=tiny_bank(), pg_dsn=fresh_dsn)          # "yeniden başlatma": yeni süreç gibi
    eng2.analyzer = NoEngine()
    s2 = eng2.get(s.id)
    assert len(s2.responses) == 1 and s2.pending.token == pending
    assert abs(s2.post.median() - s.post.median()) < 1e-9
    assert eng2.store.count() == 1


def test_ttl_cleanup_and_reconnect(fresh_dsn, caplog):
    from chessdex.api.engine import Engine

    db_migrate.migrate(fresh_dsn, log=lambda m: None)
    eng = Engine(bank=tiny_bank(), pg_dsn=fresh_dsn)
    eng.analyzer = NoEngine()
    s = eng.create("full")
    store = eng.store
    with psycopg.connect(fresh_dsn, autocommit=True) as c:      # sunucu tarafında bağlantıyı kopar
        c.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() "
                  "AND pid <> pg_backend_pid()")
    with caplog.at_level("WARNING", logger="chessdex.store"):
        store.save(s)                                           # bir kez yeniden bağlanıp yazmalı
    assert any("yeniden bağlanılıyor" in r.getMessage() for r in caplog.records)
    assert store.count() == 1
    assert store.load_all(ttl_s=60, now=time.time() + 3600) == []   # süresi dolmuş → silinir
    assert store.count() == 0
