"""A running number, kept in SQLite."""

from __future__ import annotations

from pathlib import Path

from todo.adapters.sqlite_connection import connect, writing

_DDL = """\
CREATE TABLE IF NOT EXISTS counters (
    name        TEXT    PRIMARY KEY,
    next_number INTEGER NOT NULL
);
"""


class SqliteCounterStore:
    """Implements CounterStore.

    Which counter this is, is settled when the adapter is built — one
    instance per running number, so the contract has nothing to ask.
    """

    def __init__(self, path: Path, name: str) -> None:
        self._conn = connect(path, _DDL)
        self._name = name

    def close(self) -> None:
        self._conn.close()

    def take(self) -> int:
        with writing(self._conn, f"take the next {self._name} number") as conn:
            # The row appears the first time it is wanted, at 1: there is
            # nothing to set up and nothing to migrate into.
            conn.execute(
                "INSERT OR IGNORE INTO counters (name, next_number) VALUES (?, 1)",
                (self._name,),
            )
            row = conn.execute(
                "UPDATE counters SET next_number = next_number + 1 WHERE name = ? "
                "RETURNING next_number - 1",
                (self._name,),
            ).fetchone()
        return int(row[0])
