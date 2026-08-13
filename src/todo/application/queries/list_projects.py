"""Every project, with how many of its items are open and done."""

from __future__ import annotations

from dataclasses import dataclass

from todo.application.contracts.item_store import ItemStore
from todo.application.contracts.project_store import ProjectStore
from todo.domain.project import Project
from todo.domain.project_filter import ProjectFilter


@dataclass(frozen=True)
class ProjectSummary:
    project: Project
    open_count: int
    done_count: int


class ListProjects:
    def __init__(self, projects: ProjectStore, items: ItemStore) -> None:
        self._projects = projects
        self._items = items

    def execute(self, project_filter: ProjectFilter) -> list[ProjectSummary]:
        # One count for all of them, not one query per project.
        counts = self._items.counts_by_project()
        return [
            ProjectSummary(
                project=project,
                open_count=counts[project.id].open if project.id in counts else 0,
                done_count=counts[project.id].done if project.id in counts else 0,
            )
            for project in self._projects.find(project_filter)
        ]
