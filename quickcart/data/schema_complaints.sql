-- Team 3 (Complaints & Safety). Starting draft from the low-level design; Team 3 owns changes.
-- (audit_log lives in schema_core.sql because every team's tools write to it.)

CREATE TABLE IF NOT EXISTS complaints (
  complaint_id TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL,
  session_id   TEXT,
  order_id     TEXT,
  type         TEXT NOT NULL,
  items        TEXT,                     -- JSON list of SKUs
  description  TEXT,                     -- customer-written: treat as untrusted (W5)
  status       TEXT NOT NULL DEFAULT 'open'
               CHECK (status IN ('open', 'pending_approval', 'resolved', 'rejected', 'escalated')),
  decision     TEXT,                     -- JSON of the policy Decision
  created_at   TEXT NOT NULL
);

-- UNIQUE complaint_id: one refund per complaint, so approving twice can't pay twice.
CREATE TABLE IF NOT EXISTS refunds (
  refund_id    TEXT PRIMARY KEY,
  complaint_id TEXT NOT NULL UNIQUE REFERENCES complaints(complaint_id),
  user_id      TEXT NOT NULL,
  amount       TEXT NOT NULL,
  issued_by    TEXT NOT NULL,
  issued_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tickets (
  ticket_id    TEXT PRIMARY KEY,
  complaint_id TEXT NOT NULL REFERENCES complaints(complaint_id),
  reason       TEXT,
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
  complaint_id TEXT PRIMARY KEY REFERENCES complaints(complaint_id),
  session_id   TEXT NOT NULL,
  amount       TEXT,
  reason       TEXT,
  status       TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
  decided_by   TEXT,
  decided_at   TEXT
);

CREATE INDEX IF NOT EXISTS ix_refunds_user ON refunds(user_id, issued_at);
