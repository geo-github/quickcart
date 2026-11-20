"""SQLite helpers. One short-lived connection per call keeps things simple and thread-safe.

Always use ? placeholders. Never format values into SQL strings.
Timestamps are UTC in SQLite's own format ("YYYY-MM-DD HH:MM:SS"), so they compare correctly
with SQLite functions such as datetime('now', '-30 days').
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from shared import settings


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path or settings.DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


@contextmanager
def transaction(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Several statements that must succeed or fail together:
        with db.transaction() as con:
            con.execute(...); con.execute(...)
    """
    con = connect(path)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def query(sql: str, params: tuple | list | dict = (), path: str | Path | None = None) -> list[dict]:
    con = connect(path)
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    finally:
        con.close()


def query_one(sql: str, params: tuple | list | dict = (), path: str | Path | None = None) -> dict | None:
    rows = query(sql, params, path)
    return rows[0] if rows else None


def execute(sql: str, params: tuple | list | dict = (), path: str | Path | None = None) -> int:
    """Run one write statement and commit. Returns the new row id (for INSERTs)."""
    with transaction(path) as con:
        return con.execute(sql, params).lastrowid or 0


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
