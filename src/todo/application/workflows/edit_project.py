"""Keep a project as it now stands."""

from __future__ import annotations

from todo.application.contracts.project_store import ProjectStore
from todo.domain.project import Project


class EditProject:
    def __init__(self, projects: ProjectStore) -> None:
        self._projects = projects

    def execute(self, project: Project) -> None:
        self._projects.save(project)
