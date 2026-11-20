-- Core tables shared by all teams. FROZEN: a change needs one reviewer from each team.
-- Money is TEXT holding a Decimal ("90.00"). Timestamps are UTC "YYYY-MM-DD HH:MM:SS".

CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  name    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
  sku         TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  brand       TEXT,
  category    TEXT NOT NULL,
  price       TEXT NOT NULL,
  stock       INTEGER NOT NULL CHECK (stock >= 0),
  veg         INTEGER NOT NULL,
  description TEXT
);

-- Child tables so filters match exactly: "nut" never matches "peanut".
-- Values are lower case and singular (peanut, tree_nut, milk, egg, wheat, sesame).
CREATE TABLE IF NOT EXISTS product_ingredients (
  sku        TEXT NOT NULL REFERENCES products(sku),
  ingredient TEXT NOT NULL,
  PRIMARY KEY (sku, ingredient)
);

CREATE TABLE IF NOT EXISTS product_allergens (
  sku      TEXT NOT NULL REFERENCES products(sku),
  allergen TEXT NOT NULL,
  PRIMARY KEY (sku, allergen)
);

-- Curated substitute pairs (otherwise computed from category and price).
CREATE TABLE IF NOT EXISTS substitutes (
  sku            TEXT NOT NULL REFERENCES products(sku),
  substitute_sku TEXT NOT NULL REFERENCES products(sku),
  PRIMARY KEY (sku, substitute_sku)
);

CREATE TABLE IF NOT EXISTS orders (
  order_id     TEXT PRIMARY KEY,
  user_id      TEXT NOT NULL REFERENCES users(user_id),
  status       TEXT NOT NULL CHECK (status IN ('placed', 'out_for_delivery', 'delivered', 'cancelled')),
  placed_at    TEXT NOT NULL,
  promised_eta TEXT NOT NULL,
  delivered_at TEXT,
  total        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
  order_id   TEXT NOT NULL REFERENCES orders(order_id),
  sku        TEXT NOT NULL REFERENCES products(sku),
  qty        INTEGER NOT NULL CHECK (qty > 0),
  unit_price TEXT NOT NULL,
  PRIMARY KEY (order_id, sku)
);

-- Written only by shared/security.py: every write tool call and every refused call (W1).
-- Never stores keys or tokens.
CREATE TABLE IF NOT EXISTS audit_log (
  id     INTEGER PRIMARY KEY,
  ts     TEXT NOT NULL,
  user   TEXT NOT NULL,
  role   TEXT,
  tool   TEXT NOT NULL,
  args   TEXT,
  ok     INTEGER NOT NULL,
  detail TEXT
);

CREATE INDEX IF NOT EXISTS ix_orders_user ON orders(user_id, placed_at DESC);
