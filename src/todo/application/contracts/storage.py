from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from enum import Enum, auto
from typing import Protocol, runtime_checkable

from todo.domain.deadline import Deadline
from todo.domain.description import Description
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.project_name import ProjectName
from todo.domain.project_status import ProjectStatus
from todo.domain.project_update import ProjectUpdate
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.title import Title
from todo.domain.todo_item import TodoItem
from todo.domain.update_body import UpdateBody


class Unset(Enum):
    """Sentinel for distinguishing 'not provided' from None."""

    UNSET = auto()


UNSET = Unset.UNSET

# Module-scope aliases: inside StorageProtocol the name `list` is the query
# method, so `list[...]` would not resolve to the builtin there.
ProjectList = list[Project]
UpdateList = list[ProjectUpdate]
EdgeList = list[tuple[ItemId, ItemId]]
TagStringList = list[str]
ItemTagLists = list[list[Tag]]


@runtime_checkable
class StorageProtocol(Protocol):
    def transaction(self) -> AbstractContextManager[None]: ...

    def data_version(self) -> int: ...

    def done_ids(self) -> set[ItemId]: ...

    def add(
        self,
        title: Title,
        *,
        body: str = "",
        priority: Priority = Priority.MEDIUM,
        status: Status = Status.TODO,
        deadline: Deadline | None = None,
        tags: list[Tag] | None = None,
        project_id: int | None = None,
    ) -> TodoItem: ...

    def get(self, item_id: ItemId) -> TodoItem: ...

    def update(
        self,
        item_id: ItemId,
        *,
        title: Title | None = None,
        body: str | None = None,
        priority: Priority | None = None,
        status: Status | None = None,
        deadline: Deadline | None | Unset = UNSET,
        tags: list[Tag] | None = None,
        project_id: int | None | Unset = UNSET,
    ) -> TodoItem: ...

    def delete(self, item_id: ItemId) -> None: ...

    def done_since(self, since: datetime) -> list[TodoItem]: ...

    def add_blocker(self, blocked_id: ItemId, blocker_id: ItemId) -> None: ...

    def remove_blocker(self, blocked_id: ItemId, blocker_id: ItemId) -> None: ...

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

    def add_project(
        self, name: ProjectName, *, description: Description | str = ""
    ) -> Project: ...

    def get_project(self, project_id: int) -> Project: ...

    def get_project_by_name(self, name: str) -> Project: ...

    def list_projects(self, *, include_archived: bool = False) -> ProjectList: ...

    def project_counts(self) -> dict[int, tuple[int, int]]: ...

    def dependency_edges(self) -> EdgeList: ...

    def item_tags(self) -> ItemTagLists: ...

    def update_project(
        self,
        project_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        status: ProjectStatus | None = None,
    ) -> Project: ...

    def delete_project(self, project_id: int) -> None: ...

    def add_project_update(
        self, project_id: int, body: UpdateBody
    ) -> ProjectUpdate: ...

    def list_project_updates(self, project_id: int) -> UpdateList: ...
