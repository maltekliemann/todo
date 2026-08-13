"""Unit tests for the Rich output adapter (untouched by CLI tests, which
run through PlainOutput because CliRunner is not a TTY)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

import pytest

from todo.adapters.output import RichOutput
from todo.application.queries import ProjectDetail, ProjectSummary
from todo.domain.deadline import Deadline
from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.project_status import ProjectStatus
from todo.domain.project_update import ProjectUpdate
from todo.domain.status import Status
from todo.domain.todo_item import TodoItem

_NOW = datetime.now(tz=timezone.utc)


def _item(**overrides: object) -> TodoItem:
    defaults: dict[str, object] = {
        "id": 1,
        "title": "Task",
        "body": "",
        "priority": Priority.MEDIUM,
        "status": Status.TODO,
        "created_at": _NOW,
        "updated_at": _NOW,
        "done_at": None,
        "deadline": None,
        "tags": [],
    }
    defaults.update(overrides)
    return TodoItem(**defaults)  # type: ignore[arg-type]


def _project(**overrides: object) -> Project:
    defaults: dict[str, object] = {
        "id": 1,
        "name": "infra",
        "description": "Infra work",
        "status": ProjectStatus.ACTIVE,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Project(**defaults)  # type: ignore[arg-type]


@pytest.fixture()
def rich_out(monkeypatch: pytest.MonkeyPatch) -> RichOutput:
    monkeypatch.setenv("COLUMNS", "140")  # avoid table truncation off-TTY
    return RichOutput()


class TestRichLists:
    def test_empty_list(self, rich_out: RichOutput, capsys) -> None:
        rich_out.print_list([])
        assert "No items" in capsys.readouterr().out

    def test_list_variants(self, rich_out: RichOutput, capsys) -> None:
        items = [
            _item(
                id=1,
                title="Overdue",
                deadline=Deadline.from_date(date.today() - timedelta(days=2)),
            ),
            _item(
                id=2,
                title="Urgent soon",
                priority=Priority.URGENT,
                deadline=Deadline.from_date(date.today() + timedelta(days=1)),
            ),
            _item(id=3, title="Blocked one", blocked_by=[1], is_blocked=True),
            _item(
                id=4,
                title="Finished",
                status=Status.DONE,
                done_at=_NOW,
                priority=Priority.LOW,
            ),
        ]
        rich_out.print_list(items)
        out = capsys.readouterr().out
        assert "Overdue" in out
        assert "Urgent soon" in out
        assert "\U0001f6a7" in out
        assert "4 items" in out

    def test_item_full_detail(self, rich_out: RichOutput, capsys) -> None:
        item = _item(
            title="Everything",
            body="A body",
            deadline=Deadline.from_date(date.today() + timedelta(days=10)),
            tags=["a", "b"],
            blocked_by=[7],
            blocking=[9],
            done_at=_NOW,
            status=Status.DONE,
        )
        rich_out.print_item(item)
        out = capsys.readouterr().out
        assert "Everything" in out
        assert "Tags: a, b" in out
        assert "Blocked by: #7" in out
        assert "Blocking: #9" in out
        assert "A body" in out

    def test_summary(self, rich_out: RichOutput, capsys) -> None:
        done = _item(status=Status.DONE, done_at=_NOW, title="Shipped")
        rich_out.print_summary(_NOW - timedelta(days=7), [done])
        out = capsys.readouterr().out
        assert "Shipped" in out
        assert "1 item completed" in out

    def test_summary_empty(self, rich_out: RichOutput, capsys) -> None:
        rich_out.print_summary(_NOW - timedelta(days=7), [])
        assert "No items completed" in capsys.readouterr().out

    def test_deleted(self, rich_out: RichOutput, capsys) -> None:
        rich_out.print_deleted(3)
        assert "#3" in capsys.readouterr().out


class TestRelativeAge:
    def test_all_age_buckets(self, rich_out: RichOutput, capsys) -> None:
        ages = [
            timedelta(seconds=30),
            timedelta(minutes=5),
            timedelta(hours=3),
            timedelta(days=2),
            timedelta(weeks=2),
            timedelta(days=90),
        ]
        items = [
            _item(id=i, title=f"Age {i}", created_at=_NOW - age)
            for i, age in enumerate(ages, start=1)
        ]
        rich_out.print_list(items)
        out = capsys.readouterr().out
        for pattern in (r"\d+s", r"5m", r"3h", r"2d", r"2w", r"3mo"):
            assert re.search(pattern, out), pattern


class TestRichTagsProjects:
    def test_tags(self, rich_out: RichOutput, capsys) -> None:
        rich_out.print_tags([("deploy", 3), ("infra", 1)])
        out = capsys.readouterr().out
        assert "deploy" in out
        assert "3" in out

    def test_tags_empty(self, rich_out: RichOutput, capsys) -> None:
        rich_out.print_tags([])
        assert "No tags" in capsys.readouterr().out

    def test_projects(self, rich_out: RichOutput, capsys) -> None:
        active = ProjectSummary(project=_project(), open_count=2, done_count=1)
        archived = ProjectSummary(
            project=_project(id=2, name="old", status=ProjectStatus.ARCHIVED),
            open_count=0,
            done_count=5,
        )
        rich_out.print_projects([active, archived])
        out = capsys.readouterr().out
        assert "infra" in out
        assert "archived" in out

    def test_projects_empty(self, rich_out: RichOutput, capsys) -> None:
        rich_out.print_projects([])
        assert "No projects" in capsys.readouterr().out

    def test_project_detail(self, rich_out: RichOutput, capsys) -> None:
        items = [
            _item(title="In project"),
            _item(id=2, title="Done one", status=Status.DONE, done_at=_NOW),
        ]
        updates = [
            ProjectUpdate(id=1, project_id=1, body="Kickoff done", created_at=_NOW)
        ]
        rich_out.print_project(
            ProjectDetail(project=_project(), items=items, updates=updates)
        )
        out = capsys.readouterr().out
        assert "infra" in out
        assert "1/2 done" in out
        assert "Infra work" in out
        assert "Kickoff done" in out

    def test_json_helpers(self, rich_out: RichOutput, capsys) -> None:
        import json as jsonlib

        detail = ProjectDetail(project=_project(), items=[_item()], updates=[])
        rich_out.print_json_project(detail)
        data = jsonlib.loads(capsys.readouterr().out)
        assert data["name"] == "infra"
        assert len(data["items"]) == 1
        assert data["updates"] == []


class TestRelativeAgeBuckets:
    """days 28-29 sit past the '<4 weeks' branch but below one month and
    must render as weeks, never '0mo'."""

    @staticmethod
    def _age_for(days: int) -> str:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        from todo.adapters.output import _relative_age

        dt = datetime.now(tz=ZoneInfo("UTC")) - timedelta(days=days, minutes=1)
        return _relative_age(dt)

    def test_27_days_is_3w(self) -> None:
        assert self._age_for(27) == "3w"

    def test_28_days_is_4w_not_0mo(self) -> None:
        assert self._age_for(28) == "4w"

    def test_29_days_is_4w_not_0mo(self) -> None:
        assert self._age_for(29) == "4w"

    def test_30_days_is_1mo(self) -> None:
        assert self._age_for(30) == "1mo"


class TestJsonOutputShared:
    def test_json_methods_are_one_implementation(self) -> None:
        """--json output is frontend-independent by definition: both output
        classes must share one implementation so the copies cannot drift."""
        from todo.adapters.output import PlainOutput, RichOutput

        for name in (
            "print_json_list",
            "print_json_item",
            "print_json_summary",
            "print_json_tags",
            "print_json_projects",
            "print_json_project",
        ):
            assert getattr(RichOutput, name) is getattr(PlainOutput, name), name


class TestColumnAlignment:
    def test_plain_priority_labels_are_equal_width(self) -> None:
        """PlainOutput is the machine-parseable format: a 7-char HIGH label
        against 6-char others shifts every high-priority row's columns."""
        from todo.adapters.output import _priority_label
        from todo.domain.priority import Priority

        widths = {len(_priority_label(p)) for p in Priority}
        assert len(widths) == 1, {p.value: _priority_label(p) for p in Priority}

    def test_plain_rows_align_across_priorities(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from todo.adapters.output import PlainOutput

        items = [
            _item(id=i + 1, title=f"item {p.value}", priority=p)
            for i, p in enumerate(Priority)
        ]
        PlainOutput().print_list(items)
        rows = [
            ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("  ")
        ]
        starts = {ln.index("todo") for ln in rows}
        assert len(starts) == 1, rows

    def test_overdue_deadline_cell_does_not_wrap(self) -> None:
        """The fixed-width Deadline column must hold the longest overdue
        form, or every such row wraps onto two lines."""
        from datetime import date, timedelta

        from todo.adapters.output import _DEADLINE_COL_WIDTH, _deadline_str

        longest = max(
            len(
                _deadline_str(
                    _item(deadline=Deadline.from_date(date.today() - timedelta(days=d)))
                )
            )
            for d in (1, 12, 340, 3400)
        )
        # The 🔴 prefix is a double-width cell, so it costs one more column.
        assert _DEADLINE_COL_WIDTH >= longest + 1
