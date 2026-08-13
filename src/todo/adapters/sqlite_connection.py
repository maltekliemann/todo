"""Opening the SQLite file, and running one statement against it.

Not an adapter: no contract is implemented here, and nothing here knows
what any table is called. Each store brings its own DDL and gets a
connection back — the pragmas and what it means for one change to happen
at all or not at all are all that is shared.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from todo.exceptions import StorageError


def now() -> datetime:
    return datetime.now(tz=ZoneInfo("UTC"))


def _casefold(value: str | None) -> str | None:
    return value.casefold() if value is not None else None


def connect(path: Path, ddl: str) -> sqlite3.Connection:
    """A connection to the todo database with the caller's tables present.

    The DDL belongs to the store that passes it: a store creates what it
    keeps and knows nothing about anyone else's tables.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(path))
    except (OSError, sqlite3.Error) as e:
        # An unusable path is a storage failure like any other, so both
        # frontends report it instead of showing a traceback.
        raise StorageError(f"Cannot open database at {path}: {e}") from e
    conn.row_factory = sqlite3.Row
    # SQL-side Unicode case folding for search: SQLite's own LIKE and
    # lower() fold ASCII only, which would disagree with the TUI's
    # Python-side search on the same words.
    conn.create_function("casefold", 1, _casefold, deterministic=True)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.executescript(ddl)
    except BaseException as e:
        # A failed open must not leak a connection holding the write lock;
        # closing rolls back whatever the failure left open.
        conn.rollback()
        conn.close()
        if isinstance(e, sqlite3.Error):
            raise StorageError(f"Cannot open database at {path}: {e}") from e
        raise
    return conn


@contextmanager
def reading(conn: sqlite3.Connection, action: str) -> Iterator[sqlite3.Connection]:
    """Read, turning anything SQLite or a decoder says into StorageError.

    ValueError counts: decoding rows into domain values happens on these
    paths, so a value in the file the domain refuses is a storage failure,
    not something a frontend could be expected to catch.
    """
    try:
        yield conn
    except (sqlite3.Error, OverflowError, ValueError) as e:
        raise StorageError(f"Failed to {action}: {e}") from e


@contextmanager
def writing(conn: sqlite3.Connection, action: str) -> Iterator[sqlite3.Connection]:
    """One change, all of it or none of it.

    BEGIN IMMEDIATE takes the write lock up front, so concurrent writers
    serialize instead of racing. This is what lets a store method be
    atomic without the application ever asking for a transaction: a store
    keeps one aggregate, and keeping it is one of these.
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
    except (sqlite3.Error, OverflowError) as e:
        raise StorageError(f"Failed to {action}: {e}") from e
    try:
        yield conn
    except (sqlite3.Error, OverflowError) as e:
        # Same wrapping as the read paths: a driver-level failure inside
        # the write is a storage failure, not something a frontend could
        # be expected to catch. Domain refusals are not sqlite errors and
        # travel out untouched.
        conn.rollback()
        raise StorageError(f"Failed to {action}: {e}") from e
    except BaseException:
        conn.rollback()
        raise
    try:
        conn.commit()
    except (sqlite3.Error, OverflowError) as e:
        raise StorageError(f"Failed to {action}: {e}") from e
