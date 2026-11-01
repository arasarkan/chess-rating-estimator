"""Oturum kalıcılığı: API yeniden başlarsa yarım kalan testler ve maçlar kaybolmasın.

SQLite (standart kütüphane, ek servis gerektirmez). Her durum değişikliğinden sonra oturumun tamamı yazılır; açılışta
süresi dolmamış oturumlar geri yüklenir. Veri sunucunun kendi diskinde ve yalnız sunucunun yazdığı nesnelerdir
(kullanıcı girdisi değil), bu yüzden pickle güvenli — Postgres kullanılıyorsa veritabanı yalnız API'ye açık olmalı;
şema sürümü değişirse eski kayıtlar atlanır.
PostgreSQL için aynı arayüzde PgSessionStore (CHESSDEX_PG_DSN; şema: db/migrations/002_live_sessions.sql).
"""
from __future__ import annotations

import logging
import pickle
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger("chessdex.store")
SCHEMA_VERSION = 1


class SessionStore:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute("""CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, version INTEGER NOT NULL, last_active REAL NOT NULL, data BLOB NOT NULL)""")
        self._lock = threading.Lock()

    def save(self, session) -> None:
        blob = pickle.dumps(session, protocol=pickle.HIGHEST_PROTOCOL)
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO sessions (id, version, last_active, data) VALUES (?, ?, ?, ?)",
                             (session.id, SCHEMA_VERSION, session.last_active, blob))

    def load_all(self, ttl_s: float, now: float | None = None) -> list:
        now = time.time() if now is None else now
        out, bad = [], []
        with self._lock:
            rows = self._db.execute("SELECT id, version, last_active, data FROM sessions").fetchall()
        for sid, version, last_active, blob in rows:
            if version != SCHEMA_VERSION or now - last_active > ttl_s:
                bad.append(sid)
                continue
            try:
                out.append(pickle.loads(blob))
            except Exception:                                   # bozuk/eski kayıt: atla ve sil
                log.exception("oturum yüklenemedi: %s", sid)
                bad.append(sid)
        self.delete(bad)
        return out

    def delete(self, ids) -> None:
        ids = list(ids)
        if not ids:
            return
        with self._lock:
            self._db.executemany("DELETE FROM sessions WHERE id = ?", [(i,) for i in ids])

    def count(self) -> int:
        with self._lock:
            return int(self._db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._db.close()


class PgSessionStore:
    """PostgreSQL deposu (db/migrations/002_live_sessions.sql). SessionStore ile aynı arayüz; birden fazla API örneği
    aynı veritabanını paylaşabilir. Tek bağlantı + kilit; bağlantı koparsa bir kez yeniden bağlanıp yeniden dener.
    Şemayı kendisi kurmaz: önce `python -m chessdex.db_migrate`."""

    def __init__(self, dsn: str):
        import psycopg

        self._psycopg = psycopg
        self._dsn = dsn
        self._lock = threading.Lock()
        self._conn = self._connect()
        if self._run("SELECT to_regclass('public.live_sessions') IS NOT NULL", fetch="one")[0] is not True:
            raise RuntimeError("live_sessions tablosu yok: önce `python -m chessdex.db_migrate` çalıştırın")

    def _connect(self):
        return self._psycopg.connect(self._dsn, autocommit=True, connect_timeout=10)

    def _run(self, sql: str, params=None, fetch: str | None = None, many: bool = False):
        with self._lock:
            for attempt in (0, 1):
                try:
                    if self._conn.closed:
                        self._conn = self._connect()
                    with self._conn.cursor() as cur:
                        if many:
                            cur.executemany(sql, params)
                        else:
                            cur.execute(sql, params)
                        if fetch == "one":
                            return cur.fetchone()
                        if fetch == "all":
                            return cur.fetchall()
                        return None
                except self._psycopg.OperationalError:
                    if attempt:
                        raise
                    log.warning("postgres bağlantısı koptu; yeniden bağlanılıyor")
                    try:
                        self._conn.close()
                    except Exception:                                   # pragma: no cover
                        pass
                    self._conn = self._connect()

    def save(self, session) -> None:
        blob = pickle.dumps(session, protocol=pickle.HIGHEST_PROTOCOL)
        self._run("""INSERT INTO live_sessions (id, version, last_active, data) VALUES (%s, %s, %s, %s)
                     ON CONFLICT (id) DO UPDATE SET version = EXCLUDED.version, last_active = EXCLUDED.last_active,
                     data = EXCLUDED.data, updated_at = now()""",
                  (session.id, SCHEMA_VERSION, session.last_active, blob))

    def load_all(self, ttl_s: float, now: float | None = None) -> list:
        now = time.time() if now is None else now
        out, bad = [], []
        for sid, version, last_active, blob in self._run(
                "SELECT id, version, last_active, data FROM live_sessions", fetch="all"):
            if version != SCHEMA_VERSION or now - last_active > ttl_s:
                bad.append(sid)
                continue
            try:
                out.append(pickle.loads(bytes(blob)))
            except Exception:                                   # bozuk/eski kayıt: atla ve sil
                log.exception("oturum yüklenemedi: %s", sid)
                bad.append(sid)
        self.delete(bad)
        return out

    def delete(self, ids) -> None:
        ids = list(ids)
        if ids:
            self._run("DELETE FROM live_sessions WHERE id = ANY(%s)", (ids,))

    def count(self) -> int:
        return int(self._run("SELECT COUNT(*) FROM live_sessions", fetch="one")[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def open_store(db_path: str | None = None, pg_dsn: str | None = None):
    """CHESSDEX_PG_DSN verilmişse PostgreSQL, yoksa SQLite (db_path), ikisi de yoksa kalıcılık kapalı."""
    if pg_dsn:
        return PgSessionStore(pg_dsn)
    return SessionStore(db_path) if db_path else None
