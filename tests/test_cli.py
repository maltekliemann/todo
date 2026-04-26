from __future__ import annotations

import json

from click.testing import CliRunner

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


class TestFullWorkflow:
    """End-to-end workflow simulating AI + human usage."""

    def test_ai_workflow(self, cli: CliRunner) -> None:
        # AI adds items while working
        r = cli.invoke(main, ["add", "Refactor auth middleware", "-p", "high", "-t", "refactor", "--json"])
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
