"""Whether anything changed, answered by SQLite."""

from __future__ import annotations

from pathlib import Path

from todo.adapters.sqlite_connection import connect, reading


class SqliteChangeFeed:
    """Implements ChangeFeed.

    SQLite keeps a counter that moves whenever another connection commits
    to the file. That it is called data_version, and that it says nothing
    about what changed, are facts about SQLite — which is why they stop
    here.
    """

    def __init__(self, path: Path) -> None:
        self._conn = connect(path, "")

    def close(self) -> None:
        self._conn.close()

    def revision(self) -> int:
        with reading(self._conn, "check for changes") as conn:
            return int(conn.execute("PRAGMA data_version").fetchone()[0])
