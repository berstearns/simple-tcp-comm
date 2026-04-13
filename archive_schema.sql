-- Archive DB schema — consolidates data from all worker DBs
--
-- Mirrors the 15 data tables from the app7-explicit-db-hierarchy worker
-- schema (v4/v5), plus a collection_log audit table. Every row carries
-- _source_worker to disambiguate data from different worker instances.
--
-- FK constraints are dropped (archive is read-only analytics; data arrives
-- pre-validated from worker DBs). CHECK constraints are preserved.
--
-- Idempotency: INSERT OR IGNORE on the UNIQUE constraints prevents
-- duplicate collection even if watermarks are lost.

PRAGMA journal_mode = WAL;

-- ── Collection audit ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS collection_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT    NOT NULL,
    source_worker   TEXT    NOT NULL,
    source_db_path  TEXT,
    table_name      TEXT    NOT NULL,
    rows_collected  INTEGER NOT NULL DEFAULT 0,
    rows_skipped    INTEGER NOT NULL DEFAULT 0,
    max_rowid       INTEGER,
    collected_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    duration_ms     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_clog_run    ON collection_log(run_id);
CREATE INDEX IF NOT EXISTS idx_clog_worker ON collection_log(source_worker, table_name);

-- ── Catalog tables ───────────────────────────────────────────

CREATE TABLE IF NOT EXISTS comics (
    _archive_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker TEXT NOT NULL,
    comic_id       TEXT NOT NULL,
    display_name   TEXT,
    added_at       INTEGER NOT NULL DEFAULT 0,
    UNIQUE(_source_worker, comic_id)
);

CREATE TABLE IF NOT EXISTS chapters (
    _archive_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker TEXT NOT NULL,
    comic_id       TEXT NOT NULL,
    chapter_name   TEXT NOT NULL,
    UNIQUE(_source_worker, comic_id, chapter_name)
);

CREATE TABLE IF NOT EXISTS pages (
    _archive_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker TEXT NOT NULL,
    comic_id       TEXT NOT NULL,
    page_id        TEXT NOT NULL,
    chapter_name   TEXT,
    page_title     TEXT,
    UNIQUE(_source_worker, comic_id, page_id)
);

CREATE TABLE IF NOT EXISTS images (
    _archive_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker TEXT NOT NULL,
    image_id       TEXT NOT NULL,
    comic_id       TEXT,
    page_id        TEXT,
    UNIQUE(_source_worker, image_id)
);

-- ── Ingest audit ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ingest_batches (
    _archive_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker   TEXT    NOT NULL,
    id               INTEGER,
    schema_version   INTEGER NOT NULL,
    mode             TEXT    NOT NULL CHECK(mode IN ('sync','export')),
    device_id        TEXT    NOT NULL,
    user_id          TEXT,
    app_version      TEXT    NOT NULL,
    export_timestamp INTEGER NOT NULL,
    ingested_at      INTEGER NOT NULL,
    row_counts       TEXT,
    UNIQUE(_source_worker, id)
);

-- ── Event tables (7) ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS session_events (
    _archive_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker TEXT    NOT NULL,
    id             INTEGER,
    device_id      TEXT    NOT NULL,
    user_id        TEXT,
    local_id       INTEGER NOT NULL,
    event_type     TEXT    NOT NULL,
    timestamp      INTEGER NOT NULL,
    duration_ms    INTEGER,
    comic_id       TEXT    NOT NULL DEFAULT '_no_comic_',
    chapter_name   TEXT,
    page_id        TEXT,
    page_title     TEXT,
    synced         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(_source_worker, device_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_a_se_ts ON session_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_a_se_w  ON session_events(_source_worker);

CREATE TABLE IF NOT EXISTS annotation_records (
    _archive_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker      TEXT    NOT NULL,
    id                  INTEGER,
    device_id           TEXT    NOT NULL,
    user_id             TEXT,
    local_id            INTEGER NOT NULL,
    image_id            TEXT    NOT NULL,
    box_index           INTEGER NOT NULL,
    box_x               REAL    NOT NULL,
    box_y               REAL    NOT NULL,
    box_width           REAL    NOT NULL,
    box_height          REAL    NOT NULL,
    label               TEXT    NOT NULL,
    timestamp           INTEGER NOT NULL,
    tap_x               REAL    NOT NULL,
    tap_y               REAL    NOT NULL,
    region_type         TEXT    NOT NULL DEFAULT 'BUBBLE',
    parent_bubble_index INTEGER,
    token_index         INTEGER,
    comic_id            TEXT    NOT NULL DEFAULT '_no_comic_',
    synced              INTEGER NOT NULL DEFAULT 0,
    UNIQUE(_source_worker, device_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_a_ar_ts ON annotation_records(timestamp);

CREATE TABLE IF NOT EXISTS chat_messages (
    _archive_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker TEXT    NOT NULL,
    id             INTEGER,
    device_id      TEXT    NOT NULL,
    user_id        TEXT,
    local_id       INTEGER NOT NULL,
    sender         TEXT    NOT NULL,
    text           TEXT    NOT NULL,
    timestamp      INTEGER NOT NULL,
    synced         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(_source_worker, device_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_a_cm_ts ON chat_messages(timestamp);

CREATE TABLE IF NOT EXISTS page_interactions (
    _archive_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker   TEXT    NOT NULL,
    id               INTEGER,
    device_id        TEXT    NOT NULL,
    user_id          TEXT,
    local_id         INTEGER NOT NULL,
    interaction_type TEXT    NOT NULL,
    timestamp        INTEGER NOT NULL,
    comic_id         TEXT    NOT NULL DEFAULT '_no_comic_',
    chapter_name     TEXT,
    page_id          TEXT,
    normalized_x     REAL,
    normalized_y     REAL,
    hit_result       TEXT,
    synced           INTEGER NOT NULL DEFAULT 0,
    UNIQUE(_source_worker, device_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_a_pi_ts ON page_interactions(timestamp);

CREATE TABLE IF NOT EXISTS app_launch_records (
    _archive_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker  TEXT    NOT NULL,
    id              INTEGER,
    device_id       TEXT    NOT NULL,
    user_id         TEXT,
    local_id        INTEGER NOT NULL,
    package_name    TEXT    NOT NULL,
    timestamp       INTEGER NOT NULL,
    comic_id        TEXT    NOT NULL DEFAULT '_no_comic_',
    current_chapter TEXT,
    current_page_id TEXT,
    synced          INTEGER NOT NULL DEFAULT 0,
    UNIQUE(_source_worker, device_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_a_al_ts ON app_launch_records(timestamp);

CREATE TABLE IF NOT EXISTS settings_changes (
    _archive_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker TEXT    NOT NULL,
    id             INTEGER,
    device_id      TEXT    NOT NULL,
    user_id        TEXT,
    local_id       INTEGER NOT NULL,
    setting_key    TEXT    NOT NULL,
    old_value      TEXT    NOT NULL,
    new_value      TEXT    NOT NULL,
    timestamp      INTEGER NOT NULL,
    synced         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(_source_worker, device_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_a_sc_ts ON settings_changes(timestamp);

CREATE TABLE IF NOT EXISTS region_translations (
    _archive_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker      TEXT    NOT NULL,
    id                  TEXT,
    device_id           TEXT    NOT NULL,
    user_id             TEXT,
    image_id            TEXT    NOT NULL,
    bubble_index        INTEGER NOT NULL,
    original_text       TEXT    NOT NULL,
    meaning_translation TEXT    NOT NULL,
    literal_translation TEXT    NOT NULL,
    source_language     TEXT    NOT NULL DEFAULT 'ja',
    target_language     TEXT    NOT NULL DEFAULT 'en',
    UNIQUE(_source_worker, image_id, bubble_index)
);

-- ── Session hierarchy tables (4) ─────────────────────────────

CREATE TABLE IF NOT EXISTS app_sessions (
    _archive_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker TEXT    NOT NULL,
    id             INTEGER,
    device_id      TEXT    NOT NULL,
    user_id        TEXT,
    local_id       INTEGER NOT NULL,
    start_ts       INTEGER NOT NULL,
    end_ts         INTEGER,
    duration_ms    INTEGER,
    app_version    TEXT    NOT NULL DEFAULT '',
    close_reason   TEXT,
    synced         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(_source_worker, device_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_a_as_ts ON app_sessions(start_ts);

CREATE TABLE IF NOT EXISTS comic_sessions (
    _archive_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker       TEXT    NOT NULL,
    id                   INTEGER,
    device_id            TEXT    NOT NULL,
    user_id              TEXT,
    local_id             INTEGER NOT NULL,
    app_session_local_id INTEGER NOT NULL,
    comic_id             TEXT    NOT NULL,
    start_ts             INTEGER NOT NULL,
    end_ts               INTEGER,
    duration_ms          INTEGER,
    pages_read           INTEGER,
    close_reason         TEXT,
    synced               INTEGER NOT NULL DEFAULT 0,
    UNIQUE(_source_worker, device_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_a_cs_ts ON comic_sessions(start_ts);

CREATE TABLE IF NOT EXISTS chapter_sessions (
    _archive_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker         TEXT    NOT NULL,
    id                     INTEGER,
    device_id              TEXT    NOT NULL,
    user_id                TEXT,
    local_id               INTEGER NOT NULL,
    comic_session_local_id INTEGER NOT NULL,
    comic_id               TEXT    NOT NULL,
    chapter_name           TEXT    NOT NULL,
    start_ts               INTEGER NOT NULL,
    end_ts                 INTEGER,
    duration_ms            INTEGER,
    pages_visited          INTEGER,
    close_reason           TEXT,
    synced                 INTEGER NOT NULL DEFAULT 0,
    UNIQUE(_source_worker, device_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_a_chs_ts ON chapter_sessions(start_ts);

CREATE TABLE IF NOT EXISTS page_sessions (
    _archive_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    _source_worker           TEXT    NOT NULL,
    id                       INTEGER,
    device_id                TEXT    NOT NULL,
    user_id                  TEXT,
    local_id                 INTEGER NOT NULL,
    chapter_session_local_id INTEGER NOT NULL,
    comic_id                 TEXT    NOT NULL,
    page_id                  TEXT    NOT NULL,
    enter_ts                 INTEGER NOT NULL,
    leave_ts                 INTEGER,
    dwell_ms                 INTEGER,
    interactions_n           INTEGER NOT NULL DEFAULT 0,
    close_reason             TEXT,
    synced                   INTEGER NOT NULL DEFAULT 0,
    UNIQUE(_source_worker, device_id, local_id)
);
CREATE INDEX IF NOT EXISTS idx_a_ps_ts ON page_sessions(enter_ts);
