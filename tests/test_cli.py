from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import block_todo, unblock_todo
from todo.domain.enums import Status
from todo.exceptions import DependencyError, NotFoundError
from todo.infra.cli.main import main


class TestAdd:
    def test_basic(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["add", "Buy milk"])
        assert result.exit_code == 0
        assert "Buy milk" in result.output

    def test_with_priority(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["add", "Urgent task", "-p", "urgent"])
        assert result.exit_code == 0
        assert "urgent" in result.output

    def test_with_deadline(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["add", "Ship it", "--deadline", "2099-12-31"])
        assert result.exit_code == 0
        assert "Dec 31" in result.output

    def test_with_tags(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["add", "Tagged", "-t", "foo", "-t", "bar"])
        assert result.exit_code == 0
        assert "foo" in result.output
        assert "bar" in result.output

    def test_with_status(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["add", "In backlog", "-s", "backlog"])
        assert result.exit_code == 0
        assert "backlog" in result.output

    def test_json_output(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["add", "JSON test", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["title"] == "JSON test"
        assert data["priority"] == "medium"
        assert data["status"] == "todo"


class TestList:
    def test_empty(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "No items" in result.output

    def test_shows_items(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Task A"])
        cli.invoke(main, ["add", "Task B"])
        result = cli.invoke(main, ["list"])
        assert result.exit_code == 0
        assert "Task A" in result.output
        assert "Task B" in result.output
        assert "2 items" in result.output

    def test_excludes_done_by_default(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Will finish"])
        cli.invoke(main, ["done", "1"])
        result = cli.invoke(main, ["list"])
        assert "Will finish" not in result.output

    def test_all_includes_done(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Will finish"])
        cli.invoke(main, ["done", "1"])
        result = cli.invoke(main, ["list", "--all"])
        assert "Will finish" in result.output

    def test_filter_by_status(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Backlog item", "-s", "backlog"])
        cli.invoke(main, ["add", "Todo item"])
        result = cli.invoke(main, ["list", "-s", "backlog"])
        assert "Backlog item" in result.output
        assert "Todo item" not in result.output

    def test_filter_by_priority(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Urgent one", "-p", "urgent"])
        cli.invoke(main, ["add", "Low one", "-p", "low"])
        result = cli.invoke(main, ["list", "-p", "urgent"])
        assert "Urgent one" in result.output
        assert "Low one" not in result.output

    def test_filter_by_tag(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Tagged", "-t", "deploy"])
        cli.invoke(main, ["add", "Untagged"])
        result = cli.invoke(main, ["list", "-t", "deploy"])
        assert "Tagged" in result.output
        assert "Untagged" not in result.output

    def test_json_output(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "A"])
        cli.invoke(main, ["add", "B"])
        result = cli.invoke(main, ["list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 2


class TestShow:
    def test_shows_detail(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Detailed task", "-b", "Some body text"])
        result = cli.invoke(main, ["show", "1"])
        assert result.exit_code == 0
        assert "Detailed task" in result.output

    def test_not_found(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["show", "999"])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_json_output(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "JSON show"])
        result = cli.invoke(main, ["show", "1", "--json"])
        data = json.loads(result.output)
        assert data["title"] == "JSON show"


class TestEdit:
    def test_change_priority(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Edit me"])
        result = cli.invoke(main, ["edit", "1", "-p", "urgent"])
        assert result.exit_code == 0
        assert "urgent" in result.output

    def test_change_title(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Old title"])
        result = cli.invoke(main, ["edit", "1", "--title", "New title"])
        assert result.exit_code == 0
        assert "New title" in result.output

    def test_set_deadline(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Need deadline"])
        result = cli.invoke(main, ["edit", "1", "--deadline", "2099-06-15"])
        assert result.exit_code == 0
        assert "Jun 15" in result.output

    def test_clear_deadline(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Has deadline", "--deadline", "2099-06-15"])
        result = cli.invoke(main, ["edit", "1", "--deadline", "none"])
        assert result.exit_code == 0
        # Verify deadline is gone
        show = cli.invoke(main, ["show", "1", "--json"])
        data = json.loads(show.output)
        assert data["deadline"] is None

    def test_not_found(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["edit", "999", "--title", "Nope"])
        assert result.exit_code == 1


class TestMv:
    def test_move_status(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Move me"])
        result = cli.invoke(main, ["mv", "1", "in-progress"])
        assert result.exit_code == 0
        assert "in-progress" in result.output

    def test_move_to_done_sets_done_at(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Finish me"])
        cli.invoke(main, ["mv", "1", "done"])
        result = cli.invoke(main, ["show", "1", "--json"])
        data = json.loads(result.output)
        assert data["done_at"] is not None

    def test_not_found(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["mv", "999", "todo"])
        assert result.exit_code == 1


class TestDone:
    def test_marks_done(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Complete me"])
        result = cli.invoke(main, ["done", "1"])
        assert result.exit_code == 0
        assert "done" in result.output

    def test_sets_done_at(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Complete me"])
        cli.invoke(main, ["done", "1"])
        result = cli.invoke(main, ["show", "1", "--json"])
        data = json.loads(result.output)
        assert data["done_at"] is not None
        assert data["status"] == "done"

    def test_not_found(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["done", "999"])
        assert result.exit_code == 1


class TestRm:
    def test_deletes(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Delete me"])
        result = cli.invoke(main, ["rm", "1"])
        assert result.exit_code == 0
        assert "Deleted" in result.output
        # Verify it's gone
        show = cli.invoke(main, ["show", "1"])
        assert show.exit_code == 1

    def test_not_found(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["rm", "999"])
        assert result.exit_code == 1


class TestSummary:
    def test_shows_completed(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Done task"])
        cli.invoke(main, ["done", "1"])
        result = cli.invoke(main, ["summary", "--since", "7 days"])
        assert result.exit_code == 0
        assert "Done task" in result.output
        assert "1 item completed" in result.output

    def test_empty_summary(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["summary", "--since", "7 days"])
        assert result.exit_code == 0
        assert "No items completed" in result.output

    def test_json_output(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Done"])
        cli.invoke(main, ["done", "1"])
        result = cli.invoke(main, ["summary", "--since", "7 days", "--json"])
        data = json.loads(result.output)
        assert data["count"] == 1
        assert len(data["items"]) == 1

    def test_bad_since_value(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["summary", "--since", "garbage"])
        assert result.exit_code == 1


class TestDeadlineWarnings:
    def test_overdue_shown(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Overdue task", "--deadline", "2020-01-01"])
        result = cli.invoke(main, ["show", "1", "--json"])
        data = json.loads(result.output)
        assert data["is_overdue"] is True

    def test_future_not_overdue(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Future task", "--deadline", "2099-12-31"])
        result = cli.invoke(main, ["show", "1", "--json"])
        data = json.loads(result.output)
        assert data["is_overdue"] is False

    def test_done_items_not_overdue(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Past but done", "--deadline", "2020-01-01"])
        cli.invoke(main, ["done", "1"])
        result = cli.invoke(main, ["show", "1", "--json"])
        data = json.loads(result.output)
        assert data["is_overdue"] is False


class TestBlock:
    def test_happy_path(self, invoke) -> None:
        invoke("add One")
        invoke("add Two")

        result = invoke("block 2 1")
        assert result.exit_code == 0

        r = invoke("show 2 --json")
        data = json.loads(r.output)
        assert data["blocked_by"] == [1]
        assert data["is_blocked"] is True

        r = invoke("show 1 --json")
        data = json.loads(r.output)
        assert data["blocking"] == [2]
        assert data["is_blocked"] is False

    def test_multiple_blockers_one_invocation(self, invoke) -> None:
        invoke("add One")
        invoke("add Two")
        invoke("add Three")

        result = invoke("block 3 1 2")
        assert result.exit_code == 0

        r = invoke("show 3 --json")
        data = json.loads(r.output)
        assert data["blocked_by"] == [1, 2]
        assert data["is_blocked"] is True

        assert json.loads(invoke("show 1 --json").output)["blocking"] == [3]
        assert json.loads(invoke("show 2 --json").output)["blocking"] == [3]

    def test_block_shows_relation_in_output(self, invoke) -> None:
        invoke("add Blocker")
        invoke("add Blocked")
        result = invoke("block 2 1")
        assert result.exit_code == 0
        assert "Blocked by: #1" in result.output

    def test_self_block_rejected(self, invoke) -> None:
        invoke("add Lonely")
        result = invoke("block 1 1")
        assert result.exit_code == 1
        assert "An item cannot block itself." in result.output

    def test_block_nonexistent_blocker(self, invoke) -> None:
        invoke("add Real item")
        result = invoke("block 1 999")
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_block_nonexistent_target(self, invoke) -> None:
        invoke("add Real item")
        result = invoke("block 999 1")
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_cycle_rejected(self, invoke) -> None:
        invoke("add One")
        invoke("add Two")
        assert invoke("block 2 1").exit_code == 0
        result = invoke("block 1 2")
        assert result.exit_code == 1
        assert "cycle" in result.output

    def test_transitive_cycle_rejected(self, invoke) -> None:
        invoke("add One")
        invoke("add Two")
        invoke("add Three")
        # 1 blocks 2, 2 blocks 3; adding 3 blocks 1 would form a cycle.
        assert invoke("block 2 1").exit_code == 0
        assert invoke("block 3 2").exit_code == 0
        result = invoke("block 1 3")
        assert result.exit_code == 1
        assert "cycle" in result.output

    def test_blocked_by_marked_done_flips_is_blocked(self, invoke) -> None:
        invoke("add Blocker")
        invoke("add Blocked")
        invoke("block 2 1")

        invoke("done 1")

        r = invoke("show 2 --json")
        data = json.loads(r.output)
        # Relation persists, but is_blocked flips to False once blocker is done.
        assert data["blocked_by"] == [1]
        assert data["is_blocked"] is False

    def test_delete_blocker_cascades(self, invoke) -> None:
        invoke("add Blocker")
        invoke("add Blocked")
        invoke("block 2 1")

        invoke("rm 1")

        r = invoke("show 2 --json")
        data = json.loads(r.output)
        assert data["blocked_by"] == []
        assert data["is_blocked"] is False

    def test_list_marks_blocked_item_json(self, invoke) -> None:
        invoke("add Blocker")
        invoke("add Blocked")
        invoke("block 2 1")

        r = invoke("list --json")
        items = {i["id"]: i for i in json.loads(r.output)}
        assert items[2]["is_blocked"] is True
        assert items[1]["is_blocked"] is False

    def test_plain_list_has_no_blocked_marker(self, invoke) -> None:
        """This test previously asserted the opposite: that plain output
        carried a 🚧 marker. That broke the machine-parseable contract of
        piped output, so the marker is Rich/TUI-only now."""
        invoke("add Blocker")
        invoke("add Blocked")
        invoke("block 2 1")

        r = invoke("list")
        assert r.exit_code == 0
        assert "\U0001f6a7" not in r.output
        assert "Blocked" in r.output


class TestUnblock:
    def test_unblock_removes_relation(self, invoke) -> None:
        invoke("add Blocker")
        invoke("add Blocked")
        invoke("block 2 1")

        result = invoke("unblock 2 1")
        assert result.exit_code == 0

        data = json.loads(invoke("show 2 --json").output)
        assert data["blocked_by"] == []
        assert data["is_blocked"] is False

        data = json.loads(invoke("show 1 --json").output)
        assert data["blocking"] == []

    def test_unblock_one_of_many(self, invoke) -> None:
        invoke("add One")
        invoke("add Two")
        invoke("add Three")
        invoke("block 3 1 2")

        result = invoke("unblock 3 1")
        assert result.exit_code == 0

        data = json.loads(invoke("show 3 --json").output)
        assert data["blocked_by"] == [2]
        assert data["is_blocked"] is True

    def test_unblock_nonexistent_target_fails(self, invoke) -> None:
        result = invoke("unblock 99 1")
        assert result.exit_code == 1
        assert "#99 not found" in result.stderr

    def test_unblock_non_blocker_fails(self, invoke) -> None:
        """Round-1 asserted silent success here; round-2 confirmed that hides
        typos (exit 0 while the real blocker stays). Now it errors, matching
        block's validation."""
        invoke("add One")
        invoke("add Two")
        result = invoke("unblock 1 2")
        assert result.exit_code == 1
        assert "not blocked by" in result.stderr

    def test_unblock_typo_keeps_real_blocker_and_errors(self, invoke) -> None:
        invoke("add One")
        invoke("add Two")
        invoke("block 2 1")
        result = invoke("unblock 2 99")
        assert result.exit_code == 1
        assert "not blocked by" in result.stderr
        assert json.loads(invoke("show 2 --json").output)["blocked_by"] == [1]

    def test_unblock_batch_all_or_nothing(self, invoke) -> None:
        invoke("add One")
        invoke("add Two")
        invoke("add Three")
        invoke("block 3 1 2")
        result = invoke("unblock 3 1 99")  # 99 is not a blocker
        assert result.exit_code == 1
        # Neither removal applied.
        assert json.loads(invoke("show 3 --json").output)["blocked_by"] == [1, 2]


class TestTagFilter:
    def test_multiple_tags_are_anded(self, invoke) -> None:
        invoke("add Both -t a -t b")
        invoke("add OnlyA -t a")
        invoke("add OnlyB -t b")
        data = json.loads(invoke("list -t a -t b --json").output)
        assert [i["title"] for i in data] == ["Both"]

    def test_single_tag_still_works(self, invoke) -> None:
        invoke("add Tagged -t a")
        invoke("add Other -t b")
        data = json.loads(invoke("list -t a --json").output)
        assert [i["title"] for i in data] == ["Tagged"]

    def test_tag_with_underscore_matches_literally(self, invoke) -> None:
        invoke("add A -t my_tag")
        invoke("add B -t mystag")
        data = json.loads(invoke("list -t my_tag --json").output)
        assert [i["title"] for i in data] == ["A"]


class TestSearch:
    def test_matches_title(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Fix the auth bug"])
        cli.invoke(main, ["add", "Unrelated"])
        result = cli.invoke(main, ["list", "--search", "auth", "--json"])
        data = json.loads(result.output)
        assert [i["title"] for i in data] == ["Fix the auth bug"]

    def test_matches_body(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Title", "--body", "mentions auth here"])
        cli.invoke(main, ["add", "Other"])
        result = cli.invoke(main, ["list", "--search", "auth", "--json"])
        data = json.loads(result.output)
        assert [i["title"] for i in data] == ["Title"]

    def test_case_insensitive(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Fix AUTH bug"])
        result = cli.invoke(main, ["list", "--search", "auth", "--json"])
        data = json.loads(result.output)
        assert len(data) == 1

    def test_percent_is_literal(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Reach 100% coverage"])
        cli.invoke(main, ["add", "Reach 100 coverage"])
        result = cli.invoke(main, ["list", "--search", "100%", "--json"])
        data = json.loads(result.output)
        assert [i["title"] for i in data] == ["Reach 100% coverage"]

    def test_underscore_is_literal(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "call foo_bar"])
        cli.invoke(main, ["add", "call fooXbar"])
        result = cli.invoke(main, ["list", "--search", "foo_bar", "--json"])
        data = json.loads(result.output)
        assert [i["title"] for i in data] == ["call foo_bar"]

    def test_unicode(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Küche aufräumen"])
        result = cli.invoke(main, ["list", "--search", "Küche", "--json"])
        data = json.loads(result.output)
        assert [i["title"] for i in data] == ["Küche aufräumen"]

    def test_no_match(self, invoke) -> None:
        invoke("add Something")
        data = json.loads(invoke("list --search nomatch --json").output)
        assert data == []

    def test_composes_with_tag(self, invoke) -> None:
        invoke("add Auth-work -t backend")
        invoke("add Auth-docs -t docs")
        data = json.loads(invoke("list --search Auth -t docs --json").output)
        assert [i["title"] for i in data] == ["Auth-docs"]


class TestDatabaseErrors:
    def test_corrupt_database_reports_cleanly(self, tmp_path, monkeypatch) -> None:
        """A broken database file must produce a clean error, not a traceback."""
        bad = tmp_path / "corrupt.db"
        bad.write_bytes(b"this is not a sqlite database at all --------")
        runner = CliRunner(env={"TODO_DB": str(bad)})
        result = runner.invoke(main, ["list"])
        assert result.exit_code == 1
        assert "Database error" in result.stderr
        assert result.exception is None or isinstance(result.exception, SystemExit)


class TestBadInput:
    def test_add_invalid_deadline_exits_cleanly(self, invoke) -> None:
        result = invoke("add Task -d garbage")
        assert result.exit_code == 1
        assert "Invalid deadline" in result.stderr
        assert result.exception is None or isinstance(result.exception, SystemExit)

    def test_edit_invalid_deadline_exits_cleanly(self, invoke) -> None:
        invoke("add Task")
        result = invoke("edit 1 -d 2026-13-45")
        assert result.exit_code == 1
        assert "Invalid deadline" in result.stderr


class TestProjectCli:
    def test_add_and_show(self, invoke) -> None:
        result = invoke("project add infra -D Infrastructure")
        assert result.exit_code == 0
        assert "infra" in result.output

        data = json.loads(invoke("project show infra --json").output)
        assert data["name"] == "infra"
        assert data["description"] == "Infrastructure"
        assert data["status"] == "active"
        assert data["items"] == []

    def test_show_by_id(self, invoke) -> None:
        invoke("project add infra")
        data = json.loads(invoke("project show 1 --json").output)
        assert data["name"] == "infra"

    def test_duplicate_add_fails(self, invoke) -> None:
        invoke("project add infra")
        result = invoke("project add infra")
        assert result.exit_code == 1
        assert "already exists" in result.stderr

    def test_show_unknown_fails(self, invoke) -> None:
        result = invoke("project show nope")
        assert result.exit_code == 1
        assert "not found" in result.stderr

    def test_list_with_counts(self, invoke) -> None:
        invoke("project add infra")
        invoke("add TaskA --project infra")
        invoke("add TaskB --project infra")
        invoke("done 2")
        data = json.loads(invoke("project list --json").output)
        assert len(data) == 1
        assert data[0]["open_count"] == 1
        assert data[0]["done_count"] == 1

    def test_archive_hides_from_default_list(self, invoke) -> None:
        invoke("project add old")
        invoke("project archive old")
        assert json.loads(invoke("project list --json").output) == []
        data = json.loads(invoke("project list --all --json").output)
        assert data[0]["status"] == "archived"

    def test_edit_renames(self, invoke) -> None:
        invoke("project add old")
        result = invoke("project edit old --name new")
        assert result.exit_code == 0
        assert json.loads(invoke("project show new --json").output)["name"] == "new"

    def test_rm_unassigns_items(self, invoke) -> None:
        invoke("project add doomed")
        invoke("add Task --project doomed")
        result = invoke("project rm doomed")
        assert result.exit_code == 0
        data = json.loads(invoke("show 1 --json").output)
        assert data["project_id"] is None
        assert data["project"] is None

    def test_add_todo_with_unknown_project_fails(self, invoke) -> None:
        result = invoke("add Task --project nope")
        assert result.exit_code == 1
        assert "not found" in result.stderr

    def test_assign_and_clear_via_edit(self, invoke) -> None:
        invoke("project add infra")
        invoke("add Task")
        data = json.loads(invoke("edit 1 --project infra --json").output)
        assert data["project"] == "infra"
        data = json.loads(invoke("edit 1 --project none --json").output)
        assert data["project"] is None

    def test_list_filters_by_project(self, invoke) -> None:
        invoke("project add infra")
        invoke("add In-project --project infra")
        invoke("add Outside")
        data = json.loads(invoke("list --project infra --json").output)
        assert [i["title"] for i in data] == ["In-project"]

    def test_project_log_appends_and_shows(self, cli: CliRunner) -> None:
        cli.invoke(main, ["project", "add", "infra"])
        result = cli.invoke(main, ["project", "log", "infra", "Kickoff complete"])
        assert result.exit_code == 0
        assert "Kickoff complete" in result.output

        cli.invoke(main, ["project", "log", "infra", "Second update"])
        data = json.loads(
            cli.invoke(main, ["project", "show", "infra", "--json"]).output
        )
        # Newest first.
        assert [u["body"] for u in data["updates"]] == [
            "Second update",
            "Kickoff complete",
        ]

    def test_project_log_unknown_project_fails(self, cli: CliRunner) -> None:
        result = cli.invoke(main, ["project", "log", "nope", "text"])
        assert result.exit_code == 1
        assert "not found" in result.stderr

    def test_project_rm_removes_its_log(self, cli: CliRunner) -> None:
        cli.invoke(main, ["project", "add", "doomed"])
        cli.invoke(main, ["project", "log", "doomed", "note"])
        cli.invoke(main, ["project", "rm", "doomed"])
        cli.invoke(main, ["project", "add", "doomed"])  # fresh, same name
        data = json.loads(
            cli.invoke(main, ["project", "show", "doomed", "--json"]).output
        )
        assert data["updates"] == []

    def test_project_named_none_is_rejected(self, invoke) -> None:
        """'none' is the clear-sentinel in --project; a project by that name
        would be unreachable from edit and could cause silent detachment."""
        result = invoke("project add none")
        assert result.exit_code == 1
        assert "reserved" in result.stderr
        result = invoke("project add NONE")
        assert result.exit_code == 1

    def test_project_rename_to_none_is_rejected(self, invoke) -> None:
        invoke("project add ok")
        result = invoke("project edit ok --name none")
        assert result.exit_code == 1
        assert "reserved" in result.stderr

    def test_show_displays_project(self, invoke) -> None:
        invoke("project add infra")
        invoke("add Task --project infra")
        result = invoke("show 1")
        assert "Project: infra" in result.output

    def test_numeric_project_name_does_not_hijack_output(self, cli: CliRunner) -> None:
        """Commands that know the project id must not re-resolve by name."""
        cli.invoke(main, ["project", "add", "2"])  # project id 1, named "2"
        result = cli.invoke(main, ["project", "add", "foo", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "foo"
        assert data["id"] == 2

        result = cli.invoke(
            main, ["project", "edit", "foo", "--description", "d", "--json"]
        )
        assert json.loads(result.output)["name"] == "foo"

        result = cli.invoke(main, ["project", "archive", "foo", "--json"])
        assert json.loads(result.output)["name"] == "foo"

        result = cli.invoke(main, ["project", "log", "foo", "note", "--json"])
        data = json.loads(result.output)
        assert data["name"] == "foo"
        assert data["updates"][0]["body"] == "note"

    def test_summary_json_includes_dependency_fields(self, cli: CliRunner) -> None:
        """Summary items must report the same dependency data as show/list."""
        cli.invoke(main, ["add", "Blocker"])
        cli.invoke(main, ["add", "Waiting"])
        cli.invoke(main, ["block", "2", "1"])
        cli.invoke(main, ["done", "1"])
        result = cli.invoke(main, ["summary", "--since", "1 days", "--json"])
        data = json.loads(result.output)
        item = next(i for i in data["items"] if i["id"] == 1)
        assert item["blocking"] == [2]

    def test_plain_list_titles_are_verbatim_when_blocked(self, invoke) -> None:
        """PlainOutput is machine-parseable: no decoration on titles."""
        invoke("add Blocker")
        invoke("add Waiting")
        invoke("block 2 1")
        result = invoke("list")
        lines = [ln for ln in result.output.split("\n") if "Waiting" in ln]
        assert lines, result.output
        assert "\U0001f6a7" not in lines[0]

    def test_project_show_lists_its_items(self, invoke) -> None:
        invoke("project add infra")
        invoke("add Task --project infra")
        invoke("add Other")
        data = json.loads(invoke("project show infra --json").output)
        assert [i["title"] for i in data["items"]] == ["Task"]


class TestTags:
    def test_empty(self, invoke) -> None:
        result = invoke("tags")
        assert result.exit_code == 0
        assert "No tags" in result.output

    def test_counts_and_order(self, invoke) -> None:
        invoke("add A -t common -t rare")
        invoke("add B -t common")
        invoke("add C -t common -t other")
        data = json.loads(invoke("tags --json").output)
        assert data[0] == {"tag": "common", "count": 3}
        # Ties broken alphabetically.
        assert [d["tag"] for d in data[1:]] == ["other", "rare"]

    def test_includes_done_items(self, invoke) -> None:
        invoke("add A -t keep")
        invoke("done 1")
        data = json.loads(invoke("tags --json").output)
        assert data == [{"tag": "keep", "count": 1}]

    def test_plain_output(self, invoke) -> None:
        invoke("add A -t foo")
        result = invoke("tags")
        assert result.exit_code == 0
        assert "foo" in result.output
        assert "1" in result.output


class TestBlockAtomicity:
    def test_failed_multi_block_applies_nothing(self, invoke) -> None:
        invoke("add One")
        invoke("add Two")
        result = invoke("block 2 1 999")
        assert result.exit_code == 1
        data = json.loads(invoke("show 2 --json").output)
        assert data["blocked_by"] == []
        assert data["is_blocked"] is False

    def test_cycle_mid_batch_rolls_back_earlier_blockers(self, invoke) -> None:
        invoke("add One")
        invoke("add Two")
        invoke("add Three")
        invoke("block 2 1")  # 1 blocks 2
        # Adding blockers (3, 2) to item 1: 3 is fine, 2 would form a cycle.
        result = invoke("block 1 3 2")
        assert result.exit_code == 1
        data = json.loads(invoke("show 1 --json").output)
        assert data["blocked_by"] == []

    def test_failed_batch_preserves_preexisting_blockers(self, invoke) -> None:
        """Rollback of a failed batch must not delete relations that existed
        before the batch (round-2 finding: INSERT OR IGNORE made re-adds
        indistinguishable from new edges, so compensation deleted them)."""
        invoke("add One")
        invoke("add Two")
        invoke("block 2 1")  # pre-existing relation
        result = invoke("block 2 1 999")  # re-add 1, then fail on 999
        assert result.exit_code == 1
        data = json.loads(invoke("show 2 --json").output)
        assert data["blocked_by"] == [1]  # pre-existing edge survives
        assert data["is_blocked"] is True

    def test_successful_multi_block_still_works(self, invoke) -> None:
        invoke("add One")
        invoke("add Two")
        invoke("add Three")
        result = invoke("block 3 1 2")
        assert result.exit_code == 0
        data = json.loads(invoke("show 3 --json").output)
        assert data["blocked_by"] == [1, 2]

    def test_unblock_missing_target_changes_nothing(self, invoke) -> None:
        invoke("add One")
        invoke("add Two")
        invoke("block 2 1")
        result = invoke("unblock 99 1")
        assert result.exit_code == 1
        assert json.loads(invoke("show 2 --json").output)["blocked_by"] == [1]


class TestUnblockWarning:
    def test_done_warns_about_newly_unblocked(self, invoke) -> None:
        invoke("add Blocker")
        invoke("add Waiting")
        invoke("block 2 1")
        result = invoke("done 1")
        assert result.exit_code == 0
        assert "#2 Waiting is now unblocked" in result.stderr

    def test_edit_to_done_warns(self, invoke) -> None:
        """Completing via 'edit -s done' must behave like done/mv."""
        invoke("add Blocker")
        invoke("add Waiting")
        invoke("block 2 1")
        result = invoke("edit 1 -s done")
        assert result.exit_code == 0
        assert "#2 Waiting is now unblocked" in result.stderr

    def test_edit_to_done_with_other_fields_warns(self, invoke) -> None:
        invoke("add Blocker")
        invoke("add Waiting")
        invoke("block 2 1")
        result = invoke("edit 1 -s done -p low")
        assert result.exit_code == 0
        assert "unblocked" in result.stderr
        data = json.loads(invoke("show 1 --json").output)
        assert data["priority"] == "low"
        assert data["status"] == "done"

    def test_mv_to_done_warns(self, invoke) -> None:
        invoke("add Blocker")
        invoke("add Waiting")
        invoke("block 2 1")
        result = invoke("mv 1 done")
        assert result.exit_code == 0
        assert "#2 Waiting is now unblocked" in result.stderr

    def test_warning_not_on_stdout(self, invoke) -> None:
        invoke("add Blocker")
        invoke("add Waiting")
        invoke("block 2 1")
        result = invoke("done 1 --json")
        assert result.exit_code == 0
        assert "unblocked" not in result.stdout
        json.loads(result.stdout)  # stdout stays machine-parseable

    def test_no_warning_when_dependent_still_blocked(self, invoke) -> None:
        invoke("add Blocker-a")
        invoke("add Blocker-b")
        invoke("add Waiting")
        invoke("block 3 1 2")
        result = invoke("done 1")
        assert result.exit_code == 0
        assert "unblocked" not in result.stderr

    def test_no_warning_without_dependents(self, invoke) -> None:
        invoke("add Solo")
        result = invoke("done 1")
        assert result.exit_code == 0
        assert "unblocked" not in result.stderr

    def test_completing_already_done_item_does_not_warn(self, invoke) -> None:
        invoke("add Blocker")
        invoke("add Waiting")
        invoke("block 2 1")
        invoke("done 1")
        result = invoke("done 1")
        assert result.exit_code == 0
        assert "unblocked" not in result.stderr


class TestListBlockedReady:
    def _setup(self, invoke) -> None:
        invoke("add Free")
        invoke("add Blocker")
        invoke("add Blocked")
        invoke("block 3 2")
        invoke("add Finished")
        invoke("done 4")

    def test_blocked_only(self, invoke) -> None:
        self._setup(invoke)
        data = json.loads(invoke("list --blocked --json").output)
        assert [i["id"] for i in data] == [3]

    def test_ready_excludes_blocked_and_done(self, invoke) -> None:
        self._setup(invoke)
        data = json.loads(invoke("list --ready --json").output)
        assert sorted(i["id"] for i in data) == [1, 2]

    def test_ready_with_all_still_excludes_done(self, invoke) -> None:
        self._setup(invoke)
        data = json.loads(invoke("list --ready --all --json").output)
        assert sorted(i["id"] for i in data) == [1, 2]

    def test_blocked_and_ready_mutually_exclusive(self, invoke) -> None:
        result = invoke("list --blocked --ready")
        assert result.exit_code != 0
        assert "mutually exclusive" in result.output

    def test_done_blocker_makes_item_ready(self, invoke) -> None:
        self._setup(invoke)
        invoke("done 2")
        data = json.loads(invoke("list --ready --json").output)
        assert sorted(i["id"] for i in data) == [1, 3]
        assert json.loads(invoke("list --blocked --json").output) == []

    def test_blocked_composes_with_other_filters(self, invoke) -> None:
        self._setup(invoke)
        invoke("add Urgent-blocked -p urgent")
        invoke("block 5 2")
        data = json.loads(invoke("list --blocked -p urgent --json").output)
        assert [i["id"] for i in data] == [5]


class TestBlockStorage:
    """Application + storage layer behavior, bypassing the CLI."""

    def test_add_and_query_relation(self, storage: SqliteStorage) -> None:
        a = storage.add("Blocker")
        b = storage.add("Blocked")

        block_todo(storage, b.id, a.id)

        refreshed = storage.get(b.id)
        assert refreshed.blocked_by == [a.id]
        assert refreshed.is_blocked is True
        assert storage.get(a.id).blocking == [b.id]

    def test_list_no_n_plus_one_context(self, storage: SqliteStorage) -> None:
        a = storage.add("Blocker")
        b = storage.add("Blocked")
        block_todo(storage, b.id, a.id)

        by_id = {i.id: i for i in storage.list()}
        assert by_id[b.id].blocked_by == [a.id]
        assert by_id[b.id].is_blocked is True
        assert by_id[a.id].blocking == [b.id]

    def test_self_block_raises(self, storage: SqliteStorage) -> None:
        a = storage.add("Item")
        with pytest.raises(DependencyError):
            block_todo(storage, a.id, a.id)

    def test_cycle_raises(self, storage: SqliteStorage) -> None:
        a = storage.add("One")
        b = storage.add("Two")
        block_todo(storage, b.id, a.id)
        with pytest.raises(DependencyError):
            block_todo(storage, a.id, b.id)

    def test_block_missing_raises(self, storage: SqliteStorage) -> None:
        a = storage.add("Item")
        with pytest.raises(NotFoundError):
            block_todo(storage, a.id, 999)

    def test_done_blocker_flips_is_blocked(self, storage: SqliteStorage) -> None:
        a = storage.add("Blocker")
        b = storage.add("Blocked")
        block_todo(storage, b.id, a.id)

        storage.update(a.id, status=Status.DONE)

        refreshed = storage.get(b.id)
        assert refreshed.blocked_by == [a.id]
        assert refreshed.is_blocked is False

    def test_delete_cascades(self, storage: SqliteStorage) -> None:
        a = storage.add("Blocker")
        b = storage.add("Blocked")
        block_todo(storage, b.id, a.id)

        storage.delete(a.id)

        refreshed = storage.get(b.id)
        assert refreshed.blocked_by == []
        assert refreshed.is_blocked is False

    def test_unblock_removes_relation(self, storage: SqliteStorage) -> None:
        a = storage.add("Blocker")
        b = storage.add("Blocked")
        block_todo(storage, b.id, a.id)

        unblock_todo(storage, b.id, a.id)

        assert storage.get(b.id).blocked_by == []
        assert storage.get(b.id).is_blocked is False


class TestFullWorkflow:
    """End-to-end workflow simulating AI + human usage."""

    def test_ai_workflow(self, cli: CliRunner) -> None:
        # AI adds items while working
        r = cli.invoke(
            main,
            [
                "add",
                "Refactor auth middleware",
                "-p",
                "high",
                "-t",
                "refactor",
                "--json",
            ],
        )
        assert r.exit_code == 0
        item = json.loads(r.output)
        item_id = str(item["id"])

        # AI moves to in-progress
        r = cli.invoke(main, ["mv", item_id, "in-progress", "--json"])
        assert r.exit_code == 0
        assert json.loads(r.output)["status"] == "in-progress"

        # AI marks done
        r = cli.invoke(main, ["done", item_id, "--json"])
        assert r.exit_code == 0
        done_item = json.loads(r.output)
        assert done_item["status"] == "done"
        assert done_item["done_at"] is not None

        # User asks for summary
        r = cli.invoke(main, ["summary", "--since", "1 days", "--json"])
        assert r.exit_code == 0
        summary = json.loads(r.output)
        assert summary["count"] == 1
        assert summary["items"][0]["title"] == "Refactor auth middleware"

    def test_human_workflow(self, cli: CliRunner) -> None:
        # Add several items
        cli.invoke(main, ["add", "Task A", "-p", "urgent", "--deadline", "2099-05-01"])
        cli.invoke(main, ["add", "Task B", "-p", "medium"])
        cli.invoke(main, ["add", "Task C", "-p", "low", "-s", "backlog"])

        # List shows correct order (urgent first, low last)
        r = cli.invoke(main, ["list", "--json"])
        items = json.loads(r.output)
        assert items[0]["priority"] == "urgent"
        assert items[-1]["priority"] == "low"

        # Edit and complete
        cli.invoke(main, ["edit", "2", "-p", "high"])
        cli.invoke(main, ["done", "1"])

        # Done items excluded by default
        r = cli.invoke(main, ["list", "--json"])
        ids = [i["id"] for i in json.loads(r.output)]
        assert 1 not in ids

        # But included with --all
        r = cli.invoke(main, ["list", "--all", "--json"])
        ids = [i["id"] for i in json.loads(r.output)]
        assert 1 in ids

        # Delete
        cli.invoke(main, ["rm", "3"])
        r = cli.invoke(main, ["list", "--all", "--json"])
        ids = [i["id"] for i in json.loads(r.output)]
        assert 3 not in ids


class TestOverdueSorting:
    """README and the query's own comment promise overdue items sort to
    the top; the ORDER BY had no deadline term at all."""

    def test_overdue_items_sort_above_non_overdue(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "Renew SSL cert", "-p", "low", "-d", "2020-01-01"])
        cli.invoke(main, ["add", "Ship feature", "-p", "urgent"])
        cli.invoke(main, ["add", "Pay invoice", "-p", "medium", "-d", "2021-06-01"])
        out = cli.invoke(main, ["list"]).output
        # Both overdue items outrank the urgent item with no deadline, and
        # the older deadline comes first.
        assert out.index("Renew SSL cert") < out.index("Pay invoice")
        assert out.index("Pay invoice") < out.index("Ship feature")

    def test_priority_still_orders_within_non_overdue(self, cli: CliRunner) -> None:
        cli.invoke(main, ["add", "low thing", "-p", "low"])
        cli.invoke(main, ["add", "urgent thing", "-p", "urgent"])
        result = cli.invoke(main, ["list"])
        assert result.output.index("urgent thing") < result.output.index("low thing")
