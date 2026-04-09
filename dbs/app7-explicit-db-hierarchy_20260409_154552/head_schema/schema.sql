-- app7-explicit-db-hierarchy schema — v4
--
-- Forked from dbs/app7-tcp-sync-direct-queue-client_20260409_031219/ to
-- fix the chapter-name-collision-across-comics bug. Key change: every
-- event table now carries a `comic_id` column, and the catalog (comics,
-- chapters, pages) is composite-keyed on (comic_id, ...) so two comics
-- sharing a chapter name ("Chapter 1") produce two distinct rows.
--
-- Schema version: 4 (producer's UnifiedPayload.schemaVersion must match).
--
-- Rollout notes:
--   • Pre-migration legacy rows arriving from older producers carry
--     comic_id='_no_comic_' as a sentinel. Analytics queries should treat
--     that as "unknown comic, exclude or flag as legacy".
--   • Worker's catalog upsert now iterates (comic_id, chapter_name) tuples.
--   • FK constraints on event tables' chapter_name/page_id are REMOVED —
--     they no longer make semantic sense on their own after the catalog
--     went composite. Join semantic integrity is preserved in queries by
--     always using (comic_id, chapter_name) or (comic_id, page_id).

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── Content catalog ───────────────────────────────────────────

CREATE TABLE comics (
    comic_id     TEXT PRIMARY KEY,
    display_name TEXT,
    added_at     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE chapters (
    comic_id     TEXT NOT NULL REFERENCES comics(comic_id),
    chapter_name TEXT NOT NULL,
    PRIMARY KEY (comic_id, chapter_name)
);
CREATE INDEX idx_chapters_comic ON chapters(comic_id);

CREATE TABLE pages (
    comic_id     TEXT NOT NULL,
    page_id      TEXT NOT NULL,
    chapter_name TEXT,
    page_title   TEXT,
    PRIMARY KEY (comic_id, page_id),
    FOREIGN KEY (comic_id, chapter_name) REFERENCES chapters(comic_id, chapter_name)
);
CREATE INDEX idx_pages_comic_chapter ON pages(comic_id, chapter_name);

-- images: no comic_id column; image_id is globally unique (producer emits
-- "{asset_id}/img_NNN" style values). Reference pages via composite key.
CREATE TABLE images (
    image_id TEXT PRIMARY KEY,
    comic_id TEXT,
    page_id  TEXT,
    FOREIGN KEY (comic_id, page_id) REFERENCES pages(comic_id, page_id)
);
CREATE INDEX idx_images_comic_page ON images(comic_id, page_id);

-- ── Ingest audit ──────────────────────────────────────────────

CREATE TABLE ingest_batches (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version    INTEGER NOT NULL,
    mode              TEXT    NOT NULL CHECK(mode IN ('sync','export')),
    device_id         TEXT    NOT NULL,
    user_id           TEXT,
    app_version       TEXT    NOT NULL,
    export_timestamp  INTEGER NOT NULL,
    ingested_at       INTEGER NOT NULL,
    row_counts        TEXT  -- JSON
);
CREATE INDEX idx_ingest_batches_device ON ingest_batches(device_id, export_timestamp);

-- ── Syncable tables ───────────────────────────────────────────
-- All six event tables now carry comic_id. FK to chapters/pages is NOT
-- declared: the join key is always the composite (comic_id, chapter_name)
-- or (comic_id, page_id), not chapter_name or page_id alone.

CREATE TABLE session_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id     TEXT    NOT NULL,
    user_id       TEXT,
    local_id      INTEGER NOT NULL,
    event_type    TEXT    NOT NULL CHECK(event_type != ''),
    timestamp     INTEGER NOT NULL,
    duration_ms   INTEGER,
    comic_id      TEXT    NOT NULL DEFAULT '_no_comic_',
    chapter_name  TEXT,
    page_id       TEXT,
    page_title    TEXT,
    synced        INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0,1)),
    UNIQUE(device_id, local_id)
);
CREATE INDEX idx_session_events_ts     ON session_events(timestamp);
CREATE INDEX idx_session_events_comic  ON session_events(comic_id, chapter_name);
CREATE INDEX idx_session_events_device ON session_events(device_id, timestamp);

CREATE TABLE annotation_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
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
    region_type         TEXT    NOT NULL DEFAULT 'BUBBLE'
                        CHECK(region_type IN ('BUBBLE','TOKEN')),
    parent_bubble_index INTEGER,
    token_index         INTEGER,
    comic_id            TEXT    NOT NULL DEFAULT '_no_comic_',
    synced              INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0,1)),
    UNIQUE(device_id, local_id)
);
CREATE INDEX idx_annotations_image  ON annotation_records(image_id);
CREATE INDEX idx_annotations_comic  ON annotation_records(comic_id);
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
    comic_id         TEXT    NOT NULL DEFAULT '_no_comic_',
    chapter_name     TEXT,
    page_id          TEXT,
    normalized_x     REAL,
    normalized_y     REAL,
    hit_result       TEXT,
    synced           INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0,1)),
    UNIQUE(device_id, local_id)
);
CREATE INDEX idx_page_interactions_ts     ON page_interactions(timestamp);
CREATE INDEX idx_page_interactions_comic  ON page_interactions(comic_id, chapter_name);
CREATE INDEX idx_page_interactions_device ON page_interactions(device_id, timestamp);

CREATE TABLE app_launch_records (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       TEXT    NOT NULL,
    user_id         TEXT,
    local_id        INTEGER NOT NULL,
    package_name    TEXT    NOT NULL,
    timestamp       INTEGER NOT NULL,
    comic_id        TEXT    NOT NULL DEFAULT '_no_comic_',
    current_chapter TEXT,
    current_page_id TEXT,
    synced          INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0,1)),
    UNIQUE(device_id, local_id)
);
CREATE INDEX idx_app_launches_ts     ON app_launch_records(timestamp);
CREATE INDEX idx_app_launches_comic  ON app_launch_records(comic_id);
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

-- region_translations: already carries image_id which is globally unique.
-- No comic_id needed — the imageId transitively identifies the comic.
CREATE TABLE region_translations (
    id                  TEXT    PRIMARY KEY,
    device_id           TEXT    NOT NULL,
    user_id             TEXT,
    image_id            TEXT    NOT NULL,
    bubble_index        INTEGER NOT NULL,
    original_text       TEXT    NOT NULL,
    meaning_translation TEXT    NOT NULL,
    literal_translation TEXT    NOT NULL,
    source_language     TEXT    NOT NULL DEFAULT 'ja',
    target_language     TEXT    NOT NULL DEFAULT 'en',
    UNIQUE(image_id, bubble_index)
);
CREATE INDEX idx_translations_image ON region_translations(image_id);
