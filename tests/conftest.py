from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from todo.adapters.sqlite_dependency_store import SqliteDependencyStore
from todo.adapters.sqlite_item_store import SqliteItemStore
from todo.adapters.sqlite_project_log_store import SqliteProjectLogStore
from todo.adapters.sqlite_project_store import SqliteProjectStore
from todo.infra.cli.main import main


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture(autouse=True)
def _todo_db(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test runs against its own temporary database.

    Autouse and unconditional: nothing in the suite may reach the real
    one, whether it builds a store by hand or goes through the config.
    """
    monkeypatch.setenv("TODO_DB", str(db_path))


@pytest.fixture()
def items(db_path: Path) -> SqliteItemStore:
    return SqliteItemStore(db_path)


@pytest.fixture()
def projects(db_path: Path) -> SqliteProjectStore:
    return SqliteProjectStore(db_path)


@pytest.fixture()
def dependencies(db_path: Path) -> SqliteDependencyStore:
    return SqliteDependencyStore(db_path)


@pytest.fixture()
def log(db_path: Path) -> SqliteProjectLogStore:
    return SqliteProjectLogStore(db_path)


@pytest.fixture()
def cli(db_path: Path) -> CliRunner:
    """CliRunner with TODO_DB pointed at a temp database."""
    runner = CliRunner(env={"TODO_DB": str(db_path)})
    return runner


@pytest.fixture()
def invoke(cli: CliRunner):
    """Shorthand: invoke(args_string) -> click.Result."""

    def _invoke(args: str) -> object:
        return cli.invoke(main, args.split())

    return _invoke
