"""Write an entry in a project's log.

Created, not added: the entry is new.
"""

from __future__ import annotations

from todo.application.contracts.project_log_store import ProjectLogStore
from todo.application.contracts.project_store import ProjectStore
from todo.domain.project_update import ProjectUpdate


class CreateProjectUpdate:
    """The entry and the project it is written against are two
    aggregates, so that there is a project to write against is said
    here, where both are in view."""

    def __init__(self, projects: ProjectStore, log: ProjectLogStore) -> None:
        self._projects = projects
        self._log = log

    def execute(self, update: ProjectUpdate) -> None:
        # Raises ProjectNotFoundError before anything is written.
        self._projects.get(update.project_id)
        self._log.append(update)
