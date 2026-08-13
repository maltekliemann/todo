from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone

from todo.application.contracts.storage import UNSET, StorageProtocol, Unset
from todo.application.dependencies import Dependencies
from todo.domain.body import Body
from todo.domain.deadline import Deadline
from todo.domain.dependency_graph import DependencyGraph
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
from todo.exceptions import DependencyError, NotFoundError


def _now() -> datetime:
    """The application layer's clock. The domain takes the time it is
    given rather than reading one, so a transition is testable."""
    return datetime.now(tz=timezone.utc)


def _to_tags(tags: Sequence[str] | None) -> list[Tag] | None:
    """Raw strings become Tags; None means "leave them alone".

    Passing an empty list still clears them, which is explicit. Tag itself
    rejects what cannot be stored (empty, comma, multi-line); the two rules
    here are not about a tag being valid — deduping is about the set, and
    'none' is the CLI's clear-sentinel for --tag, so a tag by that name
    would be unreachable, exactly as for --project.
    """
    if tags is None:
        return None
    cleaned: list[Tag] = []
    for raw in tags:
        tag = Tag(raw)
        if tag.lower() == "none":
            raise ValueError("'none' is a reserved tag name.")
        if tag not in cleaned:
            # Dedupe here so tag counts count items, not occurrences.
            cleaned.append(tag)
    return cleaned


def _to_deadline(value: date | None) -> Deadline | None:
    """A plain date from the CLI or the TUI becomes the domain's Deadline.

    None passes through: it means "no deadline".
    """
    if value is None:
        return None
    return Deadline.from_date(value)


def add_todo(
    storage: StorageProtocol,
    title: str,
    *,
    body: str = "",
    priority: Priority = Priority.MEDIUM,
    status: Status = Status.TODO,
    deadline: date | None = None,
    tags: Sequence[str] | None = None,
    project_id: int | None = None,
) -> TodoItem:
    return storage.add(
        Title(title),
        body=body,
        priority=priority,
        status=status,
        deadline=_to_deadline(deadline),
        tags=frozenset(_to_tags(tags) or ()),
        project_id=project_id,
    )


def edit_todo(
    storage: StorageProtocol,
    item_id: ItemId,
    *,
    title: str | None = None,
    body: str | None = None,
    priority: Priority | None = None,
    status: Status | None = None,
    deadline: date | None | Unset = Unset.UNSET,
    tags: Sequence[str] | None = None,
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
    item_id: ItemId,
    status: Status | None,
    *,
    title: str | None = None,
    body: str | None = None,
    priority: Priority | None = None,
    deadline: date | None | Unset = UNSET,
    tags: Sequence[str] | None = None,
    project_id: int | None | Unset = UNSET,
) -> CompletionResult:
    """Load the item, change it through its own methods, save it.

    Every path that can complete an item goes through here, so the report
    of newly unblocked dependents can never silently miss one. The whole
    read-change-save runs in one transaction; a dependent deleted by a
    concurrent process is simply omitted, because a completion never
    reports failure after it has already happened.
    """
    with storage.transaction():
        item = storage.get(item_id)
        # Only a completion can unblock anything, so nothing else pays for
        # reading the graph — and one read answers both questions.
        deps = (
            Dependencies.load(storage)
            if status is Status.DONE and not item.is_done
            else None
        )
        dependents = deps.dependents_of(item_id) if deps else []
        completing = deps is not None and bool(dependents)
        blocked_before = deps.blocked_ids() if completing and deps else set()

        if title is not None:
            item.set_title(Title(title))
        if body is not None:
            item.set_body(Body(body))
        if priority is not None:
            item.set_priority(priority)
        if not isinstance(deadline, Unset):
            item.set_deadline(_to_deadline(deadline))
        if tags is not None:
            _retag(item, _to_tags(tags) or [])
        if not isinstance(project_id, Unset):
            item.set_project(
                storage.get_project(project_id) if project_id is not None else None
            )
        if status is not None:
            item.set_status(status)

        saved = storage.save(item)
        unblocked: list[TodoItem] = []
        if completing:
            unblocked = _newly_unblocked(storage, dependents, blocked_before)
    return CompletionResult(item=saved, unblocked=unblocked)


def _retag(item: TodoItem, tags: list[Tag]) -> None:
    """Make the item's tags exactly these, one add or remove at a time."""
    wanted = set(tags)
    for gone in item.tags - wanted:
        item.remove_tag(gone)
    for added in wanted - item.tags:
        item.add_tag(added)


def _newly_unblocked(
    storage: StorageProtocol,
    dependents: list[ItemId],
    blocked_before: set[ItemId],
) -> list[TodoItem]:
    """Hydrate the dependents that just transitioned blocked -> unblocked."""
    blocked_after = Dependencies.load(storage).blocked_ids()
    unblocked: list[TodoItem] = []
    for dep_id in sorted(dependents):
        if dep_id not in blocked_before or dep_id in blocked_after:
            continue
        try:
            unblocked.append(storage.get(dep_id))
        except NotFoundError:
            continue  # dependent deleted concurrently
    return unblocked


def move_todo(
    storage: StorageProtocol,
    item_id: ItemId,
    status: Status,
) -> CompletionResult:
    return _tracked_update(storage, item_id, status)


def complete_todo(
    storage: StorageProtocol,
    item_id: ItemId,
) -> CompletionResult:
    return _tracked_update(storage, item_id, Status.DONE)


def delete_todo(
    storage: StorageProtocol,
    item_id: ItemId,
) -> list[TodoItem]:
    """Delete an item; returns dependents its removal unblocked.

    Cascade removal of dependency edges unblocks dependents exactly like
    completing the blocker does, so it must report them the same way.
    """
    with storage.transaction():
        storage.get(item_id)  # raises NotFoundError before any graph work
        deps = Dependencies.load(storage)
        dependents = deps.dependents_of(item_id)
        if not dependents:
            storage.delete(item_id)
            return []
        blocked_before = deps.blocked_ids()
        storage.delete(item_id)
        return _newly_unblocked(storage, dependents, blocked_before)


def block_todo(
    storage: StorageProtocol,
    blocked_id: ItemId,
    blocker_id: ItemId,
) -> TodoItem:
    return block_todo_batch(storage, blocked_id, [blocker_id])


def unblock_todo(
    storage: StorageProtocol,
    blocked_id: ItemId,
    blocker_id: ItemId,
) -> TodoItem:
    return unblock_todo_batch(storage, blocked_id, [blocker_id])


def block_todo_batch(
    storage: StorageProtocol,
    blocked_id: ItemId,
    blocker_ids: list[ItemId],
) -> TodoItem:
    """Add several blockers all-or-nothing.

    The whole batch runs in one transaction: any failure (missing item,
    self-block, cycle) rolls back only this batch's writes, so pre-existing
    edges are untouched by construction — no compensation logic that could
    misidentify what to undo (round-2 finding).

    What may be added is the graph's rule, not this function's: the edge
    set is loaded once, and each addition goes through it. An edge that
    only forms a cycle together with an earlier edge in the same batch is
    refused by the same code as any other, because the graph being folded
    over already contains that earlier edge.
    """
    with storage.transaction():
        storage.get(blocked_id)  # raises NotFoundError before any graph work
        graph = DependencyGraph(frozenset(storage.dependency_edges()))
        # Blocker existence is enforced once, by add_blocker's probes —
        # not duplicated here with a full hydration per blocker.
        for blocker_id in blocker_ids:
            graph = graph.with_edge(blocker_id, blocked_id)
            storage.add_blocker(blocked_id, blocker_id)
        return storage.get(blocked_id)


def unblock_todo_batch(
    storage: StorageProtocol,
    blocked_id: ItemId,
    blocker_ids: list[ItemId],
) -> TodoItem:
    """Remove several blockers all-or-nothing.

    Validates every id against the current blocker set before removing
    anything, so a typo errors out (like block does) instead of silently
    succeeding while the real blocker stays in place.
    """
    with storage.transaction():
        storage.get(blocked_id)  # raises NotFoundError before changes
        blockers = Dependencies.load(storage).blockers_of(blocked_id)
        for blocker_id in blocker_ids:
            if blocker_id not in blockers:
                raise DependencyError(
                    f"Item #{blocked_id} is not blocked by #{blocker_id}."
                )
        for blocker_id in blocker_ids:
            storage.remove_blocker(blocked_id, blocker_id)
        return storage.get(blocked_id)


def _to_project_name(name: str) -> ProjectName:
    # ProjectName carries the single-line contract. "none" is the CLI's
    # clear-sentinel for --project, so a project by that name would be
    # unreachable from edit — a fact about the flag, not about the name.
    project_name = ProjectName(name)
    if project_name.lower() == "none":
        raise ValueError("'none' is a reserved project name.")
    return project_name


def add_project(
    storage: StorageProtocol,
    name: str,
    *,
    description: str = "",
) -> Project:
    return storage.add_project(
        _to_project_name(name),
        description=Description(description),
    )


def edit_project(
    storage: StorageProtocol,
    project_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Project:
    normalized = _to_project_name(name) if name is not None else None
    return storage.update_project(
        project_id,
        name=normalized,
        description=(Description(description) if description is not None else None),
    )


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
    return storage.add_project_update(project_id, UpdateBody(body))
