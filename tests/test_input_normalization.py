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


class TestTagFilterNormalization:
    def test_cli_tag_filter_with_incidental_whitespace_matches(
        self, cli: CliRunner
    ) -> None:
        """Write path strips tags before storing; the read path must apply
        the same normalization or the same input silently matches nothing."""
        cli.invoke(main, ["add", "x", "-t", "foo"])
        result = cli.invoke(main, ["list", "-t", "foo "])
        assert "x" in result.output
        assert "No items." not in result.output

    def test_query_layer_normalizes_filter_tags(self, storage: SqliteStorage) -> None:
        from todo.application.queries import list_todos

        add_todo(storage, "x", tags=["foo"])
        assert [i.title for i in list_todos(storage, tags=[" foo "])] == ["x"]


class TestTagFilterValidation:
    """A filter tag that can never match a stored tag must error, not
    silently run unfiltered or with adjacency semantics."""

    def test_blank_tag_filter_errors_instead_of_matching_everything(
        self, cli: CliRunner
    ) -> None:
        cli.invoke(main, ["add", "One", "-t", "work"])
        cli.invoke(main, ["add", "Two"])
        for value in ("", " "):
            result = cli.invoke(main, ["list", "--tag", value])
            assert result.exit_code == 1
            assert "Two" not in result.output

    def test_comma_tag_filter_errors_like_add_does(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "one", "-t", "a", "-t", "b", "-t", "c"])
        result = cli.invoke(main, ["list", "-t", "a,b"])
        assert result.exit_code == 1
        assert "comma" in (result.output + result.stderr)

    def test_query_layer_rejects_blank_and_comma_filters(
        self, storage: SqliteStorage
    ) -> None:
        from todo.application.queries import list_todos

        add_todo(storage, "x", tags=["a"])
        with pytest.raises(ValueError, match="[Tt]ag"):
            list_todos(storage, tags=[" "])
        with pytest.raises(ValueError, match="comma"):
            list_todos(storage, tags=["a,b"])


class TestParseSinceNegative:
    def test_negative_amount_rejected(self) -> None:
        from todo.application.queries import parse_since

        for value in ("-5 days", "-1 week", "0 days"):
            with pytest.raises(ValueError):
                parse_since(value)

    def test_cli_summary_negative_since_errors_cleanly(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["summary", "--since", "-5 days"])
        assert result.exit_code == 1
        assert result.exception is None or isinstance(result.exception, SystemExit)


class TestProjectRefNormalization:
    """Refs must resolve under the same normalization the write path
    applied — the exact string a project was created with always works."""

    def test_creation_string_resolves_after_normalization(self, cli: CliRunner) -> None:
        cli.invoke(main, ["project", "add", "my  project"])
        result = cli.invoke(main, ["project", "show", "my  project"])
        assert result.exit_code == 0
        assert "my project" in result.output

    def test_padded_ref_resolves(self, cli: CliRunner) -> None:
        cli.invoke(main, ["project", "add", "myproj"])
        assert cli.invoke(main, ["project", "show", " myproj "]).exit_code == 0
        result = cli.invoke(main, ["add", "x", "--project", "myproj "])
        assert result.exit_code == 0

    def test_padded_numeric_ref_resolves_as_id(self, storage: SqliteStorage) -> None:
        from todo.application.commands import add_project
        from todo.application.queries import resolve_project

        project = add_project(storage, "anything")
        assert resolve_project(storage, f" {project.id} ").id == project.id


class TestMatchingSemantics:
    def test_tag_filter_is_case_sensitive_like_tag_identity(
        self, cli: CliRunner
    ) -> None:
        """`todo tags` treats 'Work' and 'work' as distinct; the filter
        must agree instead of returning their union via LIKE."""
        cli.invoke(main, ["add", "lower", "-t", "work"])
        cli.invoke(main, ["add", "upper", "-t", "Work"])
        result = cli.invoke(main, ["list", "-t", "Work"])
        assert "upper" in result.output
        assert "lower" not in result.output

    def test_search_is_unicode_case_insensitive(self, cli: CliRunner) -> None:
        """The CLI search must match what the TUI's Python search matches."""
        cli.invoke(main, ["add", "Über uns"])
        result = cli.invoke(main, ["list", "--search", "über"])
        assert "Über uns" in result.output

    def test_search_still_matches_ascii_case_variants(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Fix Login Bug"])
        result = cli.invoke(main, ["list", "--search", "login"])
        assert "Fix Login Bug" in result.output

    def test_search_wildcards_stay_literal(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "done 100% sure"])
        cli.invoke(main, ["add", "unrelated"])
        result = cli.invoke(main, ["list", "--search", "100%"])
        assert "done 100% sure" in result.output
        assert "unrelated" not in result.output


class TestSharedNormalizationHelpers:
    """One implementation each for tag splitting and single-line collapse
    — the five hand-copies had already diverged."""

    def test_shared_tag_splitting(self) -> None:
        from todo.domain.tags import split_tags

        assert split_tags(" a , ,b, a ") == ["a", "b", "a"]
        assert split_tags("") == []

    def test_shared_single_line(self) -> None:
        from todo.domain.text import single_line

        assert single_line(" a\n\n b\tc ") == "a b c"

    def test_adapter_uses_shared_helpers(self) -> None:
        from pathlib import Path

        import todo.adapters.sqlite_storage as mod

        src = Path(str(mod.__file__)).read_text()
        assert "def _single_line" not in src
        assert "from todo.domain.text import" in src
        assert "from todo.domain.tags import" in src


class TestTagWritePathParity:
    """The write path must apply the same rules the read path enforces —
    the copy that loses data is the one that must not be lenient."""

    def test_empty_tag_flag_rejected_not_silent_wipe(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "keep tags", "-t", "work", "-t", "urgent"])
        result = cli.invoke(main, ["edit", "1", "-t", ""])
        assert result.exit_code == 1
        data = json.loads(cli.invoke(main, ["show", "1", "--json"]).output)
        assert data["tags"] == ["work", "urgent"]  # nothing lost

    def test_empty_tag_rejected_on_add(self, storage: SqliteStorage) -> None:
        with pytest.raises(ValueError, match="[Tt]ag"):
            add_todo(storage, "x", tags=["ok", "  "])

    def test_clearing_tags_still_possible_with_empty_list(
        self, storage: SqliteStorage
    ) -> None:
        """An explicit empty list still clears — only blank strings error."""
        from todo.application.commands import edit_todo

        add_todo(storage, "x", tags=["work"])
        assert edit_todo(storage, 1, tags=[]).item.tags == []

    def test_tag_with_newline_normalized_to_one_line(
        self, storage: SqliteStorage
    ) -> None:
        """Tags share the single_line contract of every other field, or
        plain output stops being one line per field."""
        item = add_todo(storage, "x", tags=["urgent\nreview"])
        assert item.tags == ["urgent review"]

    def test_multiline_tag_keeps_plain_output_one_line(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "x", "-t", "urgent\nreview"])
        result = cli.invoke(main, ["show", "1"])
        tag_lines = [ln for ln in result.output.splitlines() if ln.startswith("Tags:")]
        assert tag_lines == ["Tags: urgent review"]


class TestTagClearSentinel:
    """Round 11 made blank tags an error, which removed the only CLI way
    to clear tags. `none` is the clear-sentinel, matching --deadline and
    --project, and is not producible by an unset shell variable."""

    def test_tag_none_clears_tags(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "task one", "-t", "work", "-t", "home"])
        result = cli.invoke(main, ["edit", "1", "-t", "none"])
        assert result.exit_code == 0
        data = json.loads(cli.invoke(main, ["show", "1", "--json"]).output)
        assert data["tags"] == []

    def test_blank_tag_still_rejected(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "task", "-t", "work"])
        assert cli.invoke(main, ["edit", "1", "-t", ""]).exit_code == 1
        data = json.loads(cli.invoke(main, ["show", "1", "--json"]).output)
        assert data["tags"] == ["work"]

    def test_none_is_a_reserved_tag_name(self, storage: SqliteStorage) -> None:
        """Reserved so a real tag can never be shadowed by the sentinel."""
        with pytest.raises(ValueError, match="reserved"):
            add_todo(storage, "x", tags=["none"])

    def test_omitting_tag_flag_still_leaves_tags_untouched(
        self, cli: CliRunner
    ) -> None:
        cli.invoke(main, ["add", "task", "-t", "work"])
        cli.invoke(main, ["edit", "1", "--title", "renamed"])
        data = json.loads(cli.invoke(main, ["show", "1", "--json"]).output)
        assert data["tags"] == ["work"]


class TestTagFilterMatchesWritePath:
    def test_internal_whitespace_tag_matches_creating_string(
        self, cli: CliRunner
    ) -> None:
        """The write path applies single_line; the filter must too, or the
        exact string that created the tag matches nothing."""
        cli.invoke(main, ["add", "Task A", "-t", "deep  work"])
        result = cli.invoke(main, ["list", "-t", "deep  work"])
        assert "Task A" in result.output

    def test_migration_form_matches_write_path_form(self) -> None:
        from todo.adapters.sqlite_storage import _normalize_tag_string

        assert _normalize_tag_string("my  tag") == "my tag"
        assert _normalize_tag_string("a\tb, c") == "a b,c"
