from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from todo.application.contracts.storage import StorageProtocol, Unset
from todo.domain.enums import Priority, ProjectStatus, Status
from todo.domain.models import Project, ProjectUpdate, TodoItem
from todo.exceptions import DependencyError, TodoError


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
) -> CompletionResult:
    return _tracked_update(
        storage,
        item_id,
        status,
        title=title,
        body=body,
        priority=priority,
        deadline=deadline,
        tags=tags,
        project_id=project_id,
    )


@dataclass(frozen=True)
class CompletionResult:
    """Outcome of a status change, including dependents it unblocked."""

    item: TodoItem
    unblocked: list[TodoItem]


def _tracked_update(
    storage: StorageProtocol,
    item_id: int,
    status: Status | None,
    *,
    title: str | None = None,
    body: str | None = None,
    priority: Priority | None = None,
    deadline: date | None | Unset = Unset.UNSET,
    tags: list[str] | None = None,
    project_id: int | None | Unset = Unset.UNSET,
) -> CompletionResult:
    """Apply an update; when it completes the item, report newly unblocked
    dependents. Every path that can set status=done must go through here so
    the unblock warning can never silently miss a completion path."""
    before = storage.get(item_id)
    completing = status == Status.DONE and not before.is_done
    was_blocked = (
        {dep_id: storage.get(dep_id).is_blocked for dep_id in before.blocking}
        if completing
        else {}
    )
    item = storage.update(
        item_id,
        title=title,
        body=body,
        priority=priority,
        status=status,
        deadline=deadline,
        tags=tags,
        project_id=project_id,
    )
    unblocked: list[TodoItem] = []
    if completing:
        for dep_id in sorted(before.blocking):
            if not was_blocked[dep_id]:
                continue
            after = storage.get(dep_id)
            if not after.is_blocked:
                unblocked.append(after)
    return CompletionResult(item=item, unblocked=unblocked)


def move_todo(
    storage: StorageProtocol,
    item_id: int,
    status: Status,
) -> CompletionResult:
    return _tracked_update(storage, item_id, status)


def complete_todo(
    storage: StorageProtocol,
    item_id: int,
) -> CompletionResult:
    return _tracked_update(storage, item_id, Status.DONE)


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
    return unblock_todo_batch(storage, blocked_id, [blocker_id])


def block_todo_batch(
    storage: StorageProtocol,
    blocked_id: int,
    blocker_ids: list[int],
) -> TodoItem:
    """Add several blockers all-or-nothing.

    If any blocker is invalid (missing item, self-block, cycle), edges added
    by THIS batch are removed again before re-raising. Edges that existed
    before the batch are never touched: add_blocker is INSERT OR IGNORE, so
    a re-add "succeeds" without creating anything — compensating it would
    delete pre-existing data (round-2 finding).
    """
    added_by_batch: list[int] = []
    try:
        for blocker_id in blocker_ids:
            already = blocker_id in storage.get(blocked_id).blocked_by
            block_todo(storage, blocked_id, blocker_id)
            if not already:
                added_by_batch.append(blocker_id)
    except TodoError:
        for blocker_id in reversed(added_by_batch):
            storage.remove_blocker(blocked_id, blocker_id)
        raise
    return storage.get(blocked_id)


def unblock_todo_batch(
    storage: StorageProtocol,
    blocked_id: int,
    blocker_ids: list[int],
) -> TodoItem:
    """Remove several blockers all-or-nothing.

    Validates every id against the current blocker set before removing
    anything, so a typo errors out (like block does) instead of silently
    succeeding while the real blocker stays in place.
    """
    item = storage.get(blocked_id)  # raises NotFoundError before any change
    for blocker_id in blocker_ids:
        if blocker_id not in item.blocked_by:
            raise DependencyError(
                f"Item #{blocked_id} is not blocked by #{blocker_id}."
            )
    # Removals cannot fail after validation, so no rollback is needed.
    for blocker_id in blocker_ids:
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
