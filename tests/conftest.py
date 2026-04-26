from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from todo.adapters.sqlite_storage import SqliteStorage
from todo.infra.cli.main import main


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture()
def storage(db_path: Path) -> SqliteStorage:
    return SqliteStorage(db_path)


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
