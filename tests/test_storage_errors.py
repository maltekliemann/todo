"""Every storage failure must surface as StorageError, never a raw
sqlite3/OS exception: the CLI's _SafeGroup and the TUI's TodoError guards
only catch the domain hierarchy."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.factory import (
    NewItem,
    add_blocker,
    add_project,
    add_todo,
    log_project_update,
)
from todo.adapters.sqlite_dependency_store import SqliteDependencyStore
from todo.adapters.sqlite_item_store import SqliteItemStore
from todo.adapters.sqlite_project_log_store import SqliteProjectLogStore
from todo.adapters.sqlite_project_store import SqliteProjectStore
from todo.domain.body import Body
from todo.domain.item_filter import ItemFilter
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.project_filter import ProjectFilter
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName
from todo.domain.status import Status
from todo.domain.title import Title
from todo.domain.todo_item import TodoItem
from todo.exceptions import StorageError, TodoError
from todo.infra.cli.main import main


@dataclass
class _Stores:
    items: SqliteItemStore
    projects: SqliteProjectStore
    log: SqliteProjectLogStore
    dependencies: SqliteDependencyStore
    item_id: ItemId
    project_id: ProjectId


def _broken_stores(tmp_path: Path) -> _Stores:
    """Stores whose connections die mid-session (simulates corruption)."""
    path = tmp_path / "db.db"
    items = SqliteItemStore(path)
    projects = SqliteProjectStore(path)
    log = SqliteProjectLogStore(path)
    dependencies = SqliteDependencyStore(path)
    item = add_todo(items, NewItem(title="x"))
    project = add_project(projects, "p", description="")
    for store in (items, projects, log, dependencies):
        store.close()
    return _Stores(items, projects, log, dependencies, item.id, project.id)


_READ_CALLS: dict[str, Callable[[_Stores], object]] = {
    "get": lambda s: s.items.get(s.item_id),
    "find": lambda s: s.items.find(ItemFilter()),
    "exists": lambda s: s.items.exists(s.item_id),
    "done_since": lambda s: s.items.done_since(datetime.now(tz=timezone.utc)),
    "done_ids": lambda s: s.items.done_ids(),
    "tags_of_every_item": lambda s: s.items.tags_of_every_item(),
    "counts_by_project": lambda s: s.items.counts_by_project(),
    "get_project": lambda s: s.projects.get(s.project_id),
    "get_project_by_name": lambda s: s.projects.get_by_name(ProjectName("p")),
    "find_projects": lambda s: s.projects.find(ProjectFilter()),
    "load_dependencies": lambda s: s.dependencies.load(),
    "entries_for": lambda s: s.log.entries_for(s.project_id),
}


class TestReadPathErrorWrapping:
    @pytest.mark.parametrize("name", sorted(_READ_CALLS))
    def test_read_raises_storage_error_when_connection_breaks(
        self, tmp_path: Path, name: str
    ) -> None:
        stores = _broken_stores(tmp_path)
        with pytest.raises(StorageError):
            _READ_CALLS[name](stores)


class TestInitErrorWrapping:
    def test_db_path_under_a_file_raises_storage_error(self, tmp_path: Path) -> None:
        """mkdir failures (bad TODO_DB) must be StorageError so both
        frontends show a clean message instead of a traceback."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        with pytest.raises(StorageError):
            SqliteItemStore(blocker / "sub" / "todos.db")

    def test_cli_reports_bad_db_path_cleanly(self, tmp_path: Path) -> None:
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["list"],
            env={"TODO_DB": str(blocker / "sub" / "todos.db")},
        )
        assert result.exit_code == 1
        assert "Database error:" in result.stderr
        assert "Traceback" not in result.stderr


class TestOversizedIds:
    """Ids beyond SQLite's 64-bit integer range raise OverflowError at bind
    time — outside the sqlite3.Error hierarchy, so they slipped past every
    guard. They must surface as the domain hierarchy like any other bad id."""

    def test_get_with_oversized_id_raises_domain_error(
        self, items: SqliteItemStore
    ) -> None:
        with pytest.raises(TodoError):
            items.get(ItemId(10**20))

    def test_save_with_oversized_id_raises_domain_error(
        self, items: SqliteItemStore
    ) -> None:
        now = datetime.now(tz=timezone.utc)
        oversized = TodoItem(
            id=ItemId(10**20),
            title=Title("x"),
            body=Body(""),
            priority=Priority.MEDIUM,
            status=Status.TODO,
            created_at=now,
            updated_at=now,
        )
        with pytest.raises(TodoError):
            items.save(oversized)

    def test_blocking_an_oversized_id_raises_domain_error(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        add_todo(items, NewItem(title="a"))
        with pytest.raises(TodoError):
            add_blocker(items, dependencies, ItemId(1), [ItemId(10**20)])

    def test_cli_show_oversized_id_errors_cleanly(self, tmp_path: Path) -> None:
        runner = CliRunner()
        env = {"TODO_DB": str(tmp_path / "t.db")}
        runner.invoke(main, ["add", "x"], env=env)
        result = runner.invoke(main, ["show", "99999999999999999999"], env=env)
        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert "Traceback" not in result.stderr


class TestParseSinceOverflow:
    def test_huge_since_amount_raises_value_error(self) -> None:
        from todo.infra.cli.main import _parse_since_or_exit as parse_since

        for value in ("9999999 days", "99999999999 days", "999999999999999 weeks"):
            with pytest.raises(ValueError, match="Cannot parse|too large"):
                parse_since(value)

    def test_cli_summary_huge_since_errors_cleanly(self, tmp_path: Path) -> None:
        runner = CliRunner()
        env = {"TODO_DB": str(tmp_path / "t.db")}
        result = runner.invoke(main, ["summary", "--since", "9999999 days"], env=env)
        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)
        assert "Traceback" not in result.stderr


class TestInitSqliteErrorWrapping:
    def test_corrupt_db_file_raises_storage_error(self, tmp_path: Path) -> None:
        """Init-time sqlite failures (corrupt file) are part of the same
        wrapping contract as reads and writes."""
        bad = tmp_path / "corrupt.db"
        bad.write_bytes(b"this is not a sqlite database at all --------")
        with pytest.raises(StorageError):
            SqliteItemStore(bad)


class TestConnectErrorWrapping:
    def test_db_path_is_a_directory_raises_storage_error(self, tmp_path: Path) -> None:
        """sqlite3.connect failures are init-time database failures like
        any other and must wrap as StorageError."""
        with pytest.raises(StorageError):
            SqliteItemStore(tmp_path)  # the path IS a directory

    def test_project_log_read_is_wrapped(
        self, projects: SqliteProjectStore, log: SqliteProjectLogStore
    ) -> None:
        """Reading a project's log is a storage read like any other."""
        project = add_project(projects, "p", description="")
        log_project_update(projects, log, project.id, "hello")
        real_conn = log._conn

        class _Proxy:
            def __getattr__(self, name: str) -> object:
                return getattr(real_conn, name)

            def execute(self, sql: str, *args: object) -> object:
                if sql.startswith("SELECT * FROM project_updates"):
                    raise sqlite3.OperationalError("disk I/O error")
                return real_conn.execute(sql, *args)

        log._conn = _Proxy()  # type: ignore[assignment]
        with pytest.raises(StorageError):
            log.entries_for(project.id)


class TestUndecodableRowWrapping:
    """A row the adapter cannot decode is a storage failure like any
    other: it must surface as StorageError, not a raw ValueError that
    both frontends' guards miss."""

    def _poison(self, tmp_path: Path, column: str, value: str) -> Path:
        path = tmp_path / "db.db"
        items = SqliteItemStore(path)
        add_todo(items, NewItem(title="x"))
        items.close()
        conn = sqlite3.connect(str(path))
        conn.execute(f"UPDATE todos SET {column} = ?", (value,))
        conn.commit()
        conn.close()
        return path

    def test_bad_priority_enum_raises_storage_error(self, tmp_path: Path) -> None:
        path = self._poison(tmp_path, "priority", "p1")
        with pytest.raises(StorageError):
            SqliteItemStore(path).find(ItemFilter())

    def test_bad_timestamp_raises_storage_error(self, tmp_path: Path) -> None:
        path = self._poison(tmp_path, "created_at", "not-a-timestamp")
        with pytest.raises(StorageError):
            SqliteItemStore(path).get(ItemId(1))

    def test_bad_project_row_raises_storage_error(self, tmp_path: Path) -> None:
        path = tmp_path / "db.db"
        projects = SqliteProjectStore(path)
        project = add_project(projects, "p", description="")
        projects.close()
        conn = sqlite3.connect(str(path))
        conn.execute("UPDATE projects SET status = ?", ("bogus",))
        conn.commit()
        conn.close()
        with pytest.raises(StorageError):
            SqliteProjectStore(path).get(project.id)

    def test_cli_reports_undecodable_row_cleanly(self, tmp_path: Path) -> None:
        path = self._poison(tmp_path, "priority", "p1")
        runner = CliRunner()
        result = runner.invoke(main, ["list"], env={"TODO_DB": str(path)})
        assert result.exit_code == 1
        assert "Database error:" in result.stderr
        assert "Traceback" not in result.stderr
