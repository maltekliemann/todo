"""Move a project between not started, in progress, cancelled and done."""

from __future__ import annotations

from todo.application.contracts.project_store import ProjectStore
from todo.domain.project_id import ProjectId
from todo.domain.project_status import ProjectStatus


class SetProjectStatus:
    def __init__(self, projects: ProjectStore) -> None:
        self._projects = projects

    def execute(self, project_id: ProjectId, status: ProjectStatus) -> None:
        project = self._projects.get(project_id)
        project.set_status(status)
        self._projects.save(project)
