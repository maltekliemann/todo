from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from todo.adapters.sqlite_migrations import MIGRATIONS, SCHEMA
from todo.adapters.tag_column import decode_tags, encode_tags
from todo.application.contracts.storage import (
    UNSET,
    EdgeList,
    ItemTagLists,
    ProjectList,
    Unset,
    UpdateList,
)
from todo.domain.body import Body
from todo.domain.deadline import Deadline
from todo.domain.description import Description
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName
from todo.domain.project_status import ProjectStatus
from todo.domain.project_update import ProjectUpdate
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.title import Title
from todo.domain.todo_item import TodoItem
from todo.domain.update_body import UpdateBody
from todo.exceptions import (
    DuplicateProjectError,
    NotFoundError,
    ProjectNotFoundError,
    StorageError,
)


def _now() -> datetime:
    return datetime.now(tz=ZoneInfo("UTC"))


def _sql_casefold(value: str | None) -> str | None:
    return value.casefold() if value is not None else None


def _row_to_item(row: sqlite3.Row) -> TodoItem:
    tags_raw: str = row["tags"]
    # Constructing the value objects is the read-side check that what was
    # stored is still something the domain calls valid.
    tags = decode_tags(tags_raw) if tags_raw else []
    done_at_raw: str | None = row["done_at"]
    deadline_raw: str | None = row["deadline"]
    return TodoItem(
        id=ItemId(row["id"]),
        title=Title(row["title"]),
        body=Body(row["body"]),
        priority=Priority(row["priority"]),
        status=Status(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        done_at=datetime.fromisoformat(done_at_raw) if done_at_raw else None,
        deadline=Deadline.fromisoformat(deadline_raw) if deadline_raw else None,
        tags=tags,
        project=_joined_project(row),
    )


def _joined_project(row: sqlite3.Row) -> Project | None:
    """The project the join brought along, if the item is filed under one."""
    if row["proj_id"] is None:
        return None
    return Project(
        id=ProjectId(row["proj_id"]),
        name=ProjectName(row["proj_name"]),
        description=Description(row["proj_description"]),
        status=ProjectStatus(row["proj_status"]),
        created_at=datetime.fromisoformat(row["proj_created_at"]),
        updated_at=datetime.fromisoformat(row["proj_updated_at"]),
    )


def _row_to_project(row: sqlite3.Row) -> Project:
    return Project(
        id=ProjectId(row["id"]),
        name=ProjectName(row["name"]),
        description=Description(row["description"]),
        status=ProjectStatus(row["status"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


# The project's own columns, aliased: an item carries the Project, not a
# copy of two of its fields that can drift apart.
_TODO_SELECT = (
    "SELECT todos.*, "
    "projects.id AS proj_id, projects.name AS proj_name, "
    "projects.description AS proj_description, "
    "projects.status AS proj_status, "
    "projects.created_at AS proj_created_at, "
    "projects.updated_at AS proj_updated_at "
    "FROM todos LEFT JOIN projects ON projects.id = todos.project_id"
)


def _row_to_update(row: sqlite3.Row) -> ProjectUpdate:
    return ProjectUpdate(
        id=row["id"],
        project_id=ProjectId(row["project_id"]),
        body=row["body"],
        created_at=datetime.fromisoformat(row["created_at"]),
    )


class SqliteStorage:
    def __init__(self, db_path: Path) -> None:
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(db_path))
        except (OSError, sqlite3.Error) as e:
            # A bad db path (unwritable parent, file in the way, path is a
            # directory) must be StorageError like every other failure, so
            # both frontends report it cleanly instead of a traceback.
            raise StorageError(f"Cannot open database at {db_path}: {e}") from e
        self._in_txn = False
        self._conn.row_factory = sqlite3.Row
        # SQL-side Unicode case folding for search: SQLite's LIKE/lower()
        # only fold ASCII, which would contradict the TUI's Python search.
        self._conn.create_function("casefold", 1, _sql_casefold, deterministic=True)
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout = 5000")
            self._conn.executescript(SCHEMA)
            self._migrate()
        except BaseException as e:
            # A failed init must not leak a connection holding a write lock
            # (closing rolls back any transaction the failure left open).
            self._conn.rollback()
            self._conn.close()
            if isinstance(e, sqlite3.Error):
                # Same wrapping contract as reads and writes: a corrupt or
                # unusable database file surfaces as StorageError.
                raise StorageError(f"Cannot open database at {db_path}: {e}") from e
            raise

    def _migrate(self) -> None:
        version = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
        for target, script in enumerate(MIGRATIONS[version:], start=version + 1):
            self._apply_migration(target, script)

    def _apply_migration(
        self,
        target: int,
        migration: str | Callable[[sqlite3.Connection], None],
    ) -> None:
        # Each migration and its version bump run in ONE IMMEDIATE
        # transaction: a crash partway can never strand a half-applied
        # schema, and concurrent openers serialize on the write lock.
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            if callable(migration):
                migration(self._conn)
            else:
                for statement in migration.split(";"):
                    if statement.strip():
                        self._conn.execute(statement)
            self._conn.execute(f"PRAGMA user_version = {target}")
            self._conn.commit()
        except sqlite3.Error:
            self._conn.rollback()
            current = int(self._conn.execute("PRAGMA user_version").fetchone()[0])
            if current >= target:
                # Lost the race: another process applied this migration
                # between our version check and our attempt. That's success.
                return
            raise

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Run several storage calls as one atomic unit.

        BEGIN IMMEDIATE takes the write lock up front, serializing
        concurrent writers (cycle checks + inserts race otherwise). Nested
        use joins the outer transaction.
        """
        if self._in_txn:
            yield
            return
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except (sqlite3.Error, OverflowError) as e:
            raise StorageError(f"Failed to start transaction: {e}") from e
        self._in_txn = True
        try:
            yield
        except BaseException:
            self._in_txn = False
            self._conn.rollback()
            raise
        else:
            self._in_txn = False
            try:
                self._conn.commit()
            except (sqlite3.Error, OverflowError) as e:
                raise StorageError(f"Failed to commit transaction: {e}") from e

    def _commit(self) -> None:
        """Commit unless inside an explicit transaction (which owns it)."""
        if not self._in_txn:
            self._conn.commit()

    @contextmanager
    def _read_guard(self, action: str) -> Iterator[None]:
        """Wrap sqlite errors on read paths into StorageError.

        Same contract as the write methods: callers (CLI _SafeGroup, TUI
        TodoError guards) only handle the domain hierarchy, so a raw
        sqlite3.Error from a corrupted or vanished database would crash
        them. Domain exceptions (NotFoundError etc.) pass through.

        ValueError is included because row decoding lives on these paths:
        a bad enum value or malformed timestamp in the file is a storage
        failure, not something a frontend can be expected to catch.
        """
        try:
            yield
        except (sqlite3.Error, OverflowError, ValueError) as e:
            raise StorageError(f"Failed to {action}: {e}") from e

    def data_version(self) -> int:
        """Return SQLite's data_version, which increments on any external write."""
        with self._read_guard("read data version"):
            row = self._conn.execute("PRAGMA data_version").fetchone()
            return int(row[0])

    def add(
        self,
        title: Title,
        *,
        body: str = "",
        priority: Priority = Priority.MEDIUM,
        status: Status = Status.TODO,
        deadline: Deadline | None = None,
        tags: list[Tag] | None = None,
        project_id: int | None = None,
    ) -> TodoItem:
        now = _now().isoformat()
        done_at = now if status == Status.DONE else None
        tags_str = encode_tags(tags) if tags else ""
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
            self._commit()
        except (sqlite3.Error, OverflowError) as e:
            raise StorageError(f"Failed to add todo: {e}") from e
        return self.get(cur.lastrowid)  # type: ignore[arg-type]

    def get(self, item_id: ItemId) -> TodoItem:
        with self._read_guard(f"read todo #{item_id}"):
            return self._get_unguarded(item_id)

    def _get_unguarded(self, item_id: ItemId) -> TodoItem:
        row = self._conn.execute(
            f"{_TODO_SELECT} WHERE todos.id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(item_id)
        return _row_to_item(row)

    def update(
        self,
        item_id: ItemId,
        *,
        title: Title | None = None,
        body: str | None = None,
        priority: Priority | None = None,
        status: Status | None = None,
        deadline: Deadline | None | Unset = UNSET,
        tags: list[Tag] | None = None,
        project_id: int | None | Unset = UNSET,
    ) -> TodoItem:
        # Existence + the one field the done_at transition needs — not a
        # full dependency hydration used as an existence check.
        with self._read_guard(f"read todo #{item_id}"):
            status_row = self._conn.execute(
                "SELECT status FROM todos WHERE id = ?", (item_id,)
            ).fetchone()
        if status_row is None:
            raise NotFoundError(item_id)
        existing_status = Status(status_row["status"])

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
            if status == Status.DONE and existing_status != Status.DONE:
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
            params.append(encode_tags(tags))
        if not isinstance(project_id, Unset):
            sets.append("project_id = ?")
            params.append(project_id)

        if not sets:
            return self.get(item_id)

        sets.append("updated_at = ?")
        params.append(_now().isoformat())
        params.append(item_id)

        try:
            self._conn.execute(
                f"UPDATE todos SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            self._commit()
        except (sqlite3.Error, OverflowError) as e:
            raise StorageError(f"Failed to update todo #{item_id}: {e}") from e
        return self.get(item_id)

    def delete(self, item_id: ItemId) -> None:
        self._assert_exists(item_id)
        try:
            self._conn.execute("DELETE FROM todos WHERE id = ?", (item_id,))
            self._commit()
        except (sqlite3.Error, OverflowError) as e:
            raise StorageError(f"Failed to delete todo #{item_id}: {e}") from e

    def done_since(self, since: datetime) -> list[TodoItem]:
        with self._read_guard("read completed todos"):
            rows = self._conn.execute(
                f"{_TODO_SELECT} WHERE todos.status = ? AND todos.done_at >= ? "
                "ORDER BY todos.done_at DESC",
                (Status.DONE.value, since.isoformat()),
            ).fetchall()
            return [_row_to_item(r) for r in rows]

    def _assert_exists(self, item_id: ItemId) -> None:
        """Existence check without dependency hydration."""
        with self._read_guard(f"read todo #{item_id}"):
            row = self._conn.execute(
                "SELECT 1 FROM todos WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(item_id)

    def add_blocker(self, blocked_id: ItemId, blocker_id: ItemId) -> None:
        self._assert_exists(blocked_id)
        self._assert_exists(blocker_id)
        try:
            self._conn.execute(
                "INSERT OR IGNORE INTO todo_dependencies (blocker_id, blocked_id) "
                "VALUES (?, ?)",
                (blocker_id, blocked_id),
            )
            self._commit()
        except (sqlite3.Error, OverflowError) as e:
            raise StorageError(f"Failed to add blocker: {e}") from e

    def remove_blocker(self, blocked_id: ItemId, blocker_id: ItemId) -> None:
        try:
            self._conn.execute(
                "DELETE FROM todo_dependencies WHERE blocker_id = ? AND blocked_id = ?",
                (blocker_id, blocked_id),
            )
            self._commit()
        except (sqlite3.Error, OverflowError) as e:
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
            # instr, not LIKE: exact case-sensitive match (tag identity is
            # case-sensitive — `todo tags` counts 'Work' and 'work' apart)
            # with no wildcard semantics to escape.
            clauses.append("instr(',' || todos.tags || ',', ',' || ? || ',') > 0")
            params.append(tag)

        if search is not None and search != "":
            # casefold + instr: Unicode case-insensitive literal substring
            # match, agreeing with the TUI's Python-side search.
            clauses.append(
                "(instr(casefold(todos.title), casefold(?)) > 0 "
                "OR instr(casefold(todos.body), casefold(?)) > 0)"
            )
            params.extend([search, search])

        if project_id is not None:
            clauses.append("todos.project_id = ?")
            params.append(project_id)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        # Sort: within a status group, overdue first (soonest deadline
        # first among them), then priority weight, then creation date.
        # Today is bound rather than using SQLite's UTC date('now') so this
        # matches TodoItem.is_overdue, which compares against the LOCAL
        # date — otherwise a row could sort as overdue but render as not.
        today = date.today().isoformat()
        overdue_first = (
            "CASE WHEN todos.deadline IS NOT NULL AND todos.status != 'done' "
            "AND todos.deadline < ? THEN 0 ELSE 1 END"
        )
        # Deadline only orders inside the overdue group; everything else
        # collapses to NULL and ties, falling through to priority.
        overdue_deadline = (
            "CASE WHEN todos.deadline IS NOT NULL AND todos.status != 'done' "
            "AND todos.deadline < ? THEN todos.deadline ELSE NULL END"
        )
        query = (
            f"{_TODO_SELECT}{where} "
            "ORDER BY "
            "CASE todos.status "
            "  WHEN 'in-progress' THEN 0 "
            "  WHEN 'todo' THEN 1 "
            "  WHEN 'backlog' THEN 2 "
            "  WHEN 'done' THEN 3 "
            "END, "
            f"{overdue_first}, "
            f"{overdue_deadline} ASC, "
            "CASE todos.priority "
            "  WHEN 'urgent' THEN 0 "
            "  WHEN 'high' THEN 1 "
            "  WHEN 'medium' THEN 2 "
            "  WHEN 'low' THEN 3 "
            "END, "
            "todos.created_at ASC"
        )
        params.extend([today, today])
        with self._read_guard("list todos"):
            rows = self._conn.execute(query, params).fetchall()
            return [_row_to_item(r) for r in rows]

    def add_project(
        self, name: ProjectName, *, description: Description | str = ""
    ) -> Project:
        now = _now().isoformat()
        try:
            cur = self._conn.execute(
                "INSERT INTO projects (name, description, status, created_at, "
                "updated_at) VALUES (?, ?, ?, ?, ?)",
                (name, description, ProjectStatus.ACTIVE.value, now, now),
            )
            self._commit()
        except sqlite3.IntegrityError as e:
            raise DuplicateProjectError(name) from e
        except (sqlite3.Error, OverflowError) as e:
            raise StorageError(f"Failed to add project: {e}") from e
        return self.get_project(cur.lastrowid)  # type: ignore[arg-type]

    def get_project(self, project_id: int) -> Project:
        with self._read_guard(f"read project #{project_id}"):
            row = self._conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            if row is None:
                raise ProjectNotFoundError(project_id)
            return _row_to_project(row)

    def get_project_by_name(self, name: str) -> Project:
        with self._read_guard("read project"):
            row = self._conn.execute(
                "SELECT * FROM projects WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                raise ProjectNotFoundError(name)
            return _row_to_project(row)

    def done_ids(self) -> set[ItemId]:
        """Every finished item. With the graph, this is what decides
        blocked-ness — a rule that used to live in SQL."""
        with self._read_guard("read completed ids"):
            rows = self._conn.execute(
                "SELECT id FROM todos WHERE status = ?", (Status.DONE.value,)
            ).fetchall()
        return {ItemId(r["id"]) for r in rows}

    def dependency_edges(self) -> EdgeList:
        """All (blocker_id, blocked_id) edges — one query for graph walks."""
        with self._read_guard("read dependencies"):
            rows = self._conn.execute(
                "SELECT blocker_id, blocked_id FROM todo_dependencies"
            ).fetchall()
        return [(ItemId(r["blocker_id"]), ItemId(r["blocked_id"])) for r in rows]

    def item_tags(self) -> ItemTagLists:
        """Every todo's tags — one column scan for counting.

        Decoded here: the comma-joined column is this adapter's encoding,
        and handing it out raw made every caller a parser of it.
        """
        with self._read_guard("read tags"):
            rows = self._conn.execute("SELECT tags FROM todos").fetchall()
        return [decode_tags(r["tags"]) for r in rows]

    def project_counts(self) -> dict[int, tuple[int, int]]:
        """project_id -> (open, done) item counts, computed in SQL."""
        with self._read_guard("count project items"):
            rows = self._conn.execute(
                "SELECT project_id, "
                "SUM(CASE WHEN status != 'done' THEN 1 ELSE 0 END) AS open_count, "
                "SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_count "
                "FROM todos WHERE project_id IS NOT NULL GROUP BY project_id"
            ).fetchall()
        return {
            r["project_id"]: (int(r["open_count"]), int(r["done_count"])) for r in rows
        }

    def list_projects(self, *, include_archived: bool = False) -> "ProjectList":
        where = "" if include_archived else " WHERE status = 'active'"
        with self._read_guard("list projects"):
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
            self._commit()
        except sqlite3.IntegrityError as e:
            raise DuplicateProjectError(name or "") from e
        except (sqlite3.Error, OverflowError) as e:
            raise StorageError(f"Failed to update project #{project_id}: {e}") from e
        return self.get_project(project_id)

    def delete_project(self, project_id: int) -> None:
        self.get_project(project_id)  # raises ProjectNotFoundError if missing
        try:
            self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            self._commit()
        except (sqlite3.Error, OverflowError) as e:
            raise StorageError(f"Failed to delete project #{project_id}: {e}") from e

    def add_project_update(self, project_id: int, body: UpdateBody) -> ProjectUpdate:
        self.get_project(project_id)  # raises ProjectNotFoundError if missing
        now = _now().isoformat()
        try:
            cur = self._conn.execute(
                "INSERT INTO project_updates (project_id, body, created_at) "
                "VALUES (?, ?, ?)",
                (project_id, body, now),
            )
            self._commit()
        except (sqlite3.Error, OverflowError) as e:
            raise StorageError(f"Failed to log project update: {e}") from e
        with self._read_guard("read project log"):
            row = self._conn.execute(
                "SELECT * FROM project_updates WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return _row_to_update(row)

    def list_project_updates(self, project_id: int) -> "UpdateList":
        with self._read_guard("read project log"):
            rows = self._conn.execute(
                "SELECT * FROM project_updates WHERE project_id = ? "
                "ORDER BY created_at DESC, id DESC",
                (project_id,),
            ).fetchall()
            return [_row_to_update(r) for r in rows]
