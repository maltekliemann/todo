"""Strike an entry from a project's log."""

from __future__ import annotations

from todo.application.contracts.project_log_store import ProjectLogStore
from todo.domain.update_id import UpdateId


class DeleteProjectUpdate:
    def __init__(self, log: ProjectLogStore) -> None:
        self._log = log

    def execute(self, update_id: UpdateId) -> None:
        self._log.delete(update_id)
