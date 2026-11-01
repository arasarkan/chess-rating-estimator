-- 001_init.sql — chessdex ilk şema (PostgreSQL 14+)
-- Plan "Veri modeli" bölümü. Her tahmin model/parametre sürümüyle saklanır; item_params sürümlüdür ve silinmez.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- gen_random_uuid()

-- Şema sürüm takibi
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------ kullanıcılar ve harici hesaplar

CREATE TABLE users (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email       text UNIQUE,                       -- isteğe bağlı: anonim kullanıcıda NULL
    locale      text NOT NULL DEFAULT 'tr',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE external_accounts (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id              uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    platform             text NOT NULL CHECK (platform IN ('lichess', 'chesscom', 'fide')),
    username             text NOT NULL,
    verification_method  text CHECK (verification_method IN ('oauth', 'profile_code', 'manual')),
    verified_at          timestamptz,              -- NULL = doğrulanmamış (kalibrasyonda kullanılmaz)
    consent_at           timestamptz,              -- açık rıza zamanı
    created_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (platform, username)
);
CREATE INDEX external_accounts_user_idx ON external_accounts (user_id);

-- Kalibrasyonun "gerçek değeri"
CREATE TABLE rating_snapshots (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    external_account_id  bigint NOT NULL REFERENCES external_accounts(id) ON DELETE CASCADE,
    time_control         text NOT NULL,            -- 'rapid', 'blitz', 'classical', ...
    rating               integer NOT NULL,
    rd                   real,
    n_games              integer,                  -- ilgili dönemdeki rated oyun sayısı
    fetched_at           timestamptz NOT NULL DEFAULT now(),
    raw                  jsonb,                    -- API yanıtının ilgili kısmı
    created_at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX rating_snapshots_account_idx ON rating_snapshots (external_account_id, time_control, fetched_at DESC);

-- ------------------------------------------------------------------ model sürümleri

CREATE TABLE model_versions (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    component     text NOT NULL,                   -- 'estimator', 'maia', 'stockfish', 'bias_model', 'scale_map', ...
    version       text NOT NULL,
    config        jsonb NOT NULL DEFAULT '{}'::jsonb,  -- λ, α, β, önsel, düğüm sayısı vb.
    released_at   timestamptz,                     -- NULL = yayına alınmadı
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (component, version)
);

-- ------------------------------------------------------------------ oturumlar

CREATE TABLE sessions (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid REFERENCES users(id) ON DELETE SET NULL,  -- anonim oturumda NULL
    mode         text NOT NULL CHECK (mode IN ('full', 'short')),
    status       text NOT NULL DEFAULT 'items'
                 CHECK (status IN ('items', 'game', 'done', 'abandoned', 'error')),
    survey       jsonb,                            -- anket cevapları (önsel girdisi)
    seed         bigint,                           -- bot rastgeleliği için tohum
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    client_info  jsonb,                            -- tarayıcı, ekran, dil (en az veri)
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sessions_user_idx ON sessions (user_id);
CREATE INDEX sessions_status_idx ON sessions (status, started_at);

-- ------------------------------------------------------------------ senaryo bankası

CREATE TABLE items (
    id            text PRIMARY KEY,                -- ör. 'lichess:00008', 'demo:0001'; Lichess kimliği yalnızca burada
    source        text NOT NULL,                   -- 'lichess', 'demo-generated', 'positional-pipeline'
    fen           text NOT NULL,                   -- oyuncunun çözeceği pozisyon (kurulum hamlesi uygulanmış)
    solution      text[] NOT NULL,                 -- UCI; çift indeksler oyuncu
    kind          text NOT NULL CHECK (kind IN ('tactics', 'endgame', 'defense', 'positional')),
    themes        text[] NOT NULL DEFAULT '{}',
    choices       text[],                          -- çoktan seçmeli seçenekler
    move_scores   jsonb,                           -- kademeli puanlar {uci: 0..3}
    puzzle_rating real,
    rating_dev    real,
    n_plays       integer,
    meta          jsonb NOT NULL DEFAULT '{}'::jsonb,
    active        boolean NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    CHECK (cardinality(solution) >= 1)
);
CREATE INDEX items_kind_active_idx ON items (kind) WHERE active;
CREATE INDEX items_themes_gin ON items USING gin (themes);

-- Sürümlü IRT parametreleri: güncelleme = yeni satır, eski sürümler silinmez.
CREATE TABLE item_params (
    item_id        text NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    version        integer NOT NULL CHECK (version >= 1),
    a              real NOT NULL DEFAULT 1.0,
    b              real NOT NULL,
    c              real NOT NULL CHECK (c >= 0 AND c < 1),
    thresholds     real[],                         -- graded model eşikleri (varsa)
    time_fast_ms   integer,                        -- hızlı/yavaş eşiği
    n_responses    integer NOT NULL DEFAULT 0,
    infit          real,
    outfit         real,
    fit_stats      jsonb,
    model_version_id bigint REFERENCES model_versions(id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (item_id, version)
);
CREATE INDEX item_params_latest_idx ON item_params (item_id, version DESC);

-- Eski sürümler silinemez; parametre alanları (a, b, c, eşikler) değiştirilemez.
-- Yalnızca uyum istatistikleri (n_responses, infit, outfit, fit_stats) yerinde güncellenebilir.
CREATE FUNCTION item_params_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'item_params satırları silinemez; yeni sürüm ekleyin';
    END IF;
    IF (OLD.item_id, OLD.version, OLD.a, OLD.b, OLD.c, OLD.thresholds, OLD.time_fast_ms, OLD.model_version_id)
       IS DISTINCT FROM
       (NEW.item_id, NEW.version, NEW.a, NEW.b, NEW.c, NEW.thresholds, NEW.time_fast_ms, NEW.model_version_id) THEN
        RAISE EXCEPTION 'item_params parametreleri değiştirilemez; yeni sürüm ekleyin';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER item_params_versioned BEFORE UPDATE OR DELETE ON item_params
    FOR EACH ROW EXECUTE FUNCTION item_params_immutable();

-- Her senaryonun en güncel parametreleri
CREATE VIEW item_params_current AS
SELECT DISTINCT ON (item_id) *
FROM item_params
ORDER BY item_id, version DESC;

-- ------------------------------------------------------------------ cevaplar

CREATE TABLE responses (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id       uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    item_id          text NOT NULL REFERENCES items(id),
    item_version     integer,                      -- kullanılan item_params sürümü
    seq              smallint NOT NULL,            -- oturumdaki sıra
    transform        text NOT NULL DEFAULT 'identity'
                     CHECK (transform IN ('identity', 'color_swap', 'mirror', 'both')),
    shown_fen        text NOT NULL,                -- dönüştürülmüş, gösterilen FEN
    given_moves      text[] NOT NULL DEFAULT '{}',
    elapsed_ms       integer NOT NULL CHECK (elapsed_ms >= 0),
    score            smallint NOT NULL,            -- 0 yanlış, 1 yavaş doğru, 2 hızlı doğru (kademelide 0–3)
    correct          boolean NOT NULL,
    focus_lost       boolean NOT NULL DEFAULT false,
    shown_at         timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (session_id, seq),
    FOREIGN KEY (item_id, item_version) REFERENCES item_params(item_id, version)
);
CREATE INDEX responses_item_idx ON responses (item_id);

-- ------------------------------------------------------------------ maç

CREATE TABLE games (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id        uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    bot_level         integer NOT NULL,
    user_color        text NOT NULL CHECK (user_color IN ('white', 'black')),
    initial_ms        integer NOT NULL DEFAULT 600000,
    increment_ms      integer NOT NULL DEFAULT 5000,
    seed              bigint,
    pgn               text,
    result            text CHECK (result IN ('1-0', '0-1', '1/2-1/2')),
    end_reason        text,                        -- mate, resign, timeout, stalemate, abandon, ...
    human_model_version_id bigint REFERENCES model_versions(id),
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX games_session_idx ON games (session_id);

CREATE TABLE moves (
    game_id          uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    ply              smallint NOT NULL CHECK (ply >= 0),
    by_user          boolean NOT NULL,
    fen_before       text NOT NULL,
    uci              text NOT NULL,
    clock_ms         integer,                      -- hamleden sonra kalan süre
    spent_ms         integer,
    maia_probs       bytea,                        -- 261 noktalık P(hamle|θ) vektörü, sıkıştırılmış float32
    maia_entropy     real,
    sf_cp            integer,
    sf_mate          integer,
    sf_best          text,
    win_prob_loss    real,
    exclusion_reason text CHECK (exclusion_reason IN ('book', 'forced', 'decided', 'time_trouble')),
    weight           real NOT NULL DEFAULT 1.0,
    analysis         jsonb,                        -- ek analiz alanları
    created_at       timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (game_id, ply)
);

-- ------------------------------------------------------------------ tahminler ve bütünlük

CREATE TABLE estimates (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id        uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    stage             text NOT NULL CHECK (stage IN ('prior', 'items', 'game', 'final')),
    posterior         bytea NOT NULL,              -- 261 noktalık log-sonsal, sıkıştırılmış float64
    median            real NOT NULL,
    lo90              real NOT NULL,               -- %5 yüzdelik
    hi90              real NOT NULL,               -- %95 yüzdelik
    sd                real,
    n_items           integer NOT NULL DEFAULT 0,
    subskills         jsonb,                       -- {tactics: {...}, endgame: ..., ...}
    scales            jsonb,                       -- lichess / chesscom / fide karşılıkları
    reliability_flags text[] NOT NULL DEFAULT '{}',
    model_version_id  bigint NOT NULL REFERENCES model_versions(id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    CHECK (lo90 <= median AND median <= hi90)
);
CREATE INDEX estimates_session_idx ON estimates (session_id, created_at DESC);
CREATE INDEX estimates_model_idx ON estimates (model_version_id);

CREATE TABLE integrity_flags (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id  uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    kind        text NOT NULL,                     -- engine_match, uniform_speed, focus_loss, low_effort, ...
    score       real,
    details     jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX integrity_flags_session_idx ON integrity_flags (session_id);

INSERT INTO schema_migrations (version) VALUES ('001_init');

COMMIT;
