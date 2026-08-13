"""Titles are single-line and tags collapse their whitespace — enforced
at the application boundary so every storage/render format can rely on
it."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from todo.adapters.sqlite_dependency_store import SqliteDependencyStore
from todo.adapters.sqlite_item_store import SqliteItemStore
from todo.adapters.sqlite_project_log_store import SqliteProjectLogStore
from todo.adapters.sqlite_project_store import SqliteProjectStore
from todo.application.commands import add_todo, edit_todo
from todo.infra.cli.main import main


class TestTitleNormalization:
    def test_newlines_collapsed_on_add(self, items: SqliteItemStore) -> None:
        item = add_todo(items, "line one\nline two\r\nline three")
        assert item.title == "line one line two line three"

    def test_newlines_collapsed_on_edit(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        add_todo(items, "ok")
        result = edit_todo(items, dependencies, 1, title="new\ntitle")
        assert result.item.title == "new title"

    def test_cli_add_multiline_title(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Fix login\nsee ticket 42"])
        data = json.loads(cli.invoke(main, ["show", "1", "--json"]).output)
        assert "\n" not in data["title"]
        assert data["title"] == "Fix login see ticket 42"

    def test_empty_title_rejected(self, items: SqliteItemStore) -> None:
        with pytest.raises(ValueError, match="[Tt]itle"):
            add_todo(items, "   \n  ")

    def test_plain_list_one_line_per_item(
        self, items: SqliteItemStore, cli: CliRunner
    ) -> None:
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
    def test_a_comma_tag_round_trips(self, items: SqliteItemStore) -> None:
        """Tags are rows, so a comma is just a character in one."""
        item = add_todo(items, "Task", tags=frozenset({"a,b"}))
        assert item.tags == frozenset({"a,b"})
        assert items.get(item.id).tags == frozenset({"a,b"})

    def test_a_comma_tag_round_trips_through_edit(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        add_todo(items, "Task")
        result = edit_todo(items, dependencies, 1, tags=frozenset({"x,y"}))
        assert result.item.tags == frozenset({"x,y"})

    def test_cli_accepts_a_comma_tag(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["add", "Task", "-t", "a,b", "--json"])
        assert result.exit_code == 0
        assert json.loads(result.output)["tags"] == ["a,b"]

    def test_whitespace_tag_normalized(self, items: SqliteItemStore) -> None:
        item = add_todo(items, "Task", tags=frozenset({"  spaced  ", "ok"}))
        assert item.tags == frozenset({"spaced", "ok"})

    def test_no_phantom_tags_roundtrip(self, cli: CliRunner) -> None:
        """The original failure: 'a,b' silently became two tags."""
        cli.invoke(main, ["add", "Task", "-t", "real"])
        data = json.loads(cli.invoke(main, ["tags", "--json"]).output)
        assert data == [{"tag": "real", "count": 1}]


class TestProjectNameNormalization:
    def test_multiline_project_name_collapsed(
        self, projects: SqliteProjectStore
    ) -> None:
        from todo.application.commands import add_project

        project = add_project(projects, "sprint\n42")
        assert project.name == "sprint 42"

    def test_project_name_stripped(self, projects: SqliteProjectStore) -> None:
        from todo.application.commands import add_project
        from todo.exceptions import DuplicateProjectError

        add_project(projects, "work")
        with pytest.raises(DuplicateProjectError):
            add_project(projects, "  work ")

    def test_rename_normalized_too(self, projects: SqliteProjectStore) -> None:
        from todo.application.commands import add_project, edit_project

        project = add_project(projects, "old")
        renamed = edit_project(projects, project.id, name="new\nname")
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
    def test_duplicate_tags_deduped_on_add(self, items: SqliteItemStore) -> None:
        item = add_todo(items, "x", tags=frozenset({"a", "a", "b", " a "}))
        assert item.tags == frozenset({"a", "b"})

    def test_duplicate_tags_deduped_on_edit(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        add_todo(items, "x")
        result = edit_todo(items, dependencies, 1, tags=frozenset({"dup", "dup"}))
        assert result.item.tags == frozenset({"dup"})

    def test_tag_counts_count_items_not_occurrences(
        self, items: SqliteItemStore
    ) -> None:
        from todo.application.queries import count_tags

        add_todo(items, "x", tags=frozenset({"a", "a"}))
        assert count_tags(items) == [("a", 1)]


class TestProjectDescriptionNormalization:
    def test_multiline_description_collapsed_on_add(
        self, projects: SqliteProjectStore
    ) -> None:
        """project list is one row per project — a newline in the
        description would break that contract just like one in the name."""
        from todo.application.commands import add_project

        project = add_project(projects, "p", description="line1\nline2")
        assert project.description == "line1 line2"

    def test_multiline_description_collapsed_on_edit(
        self, projects: SqliteProjectStore
    ) -> None:
        from todo.application.commands import add_project, edit_project

        project = add_project(projects, "p")
        updated = edit_project(projects, project.id, description="a\n\nb")
        assert updated.description == "a b"

    def test_empty_description_still_allowed(
        self, projects: SqliteProjectStore
    ) -> None:
        from todo.application.commands import add_project

        assert add_project(projects, "p", description="").description == ""


class TestProjectLogNormalization:
    def test_empty_log_body_rejected(
        self, projects: SqliteProjectStore, log: SqliteProjectLogStore
    ) -> None:
        """An empty update would render as a dangling timestamp-only log
        line the user can never remove."""
        from todo.application.commands import add_project, log_project_update

        project = add_project(projects, "p")
        with pytest.raises(ValueError, match="[Bb]ody|[Uu]pdate"):
            log_project_update(log, project.id, "   ")

    def test_multiline_log_body_collapsed(
        self, projects: SqliteProjectStore, log: SqliteProjectLogStore
    ) -> None:
        from todo.application.commands import add_project, log_project_update

        project = add_project(projects, "p")
        update = log_project_update(log, project.id, "shipped\nthe thing")
        assert update.body == "shipped the thing"

    def test_cli_empty_log_errors_cleanly(
        self, log: SqliteProjectLogStore, cli: CliRunner
    ) -> None:
        cli.invoke(main, ["project", "add", "p"])
        result = cli.invoke(main, ["project", "log", "add", "p", "   "])
        assert result.exit_code != 0


class TestTagFilterNormalization:
    def test_cli_tag_filter_with_incidental_whitespace_matches(
        self, items: SqliteItemStore, cli: CliRunner
    ) -> None:
        """Write path strips tags before storing; the read path must apply
        the same normalization or the same input silently matches nothing."""
        cli.invoke(main, ["add", "x", "-t", "foo"])
        result = cli.invoke(main, ["list", "-t", "foo "])
        assert "x" in result.output
        assert "No items." not in result.output

    def test_query_layer_normalizes_filter_tags(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        from todo.application.queries import list_todos

        add_todo(items, "x", tags=frozenset({"foo"}))
        assert [
            i.title for i in list_todos(items, dependencies, tags=frozenset({" foo "}))
        ] == ["x"]


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

    def test_a_comma_tag_filter_matches_that_exact_tag(self, cli: CliRunner) -> None:
        """It is one tag, not two: an item tagged 'a' and 'b' is not it."""
        cli.invoke(main, ["add", "separate", "-t", "a", "-t", "b"])
        cli.invoke(main, ["add", "joined", "-t", "a,b"])
        result = cli.invoke(main, ["list", "-t", "a,b"])
        assert "joined" in result.output
        assert "separate" not in result.output

    def test_query_layer_rejects_a_blank_filter(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        from todo.application.queries import list_todos

        add_todo(items, "x", tags=frozenset({"a"}))
        with pytest.raises(ValueError, match="[Tt]ag"):
            list_todos(items, dependencies, tags=frozenset({" "}))


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

    def test_padded_numeric_ref_resolves_as_id(
        self, projects: SqliteProjectStore
    ) -> None:
        from todo.application.commands import add_project
        from todo.application.queries import resolve_project

        project = add_project(projects, "anything")
        assert resolve_project(projects, f" {project.id} ").id == project.id


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


class TestTagInputConvention:
    """One box, commas between, is the TUI's way of taking several tags.
    It is a convention of that widget and of nothing else — the store
    keeps tags as rows, and a tag may contain a comma."""

    def test_the_tui_field_splits_the_same_way(self) -> None:
        """Different layer, same convention: one box, commas between."""
        from todo.tui.tag_input import parse_tag_input

        assert parse_tag_input(" a , ,b ") == ["a", "b"]
        assert parse_tag_input("") == []


class TestTagWritePathParity:
    """The write path must apply the same rules the read path enforces —
    the copy that loses data is the one that must not be lenient."""

    def test_empty_tag_flag_rejected_not_silent_wipe(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "keep tags", "-t", "work", "-t", "urgent"])
        result = cli.invoke(main, ["edit", "1", "-t", ""])
        assert result.exit_code == 1
        data = json.loads(cli.invoke(main, ["show", "1", "--json"]).output)
        assert data["tags"] == ["urgent", "work"]  # nothing lost (a set, sorted)

    def test_empty_tag_rejected_on_add(self, items: SqliteItemStore) -> None:
        with pytest.raises(ValueError, match="[Tt]ag"):
            add_todo(items, "x", tags=frozenset({"ok", "  "}))

    def test_clearing_tags_still_possible_with_empty_list(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        """An explicit empty list still clears — only blank strings error."""
        from todo.application.commands import edit_todo

        add_todo(items, "x", tags=frozenset({"work"}))
        assert (
            edit_todo(items, dependencies, 1, tags=frozenset()).item.tags == frozenset()
        )

    def test_tag_with_newline_normalized_to_one_line(
        self, items: SqliteItemStore
    ) -> None:
        """Tags share the single_line contract of every other field, or
        plain output stops being one line per field."""
        item = add_todo(items, "x", tags=frozenset({"urgent\nreview"}))
        assert item.tags == frozenset({"urgent review"})

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

    def test_none_is_a_reserved_tag_name(self, items: SqliteItemStore) -> None:
        """Reserved so a real tag can never be shadowed by the sentinel."""
        with pytest.raises(ValueError, match="reserved"):
            add_todo(items, "x", tags=frozenset({"none"}))

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

    def test_stored_form_matches_write_path_form(self, items: SqliteItemStore) -> None:
        """What comes back is what Tag made of what went in."""
        item = add_todo(items, "x", tags=frozenset({"my  tag", "a\tb"}))
        assert items.get(item.id).tags == frozenset({"my tag", "a b"})
