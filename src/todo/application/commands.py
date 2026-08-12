from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from todo.application.contracts.storage import StorageProtocol, Unset
from todo.domain.enums import Priority, ProjectStatus, Status
from todo.domain.models import Project, ProjectUpdate, TodoItem
from todo.exceptions import DependencyError


def add_todo(
    storage: StorageProtocol,
    title: str,
    *,
    body: str = "",
    priority: Priority = Priority.MEDIUM,
    status: Status = Status.TODO,
    deadline: date | None = None,
    tags: list[str] | None = None,
    project_id: int | None = None,
) -> TodoItem:
    return storage.add(
        title,
        body=body,
        priority=priority,
        status=status,
        deadline=deadline,
        tags=tags,
        project_id=project_id,
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
    project_id: int | None | Unset = Unset.UNSET,
) -> TodoItem:
    return storage.update(
        item_id,
        title=title,
        body=body,
        priority=priority,
        status=status,
        deadline=deadline,
        tags=tags,
        project_id=project_id,
    )


@dataclass(frozen=True)
class CompletionResult:
    """Outcome of a status change, including dependents it unblocked."""

    item: TodoItem
    unblocked: list[TodoItem]


def _update_status(
    storage: StorageProtocol,
    item_id: int,
    status: Status,
) -> CompletionResult:
    before = storage.get(item_id)
    if status != Status.DONE or before.is_done:
        return CompletionResult(
            item=storage.update(item_id, status=status), unblocked=[]
        )
    was_blocked = {dep_id: storage.get(dep_id).is_blocked for dep_id in before.blocking}
    item = storage.update(item_id, status=Status.DONE)
    unblocked = [
        storage.get(dep_id)
        for dep_id in sorted(before.blocking)
        if was_blocked[dep_id] and not storage.get(dep_id).is_blocked
    ]
    return CompletionResult(item=item, unblocked=unblocked)


def move_todo(
    storage: StorageProtocol,
    item_id: int,
    status: Status,
) -> CompletionResult:
    return _update_status(storage, item_id, status)


def complete_todo(
    storage: StorageProtocol,
    item_id: int,
) -> CompletionResult:
    return _update_status(storage, item_id, Status.DONE)


def delete_todo(
    storage: StorageProtocol,
    item_id: int,
) -> None:
    storage.delete(item_id)


def block_todo(
    storage: StorageProtocol,
    blocked_id: int,
    blocker_id: int,
) -> TodoItem:
    if blocked_id == blocker_id:
        raise DependencyError("An item cannot block itself.")
    storage.get(blocked_id)
    storage.get(blocker_id)
    # Adding "blocker_id blocks blocked_id" forms a cycle iff blocked_id already
    # transitively blocks blocker_id. Walk .blocking edges from blocked_id.
    seen: set[int] = set()
    stack: list[int] = [blocked_id]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for nxt in storage.get(current).blocking:
            if nxt == blocker_id:
                raise DependencyError("Adding this blocker would create a cycle.")
            stack.append(nxt)
    storage.add_blocker(blocked_id, blocker_id)
    return storage.get(blocked_id)


def unblock_todo(
    storage: StorageProtocol,
    blocked_id: int,
    blocker_id: int,
) -> TodoItem:
    storage.remove_blocker(blocked_id, blocker_id)
    return storage.get(blocked_id)


def add_project(
    storage: StorageProtocol,
    name: str,
    *,
    description: str = "",
) -> Project:
    return storage.add_project(name, description=description)


def edit_project(
    storage: StorageProtocol,
    project_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Project:
    return storage.update_project(project_id, name=name, description=description)


def archive_project(
    storage: StorageProtocol,
    project_id: int,
) -> Project:
    return storage.update_project(project_id, status=ProjectStatus.ARCHIVED)


def delete_project(
    storage: StorageProtocol,
    project_id: int,
) -> None:
    storage.delete_project(project_id)


def log_project_update(
    storage: StorageProtocol,
    project_id: int,
    body: str,
) -> ProjectUpdate:
    return storage.add_project_update(project_id, body)


def assign_project(
    storage: StorageProtocol,
    item_id: int,
    project_id: int | None,
) -> TodoItem:
    return storage.update(item_id, project_id=project_id)
