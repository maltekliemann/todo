"""The list view's filter state, exercised without a terminal."""

from __future__ import annotations

from datetime import datetime, timezone

from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.project_status import ProjectStatus
from todo.domain.status import Status
from todo.domain.todo_item import TodoItem
from todo.tui.filters import Filters

_NOW = datetime.now(tz=timezone.utc)


def _item(item_id: int, title: str, *, body: str = "", tags: list[str] | None = None):
    return TodoItem(
        id=item_id,
        title=title,
        body=body,
        priority=Priority.MEDIUM,
        status=Status.TODO,
        created_at=_NOW,
        updated_at=_NOW,
        done_at=None,
        deadline=None,
        tags=tags or [],
    )


def _project(project_id: int, name: str) -> Project:
    return Project(
        id=project_id,
        name=name,
        description="",
        status=ProjectStatus.ACTIVE,
        created_at=_NOW,
        updated_at=_NOW,
    )


class TestSearch:
    def test_no_query_returns_everything(self) -> None:
        items = [_item(1, "Alpha"), _item(2, "Beta")]
        assert Filters().apply_search(items) == items

    def test_matches_title_body_and_tags_casefolded(self) -> None:
        items = [
            _item(1, "Alpha"),
            _item(2, "Beta", body="mentions ALPHA"),
            _item(3, "Gamma", tags=["Alpha-tag"]),
            _item(4, "Delta"),
        ]
        found = Filters(search="alpha").apply_search(items)
        assert [i.id for i in found] == [1, 2, 3]


class TestTagCycle:
    def test_cycles_through_every_tag_then_off(self) -> None:
        f = Filters()
        tags = ["a", "b"]
        f.cycle_tag(tags)
        assert f.tag == "a"
        f.cycle_tag(tags)
        assert f.tag == "b"
        f.cycle_tag(tags)
        assert f.tag is None

    def test_no_tags_is_a_no_op(self) -> None:
        f = Filters()
        f.cycle_tag([])
        assert f.tag is None

    def test_vanished_tag_restarts_at_the_first(self) -> None:
        """The filtered tag can be deleted by another process between two
        presses; cycling must not raise, it restarts the cycle."""
        f = Filters(tag="gone")
        f.cycle_tag(["a", "b"])
        assert f.tag == "a"


class TestProjectCycle:
    def test_cycles_through_every_project_then_off(self) -> None:
        f = Filters()
        projects = [_project(1, "infra"), _project(2, "web")]
        f.cycle_project(projects)
        assert (f.project_id, f.project_name) == (1, "infra")
        f.cycle_project(projects)
        assert (f.project_id, f.project_name) == (2, "web")
        f.cycle_project(projects)
        assert (f.project_id, f.project_name) == (None, None)

    def test_no_projects_is_a_no_op(self) -> None:
        f = Filters()
        f.cycle_project([])
        assert f.project_id is None

    def test_vanished_project_restarts_at_the_first(self) -> None:
        f = Filters(project_id=99, project_name="deleted")
        f.cycle_project([_project(1, "infra")])
        assert (f.project_id, f.project_name) == (1, "infra")


class TestPriorityAndClearing:
    def test_same_priority_twice_clears_it(self) -> None:
        f = Filters()
        f.toggle_priority(Priority.URGENT)
        assert f.priority == Priority.URGENT
        f.toggle_priority(Priority.URGENT)
        assert f.priority is None

    def test_different_priority_replaces(self) -> None:
        f = Filters(priority=Priority.URGENT)
        f.toggle_priority(Priority.LOW)
        assert f.priority == Priority.LOW

    def test_any_active_and_clear(self) -> None:
        f = Filters()
        assert not f.any_active()
        f.search = "x"
        assert f.any_active()
        f.clear()
        assert not f.any_active()
        assert (f.tag, f.project_id, f.project_name, f.priority) == (
            None,
            None,
            None,
            None,
        )


class TestStatusParts:
    def test_lists_only_active_filters(self) -> None:
        assert Filters().status_parts() == []
        parts = Filters(
            search="q",
            tag="t",
            project_id=1,
            project_name="infra",
            priority=Priority.LOW,
        ).status_parts()
        assert len(parts) == 4
        assert "infra" in parts[2]
        assert "low" in parts[3]

    def test_deleted_project_keeps_its_remembered_name(self) -> None:
        parts = Filters(project_id=7, project_name="gone").status_parts()
        assert "gone" in parts[0]

    def test_unknown_project_name_degrades_to_a_placeholder(self) -> None:
        parts = Filters(project_id=7).status_parts()
        assert "?" in parts[0]

    def test_user_text_is_escaped(self) -> None:
        """The status line is markup: a tag named '[b]' must not style it."""
        parts = Filters(tag="[b]").status_parts()
        assert "\\[b]" in parts[0]
