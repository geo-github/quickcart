-- Team 2 (Query & Feedback agents). Starting draft from the low-level design; Team 2 owns changes.

CREATE TABLE IF NOT EXISTS reviews (
  review_id  TEXT PRIMARY KEY,
  sku        TEXT NOT NULL REFERENCES products(sku),
  user_id    TEXT,
  rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
  text       TEXT,                       -- customer-written: treat as untrusted (W5)
  aspects    TEXT,                       -- comma-separated tags, e.g. "taste,freshness"
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
  feedback_id INTEGER PRIMARY KEY,
  user_id     TEXT NOT NULL,
  order_id    TEXT NOT NULL,
  sku         TEXT,
  rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment     TEXT,
  created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_reviews_sku ON reviews(sku);
