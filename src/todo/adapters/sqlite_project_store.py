"""Projects, kept in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from todo.adapters.sqlite_connection import connect, reading, writing
from todo.domain.description import Description
from todo.domain.project import Project
from todo.domain.project_filter import ProjectFilter
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName
from todo.domain.project_status import ProjectStatus
from todo.exceptions import DuplicateProjectError, ProjectNotFoundError, StorageError

_DDL = """\
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL UNIQUE,
    description TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'not-started',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
"""


def _to_status(value: str) -> ProjectStatus:
    """Decode the status column, refusing what it should never hold."""
    try:
        return ProjectStatus(value)
    except ValueError:
        raise StorageError(f"Unknown project status {value!r}") from None


def _to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=ProjectId(row["id"]),
        name=ProjectName(row["name"]),
        description=Description(row["description"]),
        status=_to_status(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


class SqliteProjectStore:
    """Implements ProjectStore."""

    def __init__(self, path: Path) -> None:
        self._conn = connect(path, _DDL)

    def close(self) -> None:
        self._conn.close()

    def create(self, project: Project) -> None:
        with writing(self._conn, f"create project {project.id.label}") as conn:
            try:
                conn.execute(
                    "INSERT INTO projects (id, name, description, status, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        project.id,
                        project.name,
                        project.description,
                        project.status.value,
                        project.created_at.isoformat(),
                        project.updated_at.isoformat(),
                    ),
                )
            except sqlite3.IntegrityError as e:
                # The name is taken. That is a thing a person did, not a
                # database failure, so it is named as such before the
                # write's generic wrapping can bury it.
                raise DuplicateProjectError(project.name) from e

    def get(self, project_id: ProjectId) -> Project:
        with reading(self._conn, f"read project #{project_id}") as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise ProjectNotFoundError(project_id)
            return _to_project(row)

    def get_by_name(self, name: ProjectName) -> Project:
        with reading(self._conn, "read project") as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                raise ProjectNotFoundError(name)
            return _to_project(row)

    def save(self, project: Project) -> Project:
        with writing(self._conn, f"save project {project.id.label}") as conn:
            if (
                conn.execute(
                    "SELECT 1 FROM projects WHERE id = ?", (project.id,)
                ).fetchone()
                is None
            ):
                raise ProjectNotFoundError(project.id)
            try:
                conn.execute(
                    "UPDATE projects SET name = ?, description = ?, status = ?, "
                    "updated_at = ? WHERE id = ?",
                    (
                        project.name,
                        project.description,
                        project.status.value,
                        project.updated_at.isoformat(),
                        project.id,
                    ),
                )
            except sqlite3.IntegrityError as e:
                raise DuplicateProjectError(project.name) from e
        return self.get(project.id)

    def delete(self, project_id: ProjectId) -> None:
        with writing(self._conn, f"delete project #{project_id}") as conn:
            if (
                conn.execute(
                    "SELECT 1 FROM projects WHERE id = ?", (project_id,)
                ).fetchone()
                is None
            ):
                raise ProjectNotFoundError(project_id)
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def find(self, project_filter: ProjectFilter) -> list[Project]:
        ended = ",".join(f"'{s.value}'" for s in ProjectStatus if s.ended)
        where = (
            "" if project_filter.include_ended else f" WHERE status NOT IN ({ended})"
        )
        with reading(self._conn, "list projects") as conn:
            rows = conn.execute(
                f"SELECT * FROM projects{where} ORDER BY name ASC"
            ).fetchall()
            return [_to_project(r) for r in rows]
