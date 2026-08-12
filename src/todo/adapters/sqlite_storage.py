from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from todo.application.contracts.storage import (
    UNSET,
    ProjectList,
    Unset,
    UpdateList,
)
from todo.domain.enums import Priority, ProjectStatus, Status
from todo.domain.models import Project, ProjectUpdate, TodoItem
from todo.exceptions import (
    DuplicateProjectError,
    NotFoundError,
    ProjectNotFoundError,
    StorageError,
)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS todos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    body       TEXT    NOT NULL DEFAULT '',
    priority   TEXT    NOT NULL DEFAULT 'medium',
    status     TEXT    NOT NULL DEFAULT 'todo',
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL,
    done_at    TEXT,
    deadline   TEXT,
    tags       TEXT    NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS todo_dependencies (
    blocker_id INTEGER NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
    blocked_id INTEGER NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
    PRIMARY KEY (blocker_id, blocked_id)
);
"""

# Versioned migrations, gated by PRAGMA user_version. Index i migrates a
# database at user_version i to i+1. A fresh database runs all of them, so
# fresh and upgraded databases end up with the identical schema.
_MIGRATIONS: list[str] = [
    """\
CREATE TABLE projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    description TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'active',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
ALTER TABLE todos ADD COLUMN project_id INTEGER
    REFERENCES projects(id) ON DELETE SET NULL;
""",
    """\
CREATE TABLE project_updates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    body       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
""",
]


def _now() -> datetime:
    return datetime.now(tz=ZoneInfo("UTC"))


def _like_escape(value: str) -> str:
    """Escape LIKE wildcards so user input matches literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_to_item(
    row: sqlite3.Row,
    *,
    blocked_by: list[int] | None = None,
    blocking: list[int] | None = None,
    is_blocked: bool = False,
) -> TodoItem:
    tags_raw: str = row["tags"]
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []
    done_at_raw: str | None = row["done_at"]
    deadline_raw: str | None = row["deadline"]
    return TodoItem(
        id=row["id"],
        title=row["title"],
        body=row["body"],
        priority=Priority(row["priority"]),
        status=Status(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        done_at=datetime.fromisoformat(done_at_raw) if done_at_raw else None,
        deadline=date.fromisoformat(deadline_raw) if deadline_raw else None,
        tags=tags,
        blocked_by=blocked_by if blocked_by is not None else [],
        blocking=blocking if blocking is not None else [],
        is_blocked=is_blocked,
        project_id=row["project_id"],
        project_name=row["project_name"],
    )


def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        status=ProjectStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


_TODO_SELECT = (
    "SELECT todos.*, projects.name AS project_name FROM todos "
    "LEFT JOIN projects ON projects.id = todos.project_id"
)


def _row_to_update(row: sqlite3.Row) -> ProjectUpdate:
    return ProjectUpdate(
        id=row["id"],
        project_id=row["project_id"],
        body=row["body"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class SqliteStorage:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        try:
            self._conn.executescript(_SCHEMA)
            self._migrate()
        except BaseException:
            # A failed init must not leak a connection holding a write lock
            # (closing rolls back any transaction the failure left open).
            self._conn.rollback()
            self._conn.close()
            raise

    def _migrate(self) -> None:
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        for target, script in enumerate(_MIGRATIONS[version:], start=version + 1):
            self._apply_migration(target, script)

    def _apply_migration(self, target: int, script: str) -> None:
        # Each migration and its version bump run in ONE IMMEDIATE
        # transaction: a crash partway can never strand a half-applied
        # schema, and concurrent openers serialize on the write lock.
        try:
            self._conn.executescript(
                f"BEGIN IMMEDIATE;\n{script}\nPRAGMA user_version = {target};\nCOMMIT;"
            )
        except sqlite3.OperationalError:
            self._conn.rollback()
            current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if current >= target:
                # Lost the race: another process applied this migration
                # between our version check and our attempt. That's success.
                return
            raise

    def close(self) -> None:
        self._conn.close()

    def data_version(self) -> int:
        """Return SQLite's data_version, which increments on any external write."""
        row = self._conn.execute("PRAGMA data_version").fetchone()
        return int(row[0])

    def add(
        self,
        title: str,
        *,
        body: str = "",
        priority: Priority = Priority.MEDIUM,
        status: Status = Status.TODO,
        deadline: date | None = None,
        tags: list[str] | None = None,
        project_id: int | None = None,
    ) -> TodoItem:
        now = _now().isoformat()
        done_at = now if status == Status.DONE else None
        tags_str = ",".join(tags) if tags else ""
        deadline_str = deadline.isoformat() if deadline else None
        try:
            cur = self._conn.execute(
                "INSERT INTO todos (title, body, priority, status, created_at, "
                "updated_at, done_at, deadline, tags, project_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    title,
                    body,
                    priority.value,
                    status.value,
                    now,
                    now,
                    done_at,
                    deadline_str,
                    tags_str,
                    project_id,
                ),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to add todo: {e}") from e
        return self.get(cur.lastrowid)  # type: ignore[arg-type]

    def get(self, item_id: int) -> TodoItem:
        row = self._conn.execute(
            f"{_TODO_SELECT} WHERE todos.id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(item_id)
        blocker_rows = self._conn.execute(
            "SELECT blocker_id FROM todo_dependencies WHERE blocked_id = ? "
            "ORDER BY blocker_id ASC",
            (item_id,),
        ).fetchall()
        blocked_by = [r["blocker_id"] for r in blocker_rows]
        blocking_rows = self._conn.execute(
            "SELECT blocked_id FROM todo_dependencies WHERE blocker_id = ? "
            "ORDER BY blocked_id ASC",
            (item_id,),
        ).fetchall()
        blocking = [r["blocked_id"] for r in blocking_rows]
        is_blocked = False
        if row["status"] != Status.DONE.value and blocked_by:
            placeholders = ",".join("?" for _ in blocked_by)
            status_rows = self._conn.execute(
                f"SELECT status FROM todos WHERE id IN ({placeholders})",
                blocked_by,
            ).fetchall()
            is_blocked = any(r["status"] != Status.DONE.value for r in status_rows)
        return _row_to_item(
            row,
            blocked_by=blocked_by,
            blocking=blocking,
            is_blocked=is_blocked,
        )

    def update(
        self,
        item_id: int,
        *,
        title: str | None = None,
        body: str | None = None,
        priority: Priority | None = None,
        status: Status | None = None,
        deadline: date | None | Unset = UNSET,
        tags: list[str] | None = None,
        project_id: int | None | Unset = UNSET,
    ) -> TodoItem:
        # Verify it exists
        existing = self.get(item_id)

        sets: list[str] = []
        params: list[str | int | None] = []

        if title is not None:
            sets.append("title = ?")
            params.append(title)
        if body is not None:
            sets.append("body = ?")
            params.append(body)
        if priority is not None:
            sets.append("priority = ?")
            params.append(priority.value)
        if status is not None:
            sets.append("status = ?")
            params.append(status.value)
            if status == Status.DONE and existing.status != Status.DONE:
                sets.append("done_at = ?")
                params.append(_now().isoformat())
            elif status != Status.DONE:
                sets.append("done_at = ?")
                params.append(None)
        if not isinstance(deadline, Unset):
            sets.append("deadline = ?")
            params.append(deadline.isoformat() if deadline else None)
        if tags is not None:
            sets.append("tags = ?")
            params.append(",".join(tags))
        if not isinstance(project_id, Unset):
            sets.append("project_id = ?")
            params.append(project_id)

        if not sets:
            return existing

        sets.append("updated_at = ?")
        params.append(_now().isoformat())
        params.append(item_id)

        try:
            self._conn.execute(
                f"UPDATE todos SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            self._conn.commit()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to update todo #{item_id}: {e}") from e
        return self.get(item_id)

    def delete(self, item_id: int) -> None:
        self.get(item_id)  # raises NotFoundError if missing
        self._conn.execute("DELETE FROM todos WHERE id = ?", (item_id,))
        self._conn.commit()

    def done_since(self, since: datetime) -> list[TodoItem]:
        rows = self._conn.execute(
            f"{_TODO_SELECT} WHERE todos.status = ? AND todos.done_at >= ? "
            "ORDER BY todos.done_at DESC",
            (Status.DONE.value, since.isoformat()),
        ).fetchall()
        return self._hydrate_dependencies(rows)

    def _hydrate_dependencies(self, rows: list[sqlite3.Row]) -> list[TodoItem]:
        """Build TodoItems with blocked_by/blocking/is_blocked populated.

        Every multi-item query must go through here so dependency data is
        consistent across list, summary, and any future read path. Queries
        are scoped to the selected rows so cost tracks the result size, not
        total history.
        """
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        ph = ",".join("?" for _ in ids)
        dep_rows = self._conn.execute(
            "SELECT blocker_id, blocked_id FROM todo_dependencies "
            f"WHERE blocked_id IN ({ph}) OR blocker_id IN ({ph})",
            [*ids, *ids],
        ).fetchall()
        blocker_ids = sorted({d["blocker_id"] for d in dep_rows})
        status_by_id: dict[int, str] = {}
        if blocker_ids:
            bph = ",".join("?" for _ in blocker_ids)
            status_rows = self._conn.execute(
                f"SELECT id, status FROM todos WHERE id IN ({bph})",
                blocker_ids,
            ).fetchall()
            status_by_id = {r["id"]: r["status"] for r in status_rows}
        blocked_by_map: dict[int, list[int]] = {}
        blocking_map: dict[int, list[int]] = {}
        for dep in dep_rows:
            blocked_by_map.setdefault(dep["blocked_id"], []).append(dep["blocker_id"])
            blocking_map.setdefault(dep["blocker_id"], []).append(dep["blocked_id"])

        items: list[TodoItem] = []
        for r in rows:
            blocked_by = sorted(blocked_by_map.get(r["id"], []))
            blocking = sorted(blocking_map.get(r["id"], []))
            is_blocked = r["status"] != Status.DONE.value and any(
                status_by_id.get(b) != Status.DONE.value for b in blocked_by
            )
            items.append(
                _row_to_item(
                    r,
                    blocked_by=blocked_by,
                    blocking=blocking,
                    is_blocked=is_blocked,
                )
            )
        return items

    def add_blocker(self, blocked_id: int, blocker_id: int) -> None:
        self.get(blocked_id)  # raises NotFoundError if missing
        self.get(blocker_id)  # raises NotFoundError if missing
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO todo_dependencies (blocker_id, blocked_id) "
                "VALUES (?, ?)",
                (blocker_id, blocked_id),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to add blocker: {e}") from e

    def remove_blocker(self, blocked_id: int, blocker_id: int) -> None:
        try:
            self._conn.execute(
                "DELETE FROM todo_dependencies WHERE blocker_id = ? AND blocked_id = ?",
                (blocker_id, blocked_id),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to remove blocker: {e}") from e

    def list(
        self,
        *,
        status: Status | None = None,
        priority: Priority | None = None,
        tags: list[str] | None = None,
        search: str | None = None,
        project_id: int | None = None,
        include_done: bool = False,
    ) -> list[TodoItem]:
        clauses: list[str] = []
        params: list[str | int] = []

        if status is not None:
            clauses.append("todos.status = ?")
            params.append(status.value)
        elif not include_done:
            clauses.append("todos.status != ?")
            params.append(Status.DONE.value)

        if priority is not None:
            clauses.append("todos.priority = ?")
            params.append(priority.value)

        for tag in tags or []:
            clauses.append("(',' || todos.tags || ',') LIKE ? ESCAPE '\\'")
            params.append(f"%,{_like_escape(tag)},%")

        if search is not None and search != "":
            clauses.append(
                "(todos.title LIKE ? ESCAPE '\\' OR todos.body LIKE ? ESCAPE '\\')"
            )
            pattern = f"%{_like_escape(search)}%"
            params.extend([pattern, pattern])

        if project_id is not None:
            clauses.append("todos.project_id = ?")
            params.append(project_id)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        # Sort: overdue first, then by priority weight, then by creation date
        query = (
            f"{_TODO_SELECT}{where} "
            "ORDER BY "
            "CASE todos.status "
            "  WHEN 'in-progress' THEN 0 "
            "  WHEN 'todo' THEN 1 "
            "  WHEN 'backlog' THEN 2 "
            "  WHEN 'done' THEN 3 "
            "END, "
            "CASE todos.priority "
            "  WHEN 'urgent' THEN 0 "
            "  WHEN 'high' THEN 1 "
            "  WHEN 'medium' THEN 2 "
            "  WHEN 'low' THEN 3 "
            "END, "
            "todos.created_at ASC"
        )
        rows = self._conn.execute(query, params).fetchall()
        return self._hydrate_dependencies(rows)

    def add_project(self, name: str, *, description: str = "") -> Project:
        now = _now().isoformat()
        try:
            cur = self._conn.execute(
                "INSERT INTO projects (name, description, status, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?)",
                (name, description, ProjectStatus.ACTIVE.value, now, now),
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            raise DuplicateProjectError(name) from e
        except sqlite3.Error as e:
            raise StorageError(f"Failed to add project: {e}") from e
        return self.get_project(cur.lastrowid)  # type: ignore[arg-type]

    def get_project(self, project_id: int) -> Project:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if row is None:
            raise ProjectNotFoundError(project_id)
        return _row_to_project(row)

    def get_project_by_name(self, name: str) -> Project:
        row = self._conn.execute(
            "SELECT * FROM projects WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            raise ProjectNotFoundError(name)
        return _row_to_project(row)

    def list_projects(self, *, include_archived: bool = False) -> "ProjectList":
        where = "" if include_archived else " WHERE status = 'active'"
        rows = self._conn.execute(
            f"SELECT * FROM projects{where} ORDER BY name ASC"
        ).fetchall()
        return [_row_to_project(r) for r in rows]

    def update_project(
        self,
        project_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        status: ProjectStatus | None = None,
    ) -> Project:
        self.get_project(project_id)  # raises ProjectNotFoundError if missing

        sets: list[str] = []
        params: list[str | int] = []
        if name is not None:
            sets.append("name = ?")
            params.append(name)
        if description is not None:
            sets.append("description = ?")
            params.append(description)
        if status is not None:
            sets.append("status = ?")
            params.append(status.value)
        if not sets:
            return self.get_project(project_id)

        sets.append("updated_at = ?")
        params.append(_now().isoformat())
        params.append(project_id)
        try:
            self._conn.execute(
                f"UPDATE projects SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            self._conn.commit()
        except sqlite3.IntegrityError as e:
            raise DuplicateProjectError(name or "") from e
        except sqlite3.Error as e:
            raise StorageError(f"Failed to update project #{project_id}: {e}") from e
        return self.get_project(project_id)

    def delete_project(self, project_id: int) -> None:
        self.get_project(project_id)  # raises ProjectNotFoundError if missing
        self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        self._conn.commit()

    def add_project_update(self, project_id: int, body: str) -> ProjectUpdate:
        self.get_project(project_id)  # raises ProjectNotFoundError if missing
        now = _now().isoformat()
        try:
            cur = self._conn.execute(
                "INSERT INTO project_updates (project_id, body, created_at) "
                "VALUES (?, ?, ?)",
                (project_id, body, now),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to log project update: {e}") from e
        row = self._conn.execute(
            "SELECT * FROM project_updates WHERE id = ?", (cur.lastrowid,)
        ).fetchone()
        return _row_to_update(row)

    def list_project_updates(self, project_id: int) -> "UpdateList":
        rows = self._conn.execute(
            "SELECT * FROM project_updates WHERE project_id = ? "
            "ORDER BY created_at DESC, id DESC",
            (project_id,),
        ).fetchall()
        return [_row_to_update(r) for r in rows]
