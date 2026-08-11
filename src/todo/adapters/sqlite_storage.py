from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from todo.application.contracts.storage import UNSET, Unset
from todo.domain.enums import Priority, Status
from todo.domain.models import TodoItem
from todo.exceptions import NotFoundError, StorageError

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


def _now() -> datetime:
    return datetime.now(tz=ZoneInfo("UTC"))


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
    )


class SqliteStorage:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)

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
    ) -> TodoItem:
        now = _now().isoformat()
        done_at = now if status == Status.DONE else None
        tags_str = ",".join(tags) if tags else ""
        deadline_str = deadline.isoformat() if deadline else None
        try:
            cur = self._conn.execute(
                "INSERT INTO todos (title, body, priority, status, created_at, "
                "updated_at, done_at, deadline, tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                ),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            raise StorageError(f"Failed to add todo: {e}") from e
        return self.get(cur.lastrowid)  # type: ignore[arg-type]

    def get(self, item_id: int) -> TodoItem:
        row = self._conn.execute(
            "SELECT * FROM todos WHERE id = ?", (item_id,)
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
            is_blocked = any(
                r["status"] != Status.DONE.value for r in status_rows
            )
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
    ) -> TodoItem:
        # Verify it exists
        existing = self.get(item_id)

        sets: list[str] = []
        params: list[str | None] = []

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

        if not sets:
            return existing

        sets.append("updated_at = ?")
        params.append(_now().isoformat())
        params.append(str(item_id))

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
            "SELECT * FROM todos WHERE status = ? AND done_at >= ? "
            "ORDER BY done_at DESC",
            (Status.DONE.value, since.isoformat()),
        ).fetchall()
        return [_row_to_item(r) for r in rows]

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
                "DELETE FROM todo_dependencies "
                "WHERE blocker_id = ? AND blocked_id = ?",
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
        tag: str | None = None,
        include_done: bool = False,
    ) -> list[TodoItem]:
        clauses: list[str] = []
        params: list[str] = []

        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        elif not include_done:
            clauses.append("status != ?")
            params.append(Status.DONE.value)

        if priority is not None:
            clauses.append("priority = ?")
            params.append(priority.value)

        if tag is not None:
            clauses.append("(',' || tags || ',') LIKE ?")
            params.append(f"%,{tag},%")

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        # Sort: overdue first, then by priority weight, then by creation date
        query = (
            f"SELECT * FROM todos{where} "
            "ORDER BY "
            "CASE status "
            "  WHEN 'in-progress' THEN 0 "
            "  WHEN 'todo' THEN 1 "
            "  WHEN 'backlog' THEN 2 "
            "  WHEN 'done' THEN 3 "
            "END, "
            "CASE priority "
            "  WHEN 'urgent' THEN 0 "
            "  WHEN 'high' THEN 1 "
            "  WHEN 'medium' THEN 2 "
            "  WHEN 'low' THEN 3 "
            "END, "
            "created_at ASC"
        )
        rows = self._conn.execute(query, params).fetchall()

        dep_rows = self._conn.execute(
            "SELECT blocker_id, blocked_id FROM todo_dependencies"
        ).fetchall()
        status_rows = self._conn.execute("SELECT id, status FROM todos").fetchall()
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
