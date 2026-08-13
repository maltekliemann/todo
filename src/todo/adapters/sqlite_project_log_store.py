"""Project logs, kept in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from todo.adapters.sqlite_connection import connect, reading, writing
from todo.domain.project_id import ProjectId
from todo.domain.project_update import ProjectUpdate
from todo.domain.update_body import UpdateBody
from todo.domain.update_id import UpdateId
from todo.exceptions import UpdateNotFoundError

_DDL = """\
CREATE TABLE IF NOT EXISTS project_updates (
    id         INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    body       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
"""


def _to_update(row: sqlite3.Row) -> ProjectUpdate:
    return ProjectUpdate(
        id=UpdateId(row["id"]),
        project_id=ProjectId(row["project_id"]),
        body=UpdateBody(row["body"]),
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class SqliteProjectLogStore:
    """Implements ProjectLogStore."""

    def __init__(self, path: Path) -> None:
        self._conn = connect(path, _DDL)

    def close(self) -> None:
        self._conn.close()

    def append(self, update: ProjectUpdate) -> None:
        with writing(self._conn, f"write log entry {update.id.label}") as conn:
            conn.execute(
                "INSERT INTO project_updates (id, project_id, body, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    update.id,
                    update.project_id,
                    update.body,
                    update.created_at.isoformat(),
                ),
            )

    def get(self, update_id: UpdateId) -> ProjectUpdate:
        with reading(self._conn, f"read log entry #{update_id}") as conn:
            row = conn.execute(
                "SELECT * FROM project_updates WHERE id = ?", (update_id,)
            ).fetchone()
            if row is None:
                raise UpdateNotFoundError(update_id)
            return _to_update(row)

    def entries_for(self, project_id: ProjectId) -> list[ProjectUpdate]:
        with reading(self._conn, "read project log") as conn:
            rows = conn.execute(
                "SELECT * FROM project_updates WHERE project_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (project_id,),
            ).fetchall()
            return [_to_update(r) for r in rows]

    def delete_for_project(self, project_id: ProjectId) -> None:
        """Strike the whole log. A project that is gone has no history to
        keep, and no foreign key says so on our behalf."""
        with writing(self._conn, f"delete log of project #{project_id}") as conn:
            conn.execute(
                "DELETE FROM project_updates WHERE project_id = ?", (project_id,)
            )

    def delete(self, update_id: UpdateId) -> None:
        with writing(self._conn, f"delete log entry #{update_id}") as conn:
            if (
                conn.execute(
                    "SELECT 1 FROM project_updates WHERE id = ?", (update_id,)
                ).fetchone()
                is None
            ):
                raise UpdateNotFoundError(update_id)
            conn.execute("DELETE FROM project_updates WHERE id = ?", (update_id,))
