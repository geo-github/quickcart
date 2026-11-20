-- Team 1 (Supervisor & Orchestration). Starting draft from the low-level design; Team 1 owns changes.

CREATE TABLE IF NOT EXISTS sessions (
  session_id      TEXT PRIMARY KEY,
  user_id         TEXT NOT NULL,
  summary         TEXT,                  -- compaction summary (Lab 2D)
  pending_handoff TEXT,                  -- "complaint" after a low rating (R4)
  handoff_note    TEXT,
  tokens_used     INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL,
  ended_at        TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  session_id TEXT NOT NULL REFERENCES sessions(session_id),
  seq        INTEGER NOT NULL,
  role       TEXT NOT NULL,
  content    TEXT NOT NULL,              -- JSON, lab (Claude) message format
  created_at TEXT NOT NULL,
  PRIMARY KEY (session_id, seq)
);

-- Updates for a customer that arrive outside their turn (e.g. an operator approved a refund).
CREATE TABLE IF NOT EXISTS notices (
  id         INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  text       TEXT NOT NULL,
  shown      INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

-- Long-term memory (W3). Only allergy / language / preference; never personal or payment data.
CREATE TABLE IF NOT EXISTS memories (
  id         INTEGER PRIMARY KEY,
  user_id    TEXT NOT NULL,
  kind       TEXT NOT NULL CHECK (kind IN ('allergy', 'language', 'preference')),
  content    TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE (user_id, kind, content)
);

CREATE INDEX IF NOT EXISTS ix_memories_user ON memories(user_id, id DESC);
