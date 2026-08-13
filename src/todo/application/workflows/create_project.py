"""Create a project."""

from __future__ import annotations

from todo.application.contracts.project_store import ProjectStore
from todo.domain.project import Project


class CreateProject:
    def __init__(self, projects: ProjectStore) -> None:
        self._projects = projects

    def execute(self, project: Project) -> None:
        self._projects.create(project)
