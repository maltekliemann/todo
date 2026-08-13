"""Items, kept in SQLite."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from todo.adapters.sqlite_connection import connect, now, reading, writing
from todo.application.contracts.item_store import ItemCounts, ItemQuery
from todo.domain.body import Body
from todo.domain.deadline import Deadline
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.project_id import ProjectId
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.title import Title
from todo.domain.todo_item import TodoItem
from todo.exceptions import NotFoundError

_DDL = """\
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
    project_id INTEGER
);
CREATE TABLE IF NOT EXISTS todo_tags (
    item_id INTEGER NOT NULL,
    tag     TEXT    NOT NULL,
    PRIMARY KEY (item_id, tag)
);
"""


# Sorted the way items are read: unfinished work first, overdue ahead of
# the rest of its status group, then priority, then age.
_ORDER = (
    "ORDER BY "
    "CASE todos.status "
    "  WHEN 'in-progress' THEN 0 "
    "  WHEN 'todo' THEN 1 "
    "  WHEN 'backlog' THEN 2 "
    "  WHEN 'done' THEN 3 "
    "END, "
    # Today is bound rather than taken from SQLite's UTC date('now'), so
    # this agrees with TodoItem.is_overdue, which compares against the
    # LOCAL date — otherwise a row could sort as overdue and render as not.
    "CASE WHEN todos.deadline IS NOT NULL AND todos.status != 'done' "
    "     AND todos.deadline < ? THEN 0 ELSE 1 END, "
    # The deadline orders only inside the overdue group; everything else
    # collapses to NULL and ties, falling through to priority.
    "CASE WHEN todos.deadline IS NOT NULL AND todos.status != 'done' "
    "     AND todos.deadline < ? THEN todos.deadline ELSE NULL END ASC, "
    "CASE todos.priority "
    "  WHEN 'urgent' THEN 0 "
    "  WHEN 'high' THEN 1 "
    "  WHEN 'medium' THEN 2 "
    "  WHEN 'low' THEN 3 "
    "END, "
    "todos.created_at ASC"
)


class SqliteItemStore:
    """Implements ItemStore.

    Tags are rows in a table of their own. A read fetches the items and
    then their tags — two queries for a page, never one per item — and a
    write replaces an item's rows outright, because tags are a set and
    the stored form must be a function of that set.
    """

    def __init__(self, path: Path) -> None:
        self._conn = connect(path, _DDL)

    def close(self) -> None:
        self._conn.close()

    def _to_item(self, row: sqlite3.Row, tags: frozenset[Tag]) -> TodoItem:
        """A row as the item it stands for.

        Building the value objects is the read-side check that what the
        file holds is still something the domain calls an item.
        """
        done_at: str | None = row["done_at"]
        deadline: str | None = row["deadline"]
        project_id: int | None = row["project_id"]
        return TodoItem(
            id=ItemId(row["id"]),
            title=Title(row["title"]),
            body=Body(row["body"]),
            priority=Priority(row["priority"]),
            status=Status(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            done_at=datetime.fromisoformat(done_at) if done_at else None,
            deadline=Deadline.fromisoformat(deadline) if deadline else None,
            tags=tags,
            project_id=ProjectId(project_id) if project_id is not None else None,
        )

    def _tags_of(
        self, conn: sqlite3.Connection, item_ids: list[int]
    ) -> dict[int, frozenset[Tag]]:
        """Every tag of those items, in one query rather than one each."""
        if not item_ids:
            return {}
        holes = ",".join("?" * len(item_ids))
        rows = conn.execute(
            f"SELECT item_id, tag FROM todo_tags WHERE item_id IN ({holes})",
            item_ids,
        ).fetchall()
        found: dict[int, set[Tag]] = {}
        for row in rows:
            found.setdefault(row["item_id"], set()).add(Tag(row["tag"]))
        return {item_id: frozenset(found.get(item_id, ())) for item_id in item_ids}

    def _to_items(
        self, conn: sqlite3.Connection, rows: list[sqlite3.Row]
    ) -> list[TodoItem]:
        tags = self._tags_of(conn, [r["id"] for r in rows])
        return [self._to_item(r, tags[r["id"]]) for r in rows]

    def _write_tags(
        self, conn: sqlite3.Connection, item_id: int, tags: frozenset[Tag]
    ) -> None:
        """Make the item's rows exactly these. Replacing rather than
        diffing is what makes the stored set a function of the given one."""
        conn.execute("DELETE FROM todo_tags WHERE item_id = ?", (item_id,))
        conn.executemany(
            "INSERT INTO todo_tags (item_id, tag) VALUES (?, ?)",
            [(item_id, tag) for tag in sorted(tags)],
        )

    # --- items -----------------------------------------------------------

    def create(
        self,
        *,
        title: Title,
        body: Body,
        priority: Priority,
        status: Status,
        deadline: Deadline | None = None,
        tags: frozenset[Tag] = frozenset(),
        project_id: ProjectId | None = None,
    ) -> TodoItem:
        stamp = now().isoformat()
        with writing(self._conn, "add todo") as conn:
            cursor = conn.execute(
                "INSERT INTO todos (title, body, priority, status, created_at, "
                "updated_at, done_at, deadline, project_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    title,
                    body,
                    priority.value,
                    status.value,
                    stamp,
                    stamp,
                    stamp if status.done else None,
                    deadline.isoformat() if deadline else None,
                    project_id,
                ),
            )
            new_id = ItemId(cursor.lastrowid or 0)
            self._write_tags(conn, new_id, tags)
        return self.get(new_id)

    def get(self, item_id: ItemId) -> TodoItem:
        with reading(self._conn, f"read todo #{item_id}") as conn:
            row = conn.execute(
                "SELECT * FROM todos WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError(item_id)
            return self._to_item(row, self._tags_of(conn, [row["id"]])[row["id"]])

    def exists(self, item_id: ItemId) -> bool:
        with reading(self._conn, f"read todo #{item_id}") as conn:
            row = conn.execute(
                "SELECT 1 FROM todos WHERE id = ?", (item_id,)
            ).fetchone()
        return row is not None

    def save(self, item: TodoItem) -> TodoItem:
        with writing(self._conn, f"save todo {item.id.label}") as conn:
            if (
                conn.execute("SELECT 1 FROM todos WHERE id = ?", (item.id,)).fetchone()
                is None
            ):
                raise NotFoundError(item.id)
            conn.execute(
                "UPDATE todos SET title = ?, body = ?, priority = ?, status = ?, "
                "updated_at = ?, done_at = ?, deadline = ?, "
                "project_id = ? WHERE id = ?",
                (
                    item.title,
                    item.body,
                    item.priority.value,
                    item.status.value,
                    item.updated_at.isoformat(),
                    item.done_at.isoformat() if item.done_at else None,
                    item.deadline.isoformat() if item.deadline else None,
                    item.project_id,
                    item.id,
                ),
            )
            self._write_tags(conn, item.id, item.tags)
        return self.get(item.id)

    def delete(self, item_id: ItemId) -> None:
        with writing(self._conn, f"delete todo #{item_id}") as conn:
            if (
                conn.execute("SELECT 1 FROM todos WHERE id = ?", (item_id,)).fetchone()
                is None
            ):
                raise NotFoundError(item_id)
            conn.execute("DELETE FROM todo_tags WHERE item_id = ?", (item_id,))
            conn.execute("DELETE FROM todos WHERE id = ?", (item_id,))

    def find(self, query: ItemQuery) -> list[TodoItem]:
        clauses: list[str] = []
        params: list[str | int] = []

        if query.status is not None:
            clauses.append("todos.status = ?")
            params.append(query.status.value)
        elif not query.include_done:
            clauses.append("todos.status != ?")
            params.append(Status.DONE.value)

        if query.priority is not None:
            clauses.append("todos.priority = ?")
            params.append(query.priority.value)

        for tag in sorted(query.tags):
            # One clause per tag: an item carrying all of them is one that
            # appears in every subquery.
            clauses.append("todos.id IN (SELECT item_id FROM todo_tags WHERE tag = ?)")
            params.append(tag)

        if query.text:
            # casefold + instr: Unicode case-insensitive substring match,
            # agreeing with the TUI's own search over the same words.
            clauses.append(
                "(instr(casefold(todos.title), casefold(?)) > 0 "
                "OR instr(casefold(todos.body), casefold(?)) > 0)"
            )
            params.extend([query.text, query.text])

        if query.project_id is not None:
            clauses.append("todos.project_id = ?")
            params.append(query.project_id)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        today = date.today().isoformat()
        params.extend([today, today])
        with reading(self._conn, "list todos") as conn:
            rows = conn.execute(
                f"SELECT * FROM todos{where} {_ORDER}", params
            ).fetchall()
            return self._to_items(conn, rows)

    def done_since(self, moment: datetime) -> list[TodoItem]:
        with reading(self._conn, "read completed todos") as conn:
            rows = conn.execute(
                "SELECT * FROM todos WHERE status = ? AND done_at >= ? "
                "ORDER BY done_at DESC",
                (Status.DONE.value, moment.isoformat()),
            ).fetchall()
            return self._to_items(conn, rows)

    def all_ids(self) -> frozenset[ItemId]:
        with reading(self._conn, "read item ids") as conn:
            rows = conn.execute("SELECT id FROM todos").fetchall()
        return frozenset(ItemId(r["id"]) for r in rows)

    def done_ids(self) -> frozenset[ItemId]:
        with reading(self._conn, "read completed ids") as conn:
            rows = conn.execute(
                "SELECT id FROM todos WHERE status = ?", (Status.DONE.value,)
            ).fetchall()
        return frozenset(ItemId(r["id"]) for r in rows)

    def tags_of_every_item(self) -> list[frozenset[Tag]]:
        with reading(self._conn, "read tags") as conn:
            rows = conn.execute("SELECT item_id, tag FROM todo_tags").fetchall()
        grouped: dict[int, set[Tag]] = {}
        for row in rows:
            grouped.setdefault(row["item_id"], set()).add(Tag(row["tag"]))
        return [frozenset(tags) for tags in grouped.values()]

    def unassign_project(self, project_id: ProjectId) -> None:
        """File every item under that project under nothing instead.

        Deleting a project does not delete its items — but an item may
        not name a project that is gone, and no foreign key says so on
        our behalf.
        """
        with writing(self._conn, f"unassign project #{project_id}") as conn:
            conn.execute(
                "UPDATE todos SET project_id = NULL WHERE project_id = ?",
                (project_id,),
            )

    def counts_by_project(self) -> dict[ProjectId, ItemCounts]:
        with reading(self._conn, "count project items") as conn:
            rows = conn.execute(
                "SELECT project_id, "
                "SUM(CASE WHEN status != 'done' THEN 1 ELSE 0 END) AS open_count, "
                "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_count "
                "FROM todos WHERE project_id IS NOT NULL GROUP BY project_id"
            ).fetchall()
        return {
            ProjectId(r["project_id"]): ItemCounts(
                open=int(r["open_count"]), done=int(r["done_count"])
            )
            for r in rows
        }
