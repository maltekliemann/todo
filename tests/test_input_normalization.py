"""Titles are single-line and tags are comma-free — enforced at the
application boundary so every storage/render format can rely on it."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import add_todo, edit_todo
from todo.infra.cli.main import main


class TestTitleNormalization:
    def test_newlines_collapsed_on_add(self, storage: SqliteStorage) -> None:
        item = add_todo(storage, "line one\nline two\r\nline three")
        assert item.title == "line one line two line three"

    def test_newlines_collapsed_on_edit(self, storage: SqliteStorage) -> None:
        add_todo(storage, "ok")
        result = edit_todo(storage, 1, title="new\ntitle")
        assert result.item.title == "new title"

    def test_cli_add_multiline_title(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Fix login\nsee ticket 42"])
        data = json.loads(cli.invoke(main, ["show", "1", "--json"]).output)
        assert "\n" not in data["title"]
        assert data["title"] == "Fix login see ticket 42"

    def test_empty_title_rejected(self, storage: SqliteStorage) -> None:
        with pytest.raises(ValueError, match="[Tt]itle"):
            add_todo(storage, "   \n  ")

    def test_plain_list_one_line_per_item(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "multi\nline"])
        cli.invoke(main, ["add", "single"])
        result = cli.invoke(main, ["list"])
        # Item rows are indented; the "N items" footer is not.
        item_lines = [
            ln
            for ln in result.output.splitlines()
            if ln.startswith("  ") and ln.strip()
        ]
        assert len(item_lines) == 2
        assert any("multi line" in ln for ln in item_lines)


class TestTagValidation:
    def test_comma_tag_rejected_on_add(self, storage: SqliteStorage) -> None:
        with pytest.raises(ValueError, match="comma"):
            add_todo(storage, "Task", tags=["a,b"])

    def test_comma_tag_rejected_on_edit(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task")
        with pytest.raises(ValueError, match="comma"):
            edit_todo(storage, 1, tags=["x,y"])

    def test_cli_comma_tag_errors_cleanly(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["add", "Task", "-t", "a,b"])
        assert result.exit_code == 1
        assert "comma" in result.stderr

    def test_whitespace_tag_normalized(self, storage: SqliteStorage) -> None:
        item = add_todo(storage, "Task", tags=["  spaced  ", "ok"])
        assert item.tags == ["spaced", "ok"]

    def test_no_phantom_tags_roundtrip(self, cli: CliRunner) -> None:
        """The original failure: 'a,b' silently became two tags."""
        cli.invoke(main, ["add", "Task", "-t", "real"])
        data = json.loads(cli.invoke(main, ["tags", "--json"]).output)
        assert data == [{"tag": "real", "count": 1}]
