from __future__ import annotations

from datetime import date, datetime
from enum import Enum, auto
from typing import Protocol, runtime_checkable

from todo.domain.enums import Priority, ProjectStatus, Status
from todo.domain.models import Project, TodoItem


class Unset(Enum):
    """Sentinel for distinguishing 'not provided' from None."""

    UNSET = auto()


UNSET = Unset.UNSET

# Module-scope alias: inside StorageProtocol the name `list` is the query
# method, so `list[Project]` would not resolve to the builtin there.
ProjectList = list[Project]


@runtime_checkable
class StorageProtocol(Protocol):
    def add(
        self,
        title: str,
        *,
        body: str = "",
        priority: Priority = Priority.MEDIUM,
        status: Status = Status.TODO,
        deadline: date | None = None,
        tags: list[str] | None = None,
        project_id: int | None = None,
    ) -> TodoItem: ...

    def get(self, item_id: int) -> TodoItem: ...

    def update(
        self,
        item_id: int,
        *,
        title: str | None = None,
        body: str | None = None,
        priority: Priority | None = None,
        status: Status | None = None,
        deadline: date | None | Unset = UNSET,
        tags: list[str] | None = None,
        project_id: int | None | Unset = UNSET,
    ) -> TodoItem: ...

    def delete(self, item_id: int) -> None: ...

    def done_since(self, since: datetime) -> list[TodoItem]: ...

    def add_blocker(self, blocked_id: int, blocker_id: int) -> None: ...

    def remove_blocker(self, blocked_id: int, blocker_id: int) -> None: ...

    def list(
        self,
        *,
        status: Status | None = None,
        priority: Priority | None = None,
        tags: list[str] | None = None,
        search: str | None = None,
        project_id: int | None = None,
        include_done: bool = False,
    ) -> list[TodoItem]: ...

    def add_project(self, name: str, *, description: str = "") -> Project: ...

    def get_project(self, project_id: int) -> Project: ...

    def get_project_by_name(self, name: str) -> Project: ...

    def list_projects(self, *, include_archived: bool = False) -> ProjectList: ...

    def update_project(
        self,
        project_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        status: ProjectStatus | None = None,
    ) -> Project: ...

    def delete_project(self, project_id: int) -> None: ...
