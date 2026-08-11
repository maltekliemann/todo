from __future__ import annotations

from datetime import date, datetime
from enum import Enum, auto
from typing import Protocol, runtime_checkable

from todo.domain.enums import Priority, Status
from todo.domain.models import TodoItem


class Unset(Enum):
    """Sentinel for distinguishing 'not provided' from None."""

    UNSET = auto()


UNSET = Unset.UNSET


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
        include_done: bool = False,
    ) -> list[TodoItem]: ...
