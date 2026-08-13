"""One project, its items, and its log."""

from __future__ import annotations

from dataclasses import dataclass

from todo.application.contracts.item_store import ItemStore
from todo.application.contracts.project_log_store import ProjectLogStore
from todo.application.contracts.project_store import ProjectStore
from todo.domain.item_filter import ItemFilter
from todo.domain.project import Project
from todo.domain.project_id import ProjectId
from todo.domain.project_update import ProjectUpdate
from todo.domain.todo_item import TodoItem


@dataclass(frozen=True)
class ProjectDetail:
    project: Project
    items: list[TodoItem]
    updates: list[ProjectUpdate]


class ShowProject:
    def __init__(
        self,
        projects: ProjectStore,
        items: ItemStore,
        log: ProjectLogStore,
    ) -> None:
        self._projects = projects
        self._items = items
        self._log = log

    def execute(self, project_id: ProjectId) -> ProjectDetail:
        return ProjectDetail(
            project=self._projects.get(project_id),
            # Done included: a project's page is the whole of it.
            items=self._items.find(
                ItemFilter(project_id=project_id, include_done=True)
            ),
            updates=self._log.entries_for(project_id),
        )
