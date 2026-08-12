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


class TestProjectNameNormalization:
    def test_multiline_project_name_collapsed(self, storage: SqliteStorage) -> None:
        from todo.application.commands import add_project

        project = add_project(storage, "sprint\n42")
        assert project.name == "sprint 42"

    def test_project_name_stripped(self, storage: SqliteStorage) -> None:
        from todo.application.commands import add_project
        from todo.exceptions import DuplicateProjectError

        add_project(storage, "work")
        with pytest.raises(DuplicateProjectError):
            add_project(storage, "  work ")

    def test_rename_normalized_too(self, storage: SqliteStorage) -> None:
        from todo.application.commands import add_project, edit_project

        project = add_project(storage, "old")
        renamed = edit_project(storage, project.id, name="new\nname")
        assert renamed.name == "new name"


class TestDeleteUnblockWarning:
    def test_rm_blocker_warns_about_unblocked(self, cli: CliRunner) -> None:
        """Deleting a blocker unblocks dependents via cascade; it must warn
        exactly like completing the blocker does."""
        cli.invoke(main, ["add", "Blocker"])
        cli.invoke(main, ["add", "Waiting"])
        cli.invoke(main, ["block", "2", "1"])
        result = cli.invoke(main, ["rm", "1"])
        assert result.exit_code == 0
        assert "#2 Waiting is now unblocked" in result.stderr

    def test_rm_non_blocker_does_not_warn(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Solo"])
        result = cli.invoke(main, ["rm", "1"])
        assert result.exit_code == 0
        assert "unblocked" not in result.stderr


class TestEmptyProjectRef:
    def test_add_with_empty_project_errors_like_edit(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["add", "Task", "--project", ""])
        assert result.exit_code == 1
        assert "not found" in result.stderr

    def test_list_with_empty_project_errors(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["list", "--project", ""])
        assert result.exit_code == 1
        assert "not found" in result.stderr


class TestTagDeduplication:
    def test_duplicate_tags_deduped_on_add(self, storage: SqliteStorage) -> None:
        item = add_todo(storage, "x", tags=["a", "a", "b", " a "])
        assert item.tags == ["a", "b"]

    def test_duplicate_tags_deduped_on_edit(self, storage: SqliteStorage) -> None:
        add_todo(storage, "x")
        result = edit_todo(storage, 1, tags=["dup", "dup"])
        assert result.item.tags == ["dup"]

    def test_tag_counts_count_items_not_occurrences(
        self, storage: SqliteStorage
    ) -> None:
        from todo.application.queries import count_tags

        add_todo(storage, "x", tags=["a", "a"])
        assert count_tags(storage) == [("a", 1)]


class TestProjectDescriptionNormalization:
    def test_multiline_description_collapsed_on_add(
        self, storage: SqliteStorage
    ) -> None:
        """project list is one row per project — a newline in the
        description would break that contract just like one in the name."""
        from todo.application.commands import add_project

        project = add_project(storage, "p", description="line1\nline2")
        assert project.description == "line1 line2"

    def test_multiline_description_collapsed_on_edit(
        self, storage: SqliteStorage
    ) -> None:
        from todo.application.commands import add_project, edit_project

        project = add_project(storage, "p")
        updated = edit_project(storage, project.id, description="a\n\nb")
        assert updated.description == "a b"

    def test_empty_description_still_allowed(self, storage: SqliteStorage) -> None:
        from todo.application.commands import add_project

        assert add_project(storage, "p", description="").description == ""


class TestProjectLogNormalization:
    def test_empty_log_body_rejected(self, storage: SqliteStorage) -> None:
        """An empty update would render as a dangling timestamp-only log
        line the user can never remove."""
        from todo.application.commands import add_project, log_project_update

        project = add_project(storage, "p")
        with pytest.raises(ValueError, match="[Bb]ody|[Uu]pdate"):
            log_project_update(storage, project.id, "   ")

    def test_multiline_log_body_collapsed(self, storage: SqliteStorage) -> None:
        from todo.application.commands import add_project, log_project_update

        project = add_project(storage, "p")
        update = log_project_update(storage, project.id, "shipped\nthe thing")
        assert update.body == "shipped the thing"

    def test_cli_empty_log_errors_cleanly(self, cli: CliRunner) -> None:
        cli.invoke(main, ["project", "add", "p"])
        result = cli.invoke(main, ["project", "log", "p", "   "])
        assert result.exit_code != 0
