"""Storage-level project CRUD behavior."""

from __future__ import annotations

import pytest

from todo.adapters.sqlite_item_store import SqliteItemStore
from todo.adapters.sqlite_project_log_store import SqliteProjectLogStore
from todo.adapters.sqlite_project_store import SqliteProjectStore
from todo.application.commands import add_todo, delete_project
from todo.domain.description import Description
from todo.domain.item_id import ItemId
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName
from todo.domain.project_status import ProjectStatus
from todo.domain.update_body import UpdateBody
from todo.exceptions import DuplicateProjectError, ProjectNotFoundError


class TestProjectCrud:
    def test_add_and_get(self, projects: SqliteProjectStore) -> None:
        project = projects.create(ProjectName("infra"), Description("Infra work"))
        assert project.name == "infra"
        assert project.description == "Infra work"
        assert project.status is ProjectStatus.NOT_STARTED
        assert projects.get(project.id) == project
        assert projects.get_by_name(ProjectName("infra")) == project

    def test_duplicate_name_rejected(self, projects: SqliteProjectStore) -> None:
        projects.create(ProjectName("infra"), Description(""))
        with pytest.raises(DuplicateProjectError):
            projects.create(ProjectName("infra"), Description(""))

    def test_get_missing_raises(self, projects: SqliteProjectStore) -> None:
        with pytest.raises(ProjectNotFoundError):
            projects.get(ProjectId(99))
        with pytest.raises(ProjectNotFoundError):
            projects.get_by_name(ProjectName("nope"))

    def test_list_excludes_the_ended_by_default(
        self, projects: SqliteProjectStore
    ) -> None:
        projects.create(ProjectName("current-one"), Description(""))
        finished = projects.create(ProjectName("finished-one"), Description(""))
        finished.set_status(ProjectStatus.DONE)
        projects.save(finished)

        assert [p.name for p in projects.find_all()] == ["current-one"]
        assert [p.name for p in projects.find_all(include_ended=True)] == [
            "current-one",
            "finished-one",
        ]

    def test_update_fields(self, projects: SqliteProjectStore) -> None:
        project = projects.create(ProjectName("old"), Description("d"))
        project.set_name(ProjectName("new"))
        project.set_description(Description("d2"))
        updated = projects.save(project)
        assert updated.name == "new"
        assert updated.description == "d2"

    def test_rename_to_existing_name_rejected(
        self, projects: SqliteProjectStore
    ) -> None:
        projects.create(ProjectName("taken"), Description(""))
        other = projects.create(ProjectName("other"), Description(""))
        with pytest.raises(DuplicateProjectError):
            other.set_name(ProjectName("taken"))
            projects.save(other)

    def test_delete_unassigns_todos(
        self,
        items: SqliteItemStore,
        projects: SqliteProjectStore,
        log: SqliteProjectLogStore,
    ) -> None:
        project = projects.create(ProjectName("doomed"), Description(""))
        item = add_todo(items, "Task", project_id=project.id)
        assert item.project_id == projects.get_by_name(ProjectName("doomed")).id

        # Through the command: what a deleted project means for its items
        # and its log spans three aggregates, so it is said there.
        delete_project(projects, items, log, project.id)
        survivor = items.get(item.id)
        assert survivor.project_id is None

    def test_delete_takes_the_log_with_it(
        self,
        items: SqliteItemStore,
        projects: SqliteProjectStore,
        log: SqliteProjectLogStore,
    ) -> None:
        project = projects.create(ProjectName("doomed"), Description(""))
        log.append(project.id, UpdateBody("a note"))

        delete_project(projects, items, log, project.id)
        assert log.entries_for(project.id) == []

    def test_assign_and_clear_project_on_todo(
        self, items: SqliteItemStore, projects: SqliteProjectStore
    ) -> None:
        project = projects.create(ProjectName("p"), Description(""))
        add_todo(items, "Task")
        item = items.get(ItemId(1))
        item.set_project_id(project.id)
        assigned = items.save(item)
        assert assigned.project_id == projects.get_by_name(ProjectName("p")).id
        item.set_project_id(None)
        assert items.save(item).project_id is None
