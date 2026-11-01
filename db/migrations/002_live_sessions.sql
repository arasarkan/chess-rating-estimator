-- 002_live_sessions.sql — süren oturumların operasyonel deposu (api/store.py: PgSessionStore)
-- 001'deki normalize tablolar analiz/pilot içindir; canlı oturum durumu (sonsal, bekleyen senaryo, maç analizi) burada
-- tek satırlık sürümlü bir ikili kayıt olarak tutulur. Birden fazla API örneği aynı veritabanını paylaşabilir.

BEGIN;

CREATE TABLE live_sessions (
    id           text PRIMARY KEY,
    version      integer NOT NULL,
    last_active  double precision NOT NULL,     -- epoch saniye (Session.last_active)
    data         bytea NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX live_sessions_last_active_idx ON live_sessions (last_active);

INSERT INTO schema_migrations (version) VALUES ('002_live_sessions');

COMMIT;
