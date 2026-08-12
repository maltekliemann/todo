from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from todo.application.contracts.storage import StorageProtocol, Unset
from todo.domain.enums import Priority, ProjectStatus, Status
from todo.domain.models import Project, ProjectUpdate, TodoItem
from todo.exceptions import DependencyError, NotFoundError


def _normalize_title(title: str) -> str:
    """Titles are single-line: every storage and render format (editor
    round-trip, plain output, table rows) relies on it."""
    normalized = " ".join(title.split())
    if not normalized:
        raise ValueError("Title cannot be empty.")
    return normalized


def _normalize_tags(tags: list[str] | None) -> list[str] | None:
    """Tags are stored comma-joined, so a comma inside a tag cannot
    round-trip — reject it instead of silently splitting into phantoms."""
    if tags is None:
        return None
    cleaned: list[str] = []
    for tag in tags:
        stripped = tag.strip()
        if not stripped:
            continue
        if "," in stripped:
            raise ValueError(f"Tag '{stripped}' contains a comma; use separate tags.")
        cleaned.append(stripped)
    return cleaned


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
        _normalize_title(title),
        body=body,
        priority=priority,
        status=status,
        deadline=deadline,
        tags=_normalize_tags(tags),
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
    the unblock warning can never silently miss a completion path. The whole
    read-update-read runs in one transaction, and a dependent deleted by a
    concurrent process is simply omitted — a completion never reports
    failure after it has already mutated."""
    with storage.transaction():
        before = storage.get(item_id)
        completing = status == Status.DONE and not before.is_done
        was_blocked = (
            {dep_id: storage.get(dep_id).is_blocked for dep_id in before.blocking}
            if completing
            else {}
        )
        item = storage.update(
            item_id,
            title=_normalize_title(title) if title is not None else None,
            body=body,
            priority=priority,
            status=status,
            deadline=deadline,
            tags=_normalize_tags(tags),
            project_id=project_id,
        )
        unblocked: list[TodoItem] = []
        if completing:
            for dep_id in sorted(before.blocking):
                if not was_blocked[dep_id]:
                    continue
                try:
                    after = storage.get(dep_id)
                except NotFoundError:
                    continue  # dependent deleted concurrently
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
    # Cycle check and insert run in ONE transaction: without it, two
    # concurrent processes can each pass the check and commit edges that
    # together form a cycle.
    with storage.transaction():
        storage.get(blocked_id)
        storage.get(blocker_id)
        # Adding "blocker_id blocks blocked_id" forms a cycle iff blocked_id
        # already transitively blocks blocker_id. Walk .blocking edges.
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

    The whole batch runs in one transaction: any failure (missing item,
    self-block, cycle) rolls back only this batch's writes, so pre-existing
    edges are untouched by construction — no compensation logic that could
    misidentify what to undo (round-2 finding).
    """
    with storage.transaction():
        for blocker_id in blocker_ids:
            block_todo(storage, blocked_id, blocker_id)
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
    with storage.transaction():
        item = storage.get(blocked_id)  # raises NotFoundError before changes
        for blocker_id in blocker_ids:
            if blocker_id not in item.blocked_by:
                raise DependencyError(
                    f"Item #{blocked_id} is not blocked by #{blocker_id}."
                )
        for blocker_id in blocker_ids:
            storage.remove_blocker(blocked_id, blocker_id)
        return storage.get(blocked_id)


def _validate_project_name(name: str) -> None:
    # "none" is the CLI's clear-sentinel for --project; a project by that
    # name would be unreachable from edit and cause silent detachment.
    if name.lower() == "none":
        raise ValueError("'none' is a reserved project name.")
    if not name.strip():
        raise ValueError("Project name cannot be empty.")


def add_project(
    storage: StorageProtocol,
    name: str,
    *,
    description: str = "",
) -> Project:
    _validate_project_name(name)
    return storage.add_project(name, description=description)


def edit_project(
    storage: StorageProtocol,
    project_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Project:
    if name is not None:
        _validate_project_name(name)
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
