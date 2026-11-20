"""Build the SQLite database from data/schema_*.sql and data/fixtures/*.json.

    python -m data.seed              # rebuilds var/app.db from scratch
    python -m data.seed --db x.db    # somewhere else

Order: schema_core.sql first, then the other schema files alphabetically; core.json first, then
the other fixture files alphabetically. Each team adds its own schema and fixture files; nobody
needs to edit this script.

Fixture timestamps like "@now-3d+30m" are resolved relative to the moment you seed
(d = days, h = hours, m = minutes), so time-based rules keep working on any day.
ChromaDB indexing is not done here: Team 2 runs its own indexer.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

from shared import db, settings

DATA_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = DATA_DIR / "fixtures"

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REL_TIME = re.compile(r"^@now((?:[+-]\d+[dhm])*)$")
_TERM = re.compile(r"([+-])(\d+)([dhm])")


def _ordered(paths, first: str) -> list[Path]:
    paths = sorted(paths, key=lambda p: p.name)
    return [p for p in paths if p.name == first] + [p for p in paths if p.name != first]


def resolve_time(value, now: dt.datetime):
    """'@now-3d+30m' -> 'YYYY-MM-DD HH:MM:SS' (UTC). Other values are returned unchanged."""
    if not isinstance(value, str) or not value.startswith("@now"):
        return value
    m = _REL_TIME.match(value)
    if not m:
        raise ValueError(f"Bad relative time {value!r}; use e.g. '@now-3d+30m'")
    t = now
    for sign, amount, unit in _TERM.findall(m.group(1)):
        delta = dt.timedelta(**{{"d": "days", "h": "hours", "m": "minutes"}[unit]: int(amount)})
        t = t + delta if sign == "+" else t - delta
    return t.strftime("%Y-%m-%d %H:%M:%S")


def load_fixture(con, path: Path, now: dt.datetime) -> dict[str, int]:
    counts: dict[str, int] = {}
    data = json.loads(path.read_text(encoding="utf-8"))
    for block in data.get("tables", []):
        table = block["table"]
        if not _IDENT.match(table):
            raise ValueError(f"Bad table name {table!r} in {path.name}")
        for row in block.get("rows", []):
            cols = list(row)
            if not all(_IDENT.match(c) for c in cols):
                raise ValueError(f"Bad column name in {path.name}: {cols}")
            values = [resolve_time(row[c], now) for c in cols]
            con.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", values)
            counts[table] = counts.get(table, 0) + 1
    return counts


def build(db_path: str | Path | None = None, *, fresh: bool = True) -> Path:
    """Create the schema and load all fixtures. Returns the database path."""
    path = Path(db_path or settings.DB_PATH)
    if fresh:
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    con = db.connect(path)
    try:
        for schema in _ordered(DATA_DIR.glob("schema_*.sql"), first="schema_core.sql"):
            con.executescript(schema.read_text(encoding="utf-8"))
        totals: dict[str, int] = {}
        for fixture in _ordered(FIXTURES_DIR.glob("*.json"), first="core.json"):
            for table, n in load_fixture(con, fixture, now).items():
                totals[table] = totals.get(table, 0) + n
        con.commit()
    finally:
        con.close()
    build.last_counts = totals   # type: ignore[attr-defined]
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the SQLite database from schemas and fixtures.")
    parser.add_argument("--db", help="database path (default: DB_PATH from .env, i.e. var/app.db)")
    args = parser.parse_args()
    path = build(args.db)
    print(f"Built {path}")
    for table, n in sorted(build.last_counts.items()):   # type: ignore[attr-defined]
        print(f"  {table:<20} {n:>4} rows")


if __name__ == "__main__":
    main()
