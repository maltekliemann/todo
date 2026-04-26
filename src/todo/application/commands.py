from __future__ import annotations

from datetime import date

from todo.application.contracts.storage import StorageProtocol, Unset
from todo.domain.enums import Priority, Status
from todo.domain.models import TodoItem


def add_todo(
    storage: StorageProtocol,
    title: str,
    *,
    body: str = "",
    priority: Priority = Priority.MEDIUM,
    status: Status = Status.TODO,
    deadline: date | None = None,
    tags: list[str] | None = None,
) -> TodoItem:
    return storage.add(
        title,
        body=body,
        priority=priority,
        status=status,
        deadline=deadline,
        tags=tags,
    )


def edit_todo(
    storage: StorageProtocol,
    item_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    priority: Priority | None = None,
    status: Status | None = None,
    deadline: date | None | Unset = Unset.UNSET,
    tags: list[str] | None = None,
) -> TodoItem:
    return storage.update(
        item_id,
        title=title,
        body=body,
        priority=priority,
        status=status,
        deadline=deadline,
        tags=tags,
    )


def move_todo(
    storage: StorageProtocol,
    item_id: int,
    status: Status,
) -> TodoItem:
    return storage.update(item_id, status=status)


def complete_todo(
    storage: StorageProtocol,
    item_id: int,
) -> TodoItem:
    return storage.update(item_id, status=Status.DONE)


def delete_todo(
    storage: StorageProtocol,
    item_id: int,
) -> None:
    storage.delete(item_id)
