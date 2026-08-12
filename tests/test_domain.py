"""Unit tests for domain enums/models and application query helpers."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.queries import list_todos, parse_since, resolve_project
from todo.domain.enums import Priority, ProjectStatus, Status
from todo.domain.models import Project, TodoItem
from todo.exceptions import ProjectNotFoundError

_NOW = datetime.now(tz=timezone.utc)


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

    def test_active_statuses_exclude_done(self) -> None:
        assert Status.DONE not in Status.active_statuses()


class TestModels:
    def test_project_is_archived(self) -> None:
        project = Project(
            id=1,
            name="p",
            description="",
            status=ProjectStatus.ARCHIVED,
            created_at=_NOW,
            updated_at=_NOW,
        )
        assert project.is_archived is True

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
            deadline=date.today() - timedelta(days=5),
            tags=[],
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

    def test_parse_since_weeks_and_months(self) -> None:
        assert parse_since("2 weeks") < parse_since("1 week")
        assert parse_since("1 month") < parse_since("2 weeks")

    def test_parse_since_unknown_unit(self) -> None:
        with pytest.raises(ValueError, match="Unknown time unit"):
            parse_since("3 fortnights")
