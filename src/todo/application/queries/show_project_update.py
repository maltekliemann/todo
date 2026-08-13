"""One log entry.

Which project a log entry belongs to is the entry's own answer, and it
stops being available once the entry is gone — so anything that deletes
one and then shows the project has to read it first.
"""

from __future__ import annotations

from todo.application.contracts.project_log_store import ProjectLogStore
from todo.domain.project_update import ProjectUpdate
from todo.domain.update_id import UpdateId


class ShowProjectUpdate:
    def __init__(self, log: ProjectLogStore) -> None:
        self._log = log

    def execute(self, update_id: UpdateId) -> ProjectUpdate:
        return self._log.get(update_id)
