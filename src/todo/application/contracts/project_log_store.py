"""Where a project's log is kept.

Its own store, not something reached through the project: an entry is
written and deleted on its own, and a project's whole history is not
something to load in order to say one thing about today.
"""

from __future__ import annotations

from typing import Protocol

from todo.domain.project_id import ProjectId
from todo.domain.project_update import ProjectUpdate
from todo.domain.update_id import UpdateId


class ProjectLogStore(Protocol):
    def append(self, update: ProjectUpdate) -> None:
        """Write one entry.

        That there is a project to write it against is not asked here:
        the entry and the project are two aggregates, and what one means
        for the other is decided above.
        """
        ...

    def get(self, update_id: UpdateId) -> ProjectUpdate:
        """The entry, or NotFoundError."""
        ...

    def entries_for(self, project_id: ProjectId) -> list[ProjectUpdate]:
        """That project's log, most recent first."""
        ...

    def delete_for_project(self, project_id: ProjectId) -> None:
        """Strike the whole log. A project that is gone has no history
        anything can reach."""
        ...

    def delete(self, update_id: UpdateId) -> None:
        """Strike one entry. Writing the wrong thing down is not history."""
        ...
