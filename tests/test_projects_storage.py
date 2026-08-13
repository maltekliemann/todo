"""Storage-level project CRUD behavior."""

from __future__ import annotations

import pytest

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import add_todo
from todo.domain.project_status import ProjectStatus
from todo.exceptions import DuplicateProjectError, ProjectNotFoundError


class TestProjectCrud:
    def test_add_and_get(self, storage: SqliteStorage) -> None:
        project = storage.add_project("infra", description="Infra work")
        assert project.name == "infra"
        assert project.description == "Infra work"
        assert project.status == ProjectStatus.ACTIVE
        assert storage.get_project(project.id) == project
        assert storage.get_project_by_name("infra") == project

    def test_duplicate_name_rejected(self, storage: SqliteStorage) -> None:
        storage.add_project("infra")
        with pytest.raises(DuplicateProjectError):
            storage.add_project("infra")

    def test_get_missing_raises(self, storage: SqliteStorage) -> None:
        with pytest.raises(ProjectNotFoundError):
            storage.get_project(99)
        with pytest.raises(ProjectNotFoundError):
            storage.get_project_by_name("nope")

    def test_list_excludes_archived_by_default(self, storage: SqliteStorage) -> None:
        storage.add_project("active-one")
        archived = storage.add_project("archived-one")
        storage.update_project(archived.id, status=ProjectStatus.ARCHIVED)

        assert [p.name for p in storage.list_projects()] == ["active-one"]
        assert [p.name for p in storage.list_projects(include_archived=True)] == [
            "active-one",
            "archived-one",
        ]

    def test_update_fields(self, storage: SqliteStorage) -> None:
        project = storage.add_project("old", description="d")
        updated = storage.update_project(project.id, name="new", description="d2")
        assert updated.name == "new"
        assert updated.description == "d2"

    def test_rename_to_existing_name_rejected(self, storage: SqliteStorage) -> None:
        storage.add_project("taken")
        other = storage.add_project("other")
        with pytest.raises(DuplicateProjectError):
            storage.update_project(other.id, name="taken")

    def test_delete_unassigns_todos(self, storage: SqliteStorage) -> None:
        project = storage.add_project("doomed")
        item = add_todo(storage, "Task", project_id=project.id)
        assert item.project_name == "doomed"

        storage.delete_project(project.id)
        survivor = storage.get(item.id)
        assert survivor.project_id is None
        assert survivor.project_name is None

    def test_assign_and_clear_project_on_todo(self, storage: SqliteStorage) -> None:
        project = storage.add_project("p")
        add_todo(storage, "Task")
        assert storage.update(1, project_id=project.id).project_name == "p"
        assert storage.update(1, project_id=None).project_id is None
