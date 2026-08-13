"""Unit tests for the domain models and application query helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.queries import list_todos, parse_since, resolve_project
from todo.domain.deadline import Deadline
from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.title import Title
from todo.domain.todo_item import TodoItem
from todo.exceptions import ProjectNotFoundError

_NOW = datetime.now(tz=timezone.utc)


def _item_with(*, deadline: Deadline, status: Status) -> TodoItem:
    now = datetime.now()
    return TodoItem(
        id=1,
        title=Title("t"),
        body="",
        priority=Priority.MEDIUM,
        status=status,
        created_at=now,
        updated_at=now,
        done_at=None,
        deadline=deadline,
        tags=frozenset(),
    )


class TestEnums:
    def test_priority_from_string_invalid(self) -> None:
        with pytest.raises(ValueError, match="Invalid priority"):
            Priority.from_string("nope")

    def test_priority_from_string_case_insensitive(self) -> None:
        assert Priority.from_string("URGENT") == Priority.URGENT

    def test_status_from_string_invalid(self) -> None:
        with pytest.raises(ValueError, match="Invalid status"):
            Status.from_string("nope")

    def test_status_order_boundaries(self) -> None:
        assert Status.DONE.next() is None
        assert Status.BACKLOG.prev() is None
        assert Status.BACKLOG.next() == Status.TODO
        assert Status.DONE.prev() == Status.IN_PROGRESS

    def test_done_and_active_are_opposites(self) -> None:
        assert Status.DONE.done and not Status.DONE.active
        assert all(s.active and not s.done for s in Status if s is not Status.DONE)


class TestModels:
    def test_project_is_archived(self) -> None:
        project = Project(
            id=1,
            name="p",
            description="",
            archived=True,
            created_at=_NOW,
            updated_at=_NOW,
        )
        assert project.archived is True

    def test_done_item_never_overdue_or_urgent(self) -> None:
        item = TodoItem(
            id=1,
            title="t",
            body="",
            priority=Priority.MEDIUM,
            status=Status.DONE,
            created_at=_NOW,
            updated_at=_NOW,
            done_at=_NOW,
            deadline=Deadline.from_date(date.today() - timedelta(days=5)),
            tags=frozenset(),
        )
        assert item.is_overdue is False
        assert item.deadline_urgent is False


class TestQueryHelpers:
    def test_blocked_and_ready_mutually_exclusive(self, storage: SqliteStorage) -> None:
        with pytest.raises(ValueError, match="mutually exclusive"):
            list_todos(storage, blocked=True, ready=True)

    def test_resolve_project_numeric_ref_prefers_id(
        self, storage: SqliteStorage
    ) -> None:
        """Round-1 asserted name-first here; round-2 confirmed that lets a
        numerically-named project shadow another project's id in every
        command including `project rm`. Numeric refs now mean the id shown
        in `project list`; names win only for non-numeric refs."""
        first = storage.add_project("something")  # id 1
        second_id = first.id + 1
        storage.add_project(str(first.id))  # id 2, literally named "1"
        # "1" is numeric -> resolves to project id 1, not the one named "1".
        assert resolve_project(storage, str(first.id)).name == "something"
        # The numerically-named project stays reachable by its id.
        assert resolve_project(storage, str(second_id)).name == str(first.id)

    def test_resolve_project_numeric_name_fallback(
        self, storage: SqliteStorage
    ) -> None:
        """A numeric ref that matches no id still finds a project named so."""
        storage.add_project("77")  # id 1, named "77"
        assert resolve_project(storage, "77").name == "77"

    def test_resolve_project_falls_back_to_id(self, storage: SqliteStorage) -> None:
        project = storage.add_project("named")
        assert resolve_project(storage, str(project.id)).name == "named"

    def test_resolve_project_unknown_raises(self, storage: SqliteStorage) -> None:
        with pytest.raises(ProjectNotFoundError):
            resolve_project(storage, "ghost")

    def test_resolve_project_superscript_digit_is_clean_not_found(
        self, storage: SqliteStorage
    ) -> None:
        """'²'.isdigit() is True but int('²') raises — must not traceback."""
        with pytest.raises(ProjectNotFoundError):
            resolve_project(storage, "²")

    def test_resolve_project_huge_numeric_ref_is_clean_not_found(
        self, storage: SqliteStorage
    ) -> None:
        """Ids beyond SQLite's 64-bit range must not raise OverflowError."""
        with pytest.raises(ProjectNotFoundError):
            resolve_project(storage, "99999999999999999999")

    def test_resolve_project_huge_numeric_name_still_found(
        self, storage: SqliteStorage
    ) -> None:
        storage.add_project("99999999999999999999")
        assert resolve_project(storage, "99999999999999999999").id == 1

    def test_parse_since_weeks_and_months(self) -> None:
        assert parse_since("2 weeks") < parse_since("1 week")
        assert parse_since("1 month") < parse_since("2 weeks")

    def test_parse_since_unknown_unit(self) -> None:
        with pytest.raises(ValueError, match="Unknown time unit"):
            parse_since("3 fortnights")


class TestTitle:
    def test_whitespace_is_collapsed_not_rejected(self) -> None:
        assert Title("  a\n\n b\tc ") == "a b c"

    def test_it_is_a_string(self) -> None:
        """Everything that formats or compares a title keeps working."""
        assert f"#{1} {Title('Task')}" == "#1 Task"
        assert Title("Task").startswith("Ta")

    @pytest.mark.parametrize("value", ["", "   ", "\n\t"])
    def test_an_empty_title_cannot_be_constructed(self, value: str) -> None:
        with pytest.raises(ValueError, match="[Tt]itle cannot be empty"):
            Title(value)


class TestTag:
    def test_whitespace_is_collapsed(self) -> None:
        assert Tag(" two  words ") == "two words"

    def test_an_empty_tag_cannot_be_constructed(self) -> None:
        with pytest.raises(ValueError, match="[Tt]ag cannot be empty"):
            Tag("  ")

    def test_a_comma_cannot_be_constructed(self) -> None:
        """Tags are stored comma-joined, so one containing a comma would
        come back as two phantom tags."""
        with pytest.raises(ValueError, match="comma"):
            Tag("a,b")


class TestDeadline:
    def test_has_passed(self) -> None:
        assert Deadline.from_date(date.today() - timedelta(days=1)).has_passed
        assert not Deadline.from_date(date.today() + timedelta(days=1)).has_passed

    def test_today_has_not_passed(self) -> None:
        assert not Deadline.from_date(date.today()).has_passed

    def test_days_until(self) -> None:
        assert Deadline.from_date(date.today() + timedelta(days=3)).days_until == 3
        assert Deadline.from_date(date.today() - timedelta(days=2)).days_until == -2

    def test_it_is_a_date(self) -> None:
        assert Deadline(2099, 1, 1) == date(2099, 1, 1)
        assert Deadline.fromisoformat("2099-01-01").isoformat() == "2099-01-01"

    def test_overdue_needs_the_item_not_only_the_date(self) -> None:
        """The date knows it has passed; only the item knows if that still
        matters."""
        past = Deadline.from_date(date.today() - timedelta(days=1))
        assert past.has_passed
        assert _item_with(deadline=past, status=Status.TODO).is_overdue
        assert not _item_with(deadline=past, status=Status.DONE).is_overdue
