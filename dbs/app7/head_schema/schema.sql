-- app7.db — learner activity & content annotations
--
-- ┌────────────────┐    ┌─────────────────┐    ┌─────────────────┐
-- │ chapters       │    │ pages           │    │ images          │
-- ├────────────────┤    ├─────────────────┤    ├─────────────────┤
-- │ name    PK     │◄───│ page_id    PK   │◄───│ image_id   PK   │
-- └────────────────┘    │ chapter_name FK │    │ page_id    FK   │
--                       │ title           │    └────────┬────────┘
--                       └───────┬─────────┘             │
--                               │                       │
--          ┌────────────────────┼───────────────────────┤
--          │                    │                       │
--          ▼                    ▼                       ▼
-- ┌──────────────────┐ ┌──────────────────┐ ┌───────────────────────┐
-- │ session_events   │ │ page_interactions│ │ annotation_records    │
-- ├──────────────────┤ ├──────────────────┤ ├───────────────────────┤
-- │ id        PK AI  │ │ id        PK AI  │ │ id        PK AI      │
-- │ event_type    NN │ │ interact… NN     │ │ image_id  FK NN ─────┘
-- │ timestamp     NN │ │ timestamp NN     │ │ box_index       NN
-- │ duration_ms      │ │ page_id   FK ────┘ │ box_x/y/w/h    NN
-- │ page_id   FK ────┘ │ norm_x/y         │ │ label           NN
-- │ synced    [0|1]  │ │ hit_result       │ │ timestamp       NN
-- └──────────────────┘ │ synced   [0|1]   │ │ tap_x/y         NN
--                      └──────────────────┘ │ region_type [CK] NN
--                                           │ parent_bubble_idx
-- ┌──────────────────┐                      │ token_index
-- │ app_launch_recs  │                      │ synced      [0|1]
-- ├──────────────────┤                      └──────────┬────────┘
-- │ id        PK AI  │                                 │
-- │ package…  NN     │              ┌──────────────────┘
-- │ timestamp NN     │              │ image_id + bubble_index
-- │ page_id   FK ────┘(to pages)   ▼
-- │ synced    [0|1]  │    ┌───────────────────────┐
-- └──────────────────┘    │ region_translations   │
--                         ├───────────────────────┤
--                         │ id         PK (comp)  │
-- ┌──────────────────┐    │ image_id   FK NN ─────┘(to images)
-- │ chat_messages    │    │ bubble_index     NN
-- ├──────────────────┤    │ original_text    NN
-- │ id        PK AI  │    │ meaning_transl   NN
-- │ sender    NN     │    │ literal_transl   NN
-- │ text      NN     │    │ source_lang  'ja'
-- │ timestamp NN     │    │ target_lang  'en'
-- │ synced    [0|1]  │    │ UNIQUE(image_id,
-- └──────────────────┘    │        bubble_index)
--                         └───────────────────────┘
-- ┌──────────────────┐
-- │ settings_changes │    CK: region_type IN ('BUBBLE', 'TOKEN')
-- ├──────────────────┤    AI: AUTOINCREMENT
-- │ id        PK AI  │    NN: NOT NULL
-- │ setting   NN     │    FK: FOREIGN KEY
-- │ old_value NN     │    PK: PRIMARY KEY
-- │ new_value NN     │    [0|1]: CHECK(synced IN (0,1))
-- │ timestamp NN     │
-- │ synced    [0|1]  │    All syncable tables have partial index:
-- └──────────────────┘      WHERE synced = 0
--

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ── Content structure ───────────────────────────────────────
-- Populated via INSERT OR IGNORE during sync.
-- Gives relational backbone to the string IDs the Android app sends.

CREATE TABLE chapters (
    name TEXT PRIMARY KEY
);

CREATE TABLE pages (
    page_id      TEXT PRIMARY KEY,
    chapter_name TEXT NOT NULL REFERENCES chapters(name),
    title        TEXT
);
CREATE INDEX idx_pages_chapter ON pages(chapter_name);

CREATE TABLE images (
    image_id TEXT PRIMARY KEY,
    page_id  TEXT REFERENCES pages(page_id)
);
CREATE INDEX idx_images_page ON images(page_id);

-- ── Activity tracking ───────────────────────────────────────

CREATE TABLE session_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT    NOT NULL CHECK(event_type != ''),
    timestamp   INTEGER NOT NULL,
    duration_ms INTEGER,
    page_id     TEXT    REFERENCES pages(page_id),
    synced      INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0, 1))
);
CREATE INDEX idx_session_events_ts     ON session_events(timestamp);
CREATE INDEX idx_session_events_synced ON session_events(synced) WHERE synced = 0;
CREATE INDEX idx_session_events_page   ON session_events(page_id);

CREATE TABLE page_interactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    interaction_type TEXT    NOT NULL CHECK(interaction_type != ''),
    timestamp        INTEGER NOT NULL,
    page_id          TEXT    REFERENCES pages(page_id),
    normalized_x     REAL,
    normalized_y     REAL,
    hit_result       TEXT,
    synced           INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0, 1))
);
CREATE INDEX idx_page_interactions_ts     ON page_interactions(timestamp);
CREATE INDEX idx_page_interactions_synced ON page_interactions(synced) WHERE synced = 0;
CREATE INDEX idx_page_interactions_page   ON page_interactions(page_id);

CREATE TABLE app_launch_records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    package_name TEXT    NOT NULL,
    timestamp    INTEGER NOT NULL,
    page_id      TEXT    REFERENCES pages(page_id),
    synced       INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0, 1))
);
CREATE INDEX idx_app_launches_ts     ON app_launch_records(timestamp);
CREATE INDEX idx_app_launches_synced ON app_launch_records(synced) WHERE synced = 0;

-- ── Annotations & translations ──────────────────────────────

CREATE TABLE annotation_records (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
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
    region_type         TEXT    NOT NULL DEFAULT 'BUBBLE' CHECK(region_type IN ('BUBBLE', 'TOKEN')),
    parent_bubble_index INTEGER,
    token_index         INTEGER,
    synced              INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0, 1))
);
CREATE INDEX idx_annotations_image  ON annotation_records(image_id);
CREATE INDEX idx_annotations_synced ON annotation_records(synced) WHERE synced = 0;
CREATE INDEX idx_annotations_ts     ON annotation_records(timestamp);

CREATE TABLE region_translations (
    id                  TEXT PRIMARY KEY,   -- '{image_id}_{bubble_index}'
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

-- ── Independent ─────────────────────────────────────────────

CREATE TABLE chat_messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    sender    TEXT    NOT NULL,
    text      TEXT    NOT NULL,
    timestamp INTEGER NOT NULL,
    synced    INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0, 1))
);
CREATE INDEX idx_chat_ts     ON chat_messages(timestamp);
CREATE INDEX idx_chat_synced ON chat_messages(synced) WHERE synced = 0;

CREATE TABLE settings_changes (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    setting   TEXT    NOT NULL,
    old_value TEXT    NOT NULL,
    new_value TEXT    NOT NULL,
    timestamp INTEGER NOT NULL,
    synced    INTEGER NOT NULL DEFAULT 0 CHECK(synced IN (0, 1))
);
CREATE INDEX idx_settings_ts     ON settings_changes(timestamp);
CREATE INDEX idx_settings_synced ON settings_changes(synced) WHERE synced = 0;
