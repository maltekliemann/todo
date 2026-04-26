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
"""


def _now() -> datetime:
    return datetime.now(tz=ZoneInfo("UTC"))


def _row_to_item(row: sqlite3.Row) -> TodoItem:
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
    )


class SqliteStorage:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
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
        return _row_to_item(row)

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
        return [_row_to_item(r) for r in rows]

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
