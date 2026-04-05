-- ============================================================
-- Language Learning Comic Reader — Hyper-Granular Event Schema
-- ============================================================
--
--  CONTENT CATALOG                         SESSION / INTERACTION HIERARCHY
--  (static, synced)                        (each level nests inside its parent)
--
--  ┌──────────────┐   ┌───────────────┐    ┌──────────────────┐
--  │ comics       │   │ annotation_   │    │ learners         │
--  ├──────────────┤   │ options       │    ├──────────────────┤
--  │ id       PK  │◄┐ ├───────────────┤    │ id           PK  │◄─────────────────┐
--  │ slug     UQ  │ │ │ id        PK  │◄┐  │ device_id    NN  │                  │
--  │ title    NN  │ │ │ slug      UQ  │ │  │ native_lang  NN  │                  │
--  │ lang     NN  │ │ │ label     NN  │ │  │ target_lang  NN  │                  │
--  │ difficulty   │ │ │ icon         │ │  └────────┬─────────┘                  │
--  │ total_pages  │ │ │ sort_order   │ │           │                            │
--  └──────────────┘ │ └───────────────┘ │           ▼                            │
--         │         │                   │  ┌──────────────────┐                  │
--         ▼         │                   │  │ app_sessions     │                  │
--  ┌──────────────┐ │                   │  ├──────────────────┤                  │
--  │ pages        │ │                   │  │ id           PK  │◄──┐             │
--  ├──────────────┤ │                   │  │ learner_id   FK ─┘   │             │
--  │ id       PK  │◄┐                   │  │ started_at   NN  │   │             │
--  │ comic_id FK─┘│ │                   │  │ ended_at         │   │             │
--  │ page_number  │ │                   │  │ end_reason       │   │             │
--  │ image_uri NN │ │                   │  └──────┬───────────┘   │             │
--  └──────────────┘ │                   │         │               │             │
--         │         │                   │         ├───────────────┼─────────┐   │
--         ▼         │                   │         │               │         │   │
--  ┌──────────────┐ │                   │         ▼               │         ▼   │
--  │ bubbles      │ │                   │  ┌──────────────┐      │  ┌────────────────┐
--  ├──────────────┤ │                   │  │ app_          │      │  │ comic_sessions │
--  │ id       PK  │◄┐                   │  │ interactions  │      │  ├────────────────┤
--  │ page_id  FK─┘│ │                   │  ├──────────────┤      │  │ id         PK  │◄─┐
--  │ bubble_idx   │ │                   │  │ id       PK  │      │  │ app_sess_id FK─┘  │
--  │ bbox_*   NN  │ │                   │  │ app_sess FK─┘│      │  │ comic_id   FK────┘│
--  │ full_text NN │ │                   │  │ action   NN  │      │  │ started_at NN  │  │
--  │ translation  │ │                   │  │ target       │      │  │ ended_at       │  │
--  │ audio_uri    │ │                   │  │ value        │      │  │ end_reason     │  │
--  └──────────────┘ │                   │  │ ts       NN  │      │  └────────────────┘  │
--         │         │                   │  └──────────────┘      │         │             │
--         ▼         │                   │                        │         ▼             │
--  ┌──────────────┐ │                   │                 ┌──────────────────┐           │
--  │ words        │ │                   │                 │ page_sessions    │           │
--  ├──────────────┤ │                   │                 ├──────────────────┤           │
--  │ id       PK  │◄┐                   │                 │ id           PK  │◄──┐      │
--  │ bubble_id FK─┘│ │                   │                 │ comic_sess_id FK─┘   │      │
--  │ word_index   │ │                   │                 │ page_id      FK──────┘│      │
--  │ surface  NN  │ │                   │                 │ started_at   NN  │    │      │
--  │ lemma        │ │                   │                 │ ended_at         │    │      │
--  │ pos          │ │                   │                 │ scroll_depth     │    │      │
--  │ translation  │ │                   │                 └──────┬───────────┘    │      │
--  │ bbox_*   NN  │ │                   │                        │               │      │
--  │ audio_uri    │ │                   │                        ├───────────┐    │      │
--  └──────────────┘ │                   │                        │           │    │      │
--                   │                   │                        ▼           ▼    │      │
--                   │                   │           ┌────────────────┐ ┌──────────────┐ │
--                   │                   │           │ page_          │ │ bubble_      │ │
--                   │                   │           │ interactions   │ │ sessions     │ │
--                   │                   │           ├────────────────┤ ├──────────────┤ │
--                   │                   │           │ id         PK  │ │ id       PK  │◄┐
--                   │                   │           │ page_sess FK─┘ │ │ page_sess FK─┘│
--                   │                   │           │ action     NN  │ │ bubble_id FK──┘│
--                   │                   │           │ from_page  FK  │ │ trigger    NN  ││
--                   │                   │           │ to_page    FK  │ │ showed_trnsl   ││
--                   │                   │           │ ts         NN  │ │ played_audio   ││
--                   │                   │           └────────────────┘ │ started_at NN  ││
--                   │                   │                              │ ended_at       ││
--                   │                   │                              └──────┬────────┘│
--                   │                   │                                     │         │
--                   │                   │                         ┌───────────┼─────┐   │
--                   │                   │                         │           │     │   │
--                   │                   │                         ▼           ▼     │   │
--                   │                   │            ┌──────────────┐ ┌───────────────┐│
--                   │                   │            │ bubble_      │ │ word_         ││
--                   │                   │            │ annotations  │ │ interactions  ││
--                   │                   │            ├──────────────┤ ├───────────────┤│
--                   │                   │            │ id       PK  │ │ id        PK  ││
--                   │                   └───────────│ annot_id FK──┘ │ bub_sess FK──┘│
--                   └──────────────────────────────│ bub_sess FK─┘  │ word_id   FK──┘
--                                                   │ ts       NN  │ │ interaction NN│
--                                                   └──────────────┘ │ showed_trnsl  │
--                                                                    │ played_audio  │
--                                                                    │ added_to_vocab│
--                                                                    │ ts        NN  │
--                                                                    └───────────────┘
--
--                         ┌─────────────────────────┐
--                         │ events (polymorphic)     │
--                         ├─────────────────────────┤
--                         │ id             PK       │
--                         │ learner_id     FK ──────────► learners.id
--                         │ ts             NN       │
--                         │ entity_type    NN       │──┐ polymorphic FK
--                         │ entity_id               │──┘ to any table above
--                         │ event_name     NN       │
--                         │ event_category NN       │
--                         │ payload     (JSON)      │
--                         └─────────────────────────┘
--
--  PK: PRIMARY KEY    NN: NOT NULL    FK: FOREIGN KEY
--  UQ: UNIQUE         AI: AUTOINCREMENT

-- ------------------------------------------------------------
-- 1. Learner
-- ------------------------------------------------------------
CREATE TABLE learners (
    id              INTEGER PRIMARY KEY,
    device_id       TEXT NOT NULL,            -- anonymous device fingerprint
    display_name    TEXT,
    native_lang     TEXT NOT NULL,            -- ISO 639-1 (e.g. 'de')
    target_lang     TEXT NOT NULL,            -- language they're learning
    created_at      INTEGER NOT NULL,         -- unix ms
    updated_at      INTEGER NOT NULL
);

-- ------------------------------------------------------------
-- 2. Content catalog (static, synced from server)
-- ------------------------------------------------------------
CREATE TABLE comics (
    id              INTEGER PRIMARY KEY,
    slug            TEXT NOT NULL UNIQUE,
    title           TEXT NOT NULL,
    lang            TEXT NOT NULL,            -- comic's language
    difficulty      INTEGER,                  -- 1-5 CEFR-ish band
    total_pages     INTEGER NOT NULL,
    created_at      INTEGER NOT NULL
);

CREATE TABLE pages (
    id              INTEGER PRIMARY KEY,
    comic_id        INTEGER NOT NULL REFERENCES comics(id),
    page_number     INTEGER NOT NULL,
    image_uri       TEXT NOT NULL,
    UNIQUE(comic_id, page_number)
);

CREATE TABLE bubbles (
    id              INTEGER PRIMARY KEY,
    page_id         INTEGER NOT NULL REFERENCES pages(id),
    bubble_index    INTEGER NOT NULL,         -- order on page
    bbox_x          REAL NOT NULL,            -- normalised 0-1
    bbox_y          REAL NOT NULL,
    bbox_w          REAL NOT NULL,
    bbox_h          REAL NOT NULL,
    full_text       TEXT NOT NULL,            -- raw transcript of bubble
    translation     TEXT,                     -- in learner's native lang
    audio_uri       TEXT,
    UNIQUE(page_id, bubble_index)
);

CREATE TABLE words (
    id              INTEGER PRIMARY KEY,
    bubble_id       INTEGER NOT NULL REFERENCES bubbles(id),
    word_index      INTEGER NOT NULL,         -- position in bubble text
    surface_form    TEXT NOT NULL,            -- as printed
    lemma           TEXT,                     -- dictionary form
    pos             TEXT,                     -- part of speech tag
    translation     TEXT,
    bbox_x          REAL NOT NULL,
    bbox_y          REAL NOT NULL,
    bbox_w          REAL NOT NULL,
    bbox_h          REAL NOT NULL,
    audio_uri       TEXT,
    UNIQUE(bubble_id, word_index)
);

-- ------------------------------------------------------------
-- 3. Annotation catalog (fixed set of labels learners can apply)
-- ------------------------------------------------------------

CREATE TABLE annotation_options (
    id              INTEGER PRIMARY KEY,
    slug            TEXT NOT NULL UNIQUE,      -- 'hard', 'funny', 'unknown_grammar',
                                               -- 'cultural_ref', 'review_later', etc.
    label           TEXT NOT NULL,             -- display text
    icon            TEXT,                      -- emoji or icon name
    sort_order      INTEGER NOT NULL DEFAULT 0
);

-- ------------------------------------------------------------
-- 4. Session hierarchy (each nests inside its parent)
-- ------------------------------------------------------------

-- Every time the app comes to foreground / goes to background
CREATE TABLE app_sessions (
    id              INTEGER PRIMARY KEY,
    learner_id      INTEGER NOT NULL REFERENCES learners(id),
    started_at      INTEGER NOT NULL,         -- unix ms
    ended_at        INTEGER,                  -- null = still active
    end_reason      TEXT                      -- 'background', 'killed', 'logout'
);

-- Point-in-time app-level UI actions (not reading-related)
-- e.g. open settings, open library, change profile, toggle theme
CREATE TABLE app_interactions (
    id              INTEGER PRIMARY KEY,
    app_session_id  INTEGER NOT NULL REFERENCES app_sessions(id),
    action          TEXT NOT NULL,            -- 'open_settings', 'open_library',
                                              -- 'change_profile', 'toggle_theme',
                                              -- 'open_vocab_list', 'open_stats'
    target          TEXT,                     -- what was acted on (e.g. setting key)
    value           TEXT,                     -- new value if a toggle/change
    ts              INTEGER NOT NULL
);

-- Learner opens a specific comic
CREATE TABLE comic_sessions (
    id              INTEGER PRIMARY KEY,
    app_session_id  INTEGER NOT NULL REFERENCES app_sessions(id),
    comic_id        INTEGER NOT NULL REFERENCES comics(id),
    started_at      INTEGER NOT NULL,
    ended_at        INTEGER,
    end_reason      TEXT                      -- 'back', 'switch_comic', 'app_bg'
);

-- Learner lands on / navigates to a page
CREATE TABLE page_sessions (
    id              INTEGER PRIMARY KEY,
    comic_session_id INTEGER NOT NULL REFERENCES comic_sessions(id),
    page_id         INTEGER NOT NULL REFERENCES pages(id),
    started_at      INTEGER NOT NULL,
    ended_at        INTEGER,
    scroll_depth    REAL                      -- 0-1 how far they scrolled
);

-- Point-in-time navigation actions within a page session
-- e.g. swipe to next page, tap prev, jump via thumbnail
CREATE TABLE page_interactions (
    id              INTEGER PRIMARY KEY,
    page_session_id INTEGER NOT NULL REFERENCES page_sessions(id),
    action          TEXT NOT NULL,            -- 'next', 'prev', 'jump', 'pinch_zoom',
                                              -- 'double_tap_zoom', 'scroll'
    from_page_id    INTEGER REFERENCES pages(id),  -- null unless 'jump'
    to_page_id      INTEGER REFERENCES pages(id),  -- the destination page
    ts              INTEGER NOT NULL
);

-- Learner zooms into / focuses on a bubble (this is a session, not a tap)
-- Starts when bubble is tapped/zoomed, ends when learner leaves zoom or moves on
CREATE TABLE bubble_sessions (
    id              INTEGER PRIMARY KEY,
    page_session_id INTEGER NOT NULL REFERENCES page_sessions(id),
    bubble_id       INTEGER NOT NULL REFERENCES bubbles(id),
    trigger         TEXT NOT NULL,            -- 'tap', 'long_press', 'auto_focus'
    showed_translation INTEGER NOT NULL DEFAULT 0,
    played_audio    INTEGER NOT NULL DEFAULT 0,
    started_at      INTEGER NOT NULL,
    ended_at        INTEGER
);

-- Learner double-taps to highlight a bubble and picks a fixed annotation
CREATE TABLE bubble_annotations (
    id              INTEGER PRIMARY KEY,
    bubble_session_id INTEGER NOT NULL REFERENCES bubble_sessions(id),
    annotation_id   INTEGER NOT NULL REFERENCES annotation_options(id),
    ts              INTEGER NOT NULL
);

-- Learner taps / long-presses a word inside a zoomed bubble
CREATE TABLE word_interactions (
    id              INTEGER PRIMARY KEY,
    bubble_session_id INTEGER NOT NULL REFERENCES bubble_sessions(id),
    word_id         INTEGER NOT NULL REFERENCES words(id),
    interaction     TEXT NOT NULL,            -- 'tap', 'long_press', 'double_tap'
    showed_translation INTEGER NOT NULL DEFAULT 0,
    played_audio    INTEGER NOT NULL DEFAULT 0,
    added_to_vocab  INTEGER NOT NULL DEFAULT 0,
    ts              INTEGER NOT NULL
);

-- ------------------------------------------------------------
-- 5. General events table (polymorphic, covers everything)
-- ------------------------------------------------------------
-- Every row in the tables above also emits an event here.
-- Plus system-level events (onboarding, push received, etc.)

CREATE TABLE events (
    id              INTEGER PRIMARY KEY,
    learner_id      INTEGER NOT NULL REFERENCES learners(id),
    ts              INTEGER NOT NULL,         -- unix ms

    -- polymorphic link to the entity that caused this event
    entity_type     TEXT NOT NULL,            -- 'app_session', 'app_interaction',
                                              -- 'comic_session', 'page_session',
                                              -- 'page_interaction', 'bubble_session',
                                              -- 'bubble_annotation', 'word_interaction',
                                              -- 'learner', 'system'
    entity_id       INTEGER,                  -- FK to that table's id (null for system)

    -- what happened
    event_name      TEXT NOT NULL,            -- e.g. 'app.foreground', 'app.open_settings',
                                              -- 'page.next', 'bubble.zoom_in',
                                              -- 'bubble.annotate', 'word.translation_shown'
    event_category  TEXT NOT NULL,            -- 'session', 'navigation', 'reading',
                                              -- 'annotation', 'vocab', 'ui', 'system'

    -- flexible payload
    payload         TEXT                      -- JSON blob for event-specific data
);

-- ------------------------------------------------------------
-- 6. Indexes
-- ------------------------------------------------------------
CREATE INDEX idx_events_learner_ts        ON events(learner_id, ts);
CREATE INDEX idx_events_entity            ON events(entity_type, entity_id);
CREATE INDEX idx_events_name              ON events(event_name);
CREATE INDEX idx_events_category          ON events(event_category);
CREATE INDEX idx_app_sessions_learner     ON app_sessions(learner_id, started_at);
CREATE INDEX idx_app_int_session          ON app_interactions(app_session_id);
CREATE INDEX idx_comic_sessions_app       ON comic_sessions(app_session_id);
CREATE INDEX idx_page_sessions_comic      ON page_sessions(comic_session_id);
CREATE INDEX idx_page_int_session         ON page_interactions(page_session_id);
CREATE INDEX idx_bubble_sess_page         ON bubble_sessions(page_session_id);
CREATE INDEX idx_bubble_ann_session       ON bubble_annotations(bubble_session_id);
CREATE INDEX idx_word_int_bubble_sess     ON word_interactions(bubble_session_id);
CREATE INDEX idx_word_int_word            ON word_interactions(word_id);
CREATE INDEX idx_words_lemma              ON words(lemma);
