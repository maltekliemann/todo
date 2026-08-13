"""Delete a project; its items survive, filed under nothing."""

from __future__ import annotations

from todo.application.contracts.item_store import ItemStore
from todo.application.contracts.project_log_store import ProjectLogStore
from todo.application.contracts.project_store import ProjectStore
from todo.domain.project_id import ProjectId


class DeleteProject:
    """What a project's disappearance means for the items that named it
    and for its log ranges over three aggregates, so all three are here."""

    def __init__(
        self,
        projects: ProjectStore,
        items: ItemStore,
        log: ProjectLogStore,
    ) -> None:
        self._projects = projects
        self._items = items
        self._log = log

    def execute(self, project_id: ProjectId) -> None:
        # Raises before anything moves if there is no such project.
        self._projects.get(project_id)
        self._items.unassign_project(project_id)
        self._log.delete_for_project(project_id)
        self._projects.delete(project_id)
