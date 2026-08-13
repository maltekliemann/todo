"""Every storage failure must surface as StorageError, never a raw
sqlite3/OS exception: the CLI's _SafeGroup and the TUI's TodoError guards
only catch the domain hierarchy."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner

from todo.adapters.sqlite_storage import SqliteStorage
from todo.exceptions import StorageError
from todo.infra.cli.main import main


def _broken_storage(tmp_path: Path) -> tuple[SqliteStorage, int, int]:
    """A storage whose connection dies mid-session (simulates corruption)."""
    storage = SqliteStorage(tmp_path / "db.db")
    item = storage.add("x")
    project = storage.add_project("p")
    storage._conn.close()
    return storage, item.id, project.id


_READ_CALLS: dict[str, Callable[[SqliteStorage, int, int], object]] = {
    "get": lambda s, i, p: s.get(i),
    "list": lambda s, i, p: s.list(),
    "done_since": lambda s, i, p: s.done_since(__import__("datetime").datetime.now()),
    "data_version": lambda s, i, p: s.data_version(),
    "get_project": lambda s, i, p: s.get_project(p),
    "get_project_by_name": lambda s, i, p: s.get_project_by_name("p"),
    "list_projects": lambda s, i, p: s.list_projects(),
    "project_counts": lambda s, i, p: s.project_counts(),
    "dependency_edges": lambda s, i, p: s.dependency_edges(),
    "item_tags": lambda s, i, p: s.item_tags(),
    "list_project_updates": lambda s, i, p: s.list_project_updates(p),
}


class TestReadPathErrorWrapping:
    @pytest.mark.parametrize("name", sorted(_READ_CALLS))
    def test_read_raises_storage_error_when_connection_breaks(
        self, tmp_path: Path, name: str
    ) -> None:
        storage, item_id, project_id = _broken_storage(tmp_path)
        with pytest.raises(StorageError):
            _READ_CALLS[name](storage, item_id, project_id)


class TestInitErrorWrapping:
    def test_db_path_under_a_file_raises_storage_error(self, tmp_path: Path) -> None:
        """mkdir failures (bad TODO_DB) must be StorageError so both
        frontends show a clean message instead of a traceback."""
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        with pytest.raises(StorageError):
            SqliteStorage(blocker / "sub" / "todos.db")

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

    def test_get_with_oversized_id_raises_domain_error(self, tmp_path: Path) -> None:
        from todo.exceptions import TodoError

        storage = SqliteStorage(tmp_path / "db.db")
        with pytest.raises(TodoError):
            storage.get(10**20)
        storage.close()

    def test_update_with_oversized_id_raises_domain_error(self, tmp_path: Path) -> None:
        from todo.exceptions import TodoError

        storage = SqliteStorage(tmp_path / "db.db")
        with pytest.raises(TodoError):
            storage.update(10**20, title="x")
        storage.close()

    def test_add_blocker_with_oversized_id_raises_domain_error(
        self, tmp_path: Path
    ) -> None:
        from todo.exceptions import TodoError

        storage = SqliteStorage(tmp_path / "db.db")
        storage.add("a")
        with pytest.raises(TodoError):
            storage.add_blocker(1, 10**20)
        storage.close()

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
        from todo.application.queries import parse_since

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
            SqliteStorage(bad)


class TestConnectErrorWrapping:
    def test_db_path_is_a_directory_raises_storage_error(self, tmp_path: Path) -> None:
        """sqlite3.connect failures are init-time database failures like
        any other and must wrap as StorageError."""
        with pytest.raises(StorageError):
            SqliteStorage(tmp_path)  # the path IS a directory

    def test_project_log_readback_is_wrapped(self, tmp_path: Path) -> None:
        """The post-commit read-back in add_project_update is a storage
        read like any other."""
        import sqlite3

        storage = SqliteStorage(tmp_path / "db.db")
        project = storage.add_project("p")
        real_conn = storage._conn

        class _Proxy:
            def __getattr__(self, name: str) -> object:
                return getattr(real_conn, name)

            def execute(self, sql: str, *args: object) -> object:
                if sql.startswith("SELECT * FROM project_updates"):
                    raise sqlite3.OperationalError("disk I/O error")
                return real_conn.execute(sql, *args)

        storage._conn = _Proxy()  # type: ignore[assignment]
        with pytest.raises(StorageError):
            storage.add_project_update(project.id, "hello")


class TestUndecodableRowWrapping:
    """A row the adapter cannot decode is a storage failure like any
    other: it must surface as StorageError, not a raw ValueError that
    both frontends' guards miss."""

    def _poison(self, tmp_path: Path, column: str, value: str) -> SqliteStorage:
        storage = SqliteStorage(tmp_path / "db.db")
        storage.add("x")
        storage._conn.execute(f"UPDATE todos SET {column} = ?", (value,))
        storage._conn.commit()
        return storage

    def test_bad_priority_enum_raises_storage_error(self, tmp_path: Path) -> None:
        storage = self._poison(tmp_path, "priority", "p1")
        with pytest.raises(StorageError):
            storage.get(1)
        with pytest.raises(StorageError):
            storage.list()
        storage.close()

    def test_bad_timestamp_raises_storage_error(self, tmp_path: Path) -> None:
        storage = self._poison(tmp_path, "created_at", "not-a-timestamp")
        with pytest.raises(StorageError):
            storage.get(1)
        storage.close()

    def test_bad_project_row_raises_storage_error(self, tmp_path: Path) -> None:
        storage = SqliteStorage(tmp_path / "db.db")
        project = storage.add_project("p")
        storage._conn.execute("UPDATE projects SET status = 'bogus'")
        storage._conn.commit()
        with pytest.raises(StorageError):
            storage.get_project(project.id)
        with pytest.raises(StorageError):
            storage.list_projects(include_archived=True)
        storage.close()

    def test_cli_reports_undecodable_row_cleanly(self, tmp_path: Path) -> None:
        db = tmp_path / "t.db"
        storage = SqliteStorage(db)
        storage.add("x")
        storage._conn.execute("UPDATE todos SET priority = 'p1'")
        storage._conn.commit()
        storage.close()
        runner = CliRunner()
        result = runner.invoke(main, ["show", "1"], env={"TODO_DB": str(db)})
        assert result.exit_code == 1
        assert "Database error" in result.stderr
        assert "Traceback" not in result.stderr
