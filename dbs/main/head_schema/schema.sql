-- main.db — users and learning sessions
--
-- ┌──────────────────────┐       ┌─────────────────────────────┐
-- │ users                │       │ learning_sessions            │
-- ├──────────────────────┤       ├─────────────────────────────┤
-- │ id          PK       │◄──┐   │ id            PK             │
-- │ name        TEXT NN  │   │   │ user_id       FK NN ────────┘
-- │ email       TEXT UQ  │   │   │ topic         TEXT
-- │ created_at  TEXT NN  │   │   │ started_at    TEXT NN
-- └──────────────────────┘   │   │ ended_at      TEXT
--                            │   │ status        TEXT NN  [CK]
--                            │   └─────────────────────────────┘
--                            │
--                            └── ON DELETE CASCADE
--
-- CK: status IN ('active', 'completed', 'abandoned')
--

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE users (
    id         INTEGER PRIMARY KEY,
    name       TEXT    NOT NULL,
    email      TEXT    UNIQUE,
    created_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE learning_sessions (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic      TEXT,
    started_at TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    ended_at   TEXT,
    status     TEXT    NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'abandoned'))
);
CREATE INDEX idx_sessions_user   ON learning_sessions(user_id);
CREATE INDEX idx_sessions_status ON learning_sessions(status) WHERE status = 'active';
