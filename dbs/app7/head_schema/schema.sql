-- app7.db — ingest target for the KMP "learnlauncher" app.
--
-- This schema is the downstream relational projection of the KMP
-- UnifiedPayload schema v3 (see the KMP producer at
-- shared/src/commonMain/kotlin/pl/czak/learnlauncher/data/model/UnifiedPayload.kt).
--
-- Design contract:
--   • Column names match the KMP @SerialName JSON field names 1:1.
--   • Every syncable row carries (device_id, user_id, local_id) for
--     multi-device provenance. UNIQUE(device_id, local_id) gives
--     idempotent re-ingest of the same export.
--   • Content catalog (chapters, pages, images) is inferred by the
--     ingest worker from denormalized fields already present in
--     UnifiedPayload (chapter_name, page_id, page_title, image_id,
--     current_chapter, current_page_id). The worker upserts the catalog
--     BEFORE inserting event rows so FK constraints hold.
--   • The producer-side `synced` flag is preserved per row so exported
--     snapshots retain their original state. The ingest side never
--     filters by it, so there is no partial index on synced.
--   • An ingest_batches audit row is written for every UnifiedPayload
--     consumed, recording the envelope (schema_version, mode, device_id,
--     user_id, app_version, export_timestamp, ingested_at, row_counts).
--
-- ┌────────────┐   ┌──────────────┐   ┌──────────┐
-- │ chapters   │◄──│ pages        │◄──│ images   │
-- ├────────────┤   ├──────────────┤   ├──────────┤
-- │ name  PK   │   │ page_id  PK  │   │ image_id │
-- └────────────┘   │ chapter_name │   │ page_id  │
--                  │ page_title   │   └────┬─────┘
--                  └──────┬───────┘        │
--                         │                │
--       ┌─────────────────┼─────────┬──────┴─────────────┐
--       ▼                 ▼         ▼                    ▼
-- session_events   page_interactions  app_launch_records  annotation_records
-- settings_changes  chat_messages                          region_translations
--
-- Every syncable table: (device_id, user_id, local_id) + UNIQUE(device_id, local_id).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── Content catalog ───────────────────────────────────────────
-- Upserted by the ingest worker from denormalized fields before
-- any event rows are inserted.

CREATE TABLE chapters (
    chapter_name TEXT PRIMARY KEY
);

CREATE TABLE pages (
    page_id      TEXT PRIMARY KEY,
    chapter_name TEXT REFERENCES chapters(chapter_name),
    page_title   TEXT
);
CREATE INDEX idx_pages_chapter ON pages(chapter_name);

CREATE TABLE images (
    image_id TEXT PRIMARY KEY,
    page_id  TEXT REFERENCES pages(page_id)
);
CREATE INDEX idx_images_page ON images(page_id);

-- ── Ingest audit ──────────────────────────────────────────────
-- One row per UnifiedPayload received.

CREATE TABLE ingest_batches (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version    INTEGER NOT NULL,
    mode              TEXT    NOT NULL CHECK(mode IN ('sync','export')),
    device_id         TEXT    NOT NULL,
    user_id           TEXT,
    app_version       TEXT    NOT NULL,
    export_timestamp  INTEGER NOT NULL,
    ingested_at       INTEGER NOT NULL,
    row_counts        TEXT  -- JSON, e.g. {"session_events": 10, ...}
);
CREATE INDEX idx_ingest_batches_device ON ingest_batches(device_id, export_timestamp);

-- ── Syncable tables ───────────────────────────────────────────

CREATE TABLE session_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     TEXT    NOT NULL,
    user_id       TEXT,
    local_id      INTEGER NOT NULL,
    event_type    TEXT    NOT NULL CHECK(event_type != ''),
    timestamp     INTEGER NOT NULL,
    duration_ms   INTEGER,
    chapter_name  TEXT    REFERENCES chapters(chapter_name),
    page_id       TEXT    REFERENCES pages(page_id),
    page_title    TEXT,
    synced        INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0,1)),
    UNIQUE(device_id, local_id)
);
CREATE INDEX idx_session_events_ts     ON session_events(timestamp);
CREATE INDEX idx_session_events_page   ON session_events(page_id);
CREATE INDEX idx_session_events_device ON session_events(device_id, timestamp);

CREATE TABLE annotation_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id           TEXT    NOT NULL,
    user_id             TEXT,
    local_id            INTEGER NOT NULL,
    image_id            TEXT    NOT NULL REFERENCES images(image_id),
    box_index           INTEGER NOT NULL,
    box_x               REAL    NOT NULL,
    box_y               REAL    NOT NULL,
    box_width           REAL    NOT NULL,
    box_height          REAL    NOT NULL,
    label               TEXT    NOT NULL,
    timestamp           INTEGER NOT NULL,
    tap_x               REAL    NOT NULL,
    tap_y               REAL    NOT NULL,
    region_type         TEXT    NOT NULL DEFAULT 'BUBBLE'
                        CHECK(region_type IN ('BUBBLE','TOKEN')),
    parent_bubble_index INTEGER,
    token_index         INTEGER,
    synced              INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0,1)),
    UNIQUE(device_id, local_id)
);
CREATE INDEX idx_annotations_image  ON annotation_records(image_id);
CREATE INDEX idx_annotations_ts     ON annotation_records(timestamp);
CREATE INDEX idx_annotations_device ON annotation_records(device_id, timestamp);

CREATE TABLE chat_messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT    NOT NULL,
    user_id   TEXT,
    local_id  INTEGER NOT NULL,
    sender    TEXT    NOT NULL,
    text      TEXT    NOT NULL,
    timestamp INTEGER NOT NULL,
    synced    INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0,1)),
    UNIQUE(device_id, local_id)
);
CREATE INDEX idx_chat_ts     ON chat_messages(timestamp);
CREATE INDEX idx_chat_device ON chat_messages(device_id, timestamp);

CREATE TABLE page_interactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id        TEXT    NOT NULL,
    user_id          TEXT,
    local_id         INTEGER NOT NULL,
    interaction_type TEXT    NOT NULL CHECK(interaction_type != ''),
    timestamp        INTEGER NOT NULL,
    chapter_name     TEXT    REFERENCES chapters(chapter_name),
    page_id          TEXT    REFERENCES pages(page_id),
    normalized_x     REAL,
    normalized_y     REAL,
    hit_result       TEXT,
    synced           INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0,1)),
    UNIQUE(device_id, local_id)
);
CREATE INDEX idx_page_interactions_ts     ON page_interactions(timestamp);
CREATE INDEX idx_page_interactions_page   ON page_interactions(page_id);
CREATE INDEX idx_page_interactions_device ON page_interactions(device_id, timestamp);

CREATE TABLE app_launch_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       TEXT    NOT NULL,
    user_id         TEXT,
    local_id        INTEGER NOT NULL,
    package_name    TEXT    NOT NULL,
    timestamp       INTEGER NOT NULL,
    current_chapter TEXT    REFERENCES chapters(chapter_name),
    current_page_id TEXT    REFERENCES pages(page_id),
    synced          INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0,1)),
    UNIQUE(device_id, local_id)
);
CREATE INDEX idx_app_launches_ts     ON app_launch_records(timestamp);
CREATE INDEX idx_app_launches_device ON app_launch_records(device_id, timestamp);

CREATE TABLE settings_changes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT    NOT NULL,
    user_id     TEXT,
    local_id    INTEGER NOT NULL,
    setting_key TEXT    NOT NULL,
    old_value   TEXT    NOT NULL,
    new_value   TEXT    NOT NULL,
    timestamp   INTEGER NOT NULL,
    synced      INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0,1)),
    UNIQUE(device_id, local_id)
);
CREATE INDEX idx_settings_ts     ON settings_changes(timestamp);
CREATE INDEX idx_settings_device ON settings_changes(device_id, timestamp);

-- region_translations: the KMP producer's own `id` ("{image_id}_{bubble_index}")
-- is the natural key. No local_id or synced column in UnifiedPayload for this table.
CREATE TABLE region_translations (
    id                  TEXT    PRIMARY KEY,
    device_id           TEXT    NOT NULL,
    user_id             TEXT,
    image_id            TEXT    NOT NULL REFERENCES images(image_id),
    bubble_index        INTEGER NOT NULL,
    original_text       TEXT    NOT NULL,
    meaning_translation TEXT    NOT NULL,
    literal_translation TEXT    NOT NULL,
    source_language     TEXT    NOT NULL DEFAULT 'ja',
    target_language     TEXT    NOT NULL DEFAULT 'en',
    UNIQUE(image_id, bubble_index)
);
CREATE INDEX idx_translations_image ON region_translations(image_id);
