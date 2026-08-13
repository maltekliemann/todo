from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemStore
from todo.application.contracts.project_log_store import ProjectLogStore
from todo.application.contracts.project_store import ProjectStore
from todo.application.dependencies import Dependencies
from todo.application.unset import UNSET, Unset
from todo.domain.body import Body
from todo.domain.deadline import Deadline
from todo.domain.dependency_graph import DependencyGraph
from todo.domain.description import Description
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName
from todo.domain.project_status import ProjectStatus
from todo.domain.project_update import ProjectUpdate
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.title import Title
from todo.domain.todo_item import TodoItem
from todo.domain.update_body import UpdateBody
from todo.domain.update_id import UpdateId
from todo.exceptions import DependencyError, NotFoundError


def _to_tags(tags: Sequence[str] | None) -> frozenset[Tag] | None:
    """Raw strings become Tags; None means "leave them alone".

    An empty sequence still clears them, which is explicit. Tag itself
    rejects what cannot be stored (empty, comma, multi-line); the rule
    here is not about a tag being valid — 'none' is the CLI's
    clear-sentinel for --tag, so a tag by that name would be unreachable,
    exactly as for --project.
    """
    if tags is None:
        return None
    cleaned: set[Tag] = set()
    for raw in tags:
        tag = Tag(raw)
        if tag.lower() == "none":
            raise ValueError("'none' is a reserved tag name.")
        cleaned.add(tag)
    return frozenset(cleaned)


def _to_deadline(value: date | None) -> Deadline | None:
    """A plain date from the CLI or the TUI becomes the domain's Deadline.

    None passes through: it means "no deadline".
    """
    if value is None:
        return None
    return Deadline.from_date(value)


def add_todo(
    items: ItemStore,
    title: str,
    *,
    body: str = "",
    priority: Priority = Priority.MEDIUM,
    status: Status = Status.TODO,
    deadline: date | None = None,
    tags: Sequence[str] | None = None,
    project_id: ProjectId | None = None,
) -> TodoItem:
    return items.create(
        title=Title(title),
        body=Body(body),
        priority=priority,
        status=status,
        deadline=_to_deadline(deadline),
        tags=_to_tags(tags) or frozenset(),
        project_id=project_id,
    )


@dataclass(frozen=True)
class CompletionResult:
    """Outcome of a status change, including dependents it unblocked."""

    item: TodoItem
    unblocked: list[TodoItem]


def edit_todo(
    items: ItemStore,
    dependencies: DependencyStore,
    item_id: ItemId,
    *,
    title: str | None = None,
    body: str | None = None,
    priority: Priority | None = None,
    status: Status | None = None,
    deadline: date | None | Unset = UNSET,
    tags: Sequence[str] | None = None,
    project_id: ProjectId | None | Unset = UNSET,
) -> CompletionResult:
    """Load the item, change it through its own methods, save it.

    Every path that can complete an item goes through here, so the report
    of newly unblocked dependents can never silently miss one. Saving the
    item is one write; a dependent deleted by a concurrent process is
    simply omitted, because a completion never reports failure after it
    has already happened.
    """
    item = items.get(item_id)
    # Only a completion can unblock anything, so nothing else pays for
    # reading the graph — and one read answers both questions.
    deps = (
        Dependencies.load(items, dependencies)
        if status is not None and status.done and not item.is_done
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
        _retag(item, _to_tags(tags) or frozenset())
    if not isinstance(project_id, Unset):
        item.set_project_id(project_id)
    if status is not None:
        item.set_status(status)

    saved = items.save(item)
    unblocked: list[TodoItem] = []
    if completing:
        unblocked = _newly_unblocked(items, dependencies, dependents, blocked_before)
    return CompletionResult(item=saved, unblocked=unblocked)


def _live_graph(items: ItemStore, dependencies: DependencyStore) -> DependencyGraph:
    """The graph as it stands for the items that exist.

    Every load goes through here, changes included: a rule checked
    against an edge naming a deleted item would refuse things it has no
    business refusing, and a graph saved back unrestricted would carry
    that edge forward forever.
    """
    return dependencies.load().restricted_to(items.all_ids())


def _retag(item: TodoItem, tags: frozenset[Tag]) -> None:
    """Make the item's tags exactly these, one add or remove at a time."""
    for gone in item.tags - tags:
        item.remove_tag(gone)
    for added in tags - item.tags:
        item.add_tag(added)


def _newly_unblocked(
    items: ItemStore,
    dependencies: DependencyStore,
    dependents: list[ItemId],
    blocked_before: set[ItemId],
) -> list[TodoItem]:
    """Load the dependents that just went from blocked to not blocked."""
    blocked_after = Dependencies.load(items, dependencies).blocked_ids()
    unblocked: list[TodoItem] = []
    for dep_id in sorted(dependents):
        if dep_id not in blocked_before or dep_id in blocked_after:
            continue
        try:
            unblocked.append(items.get(dep_id))
        except NotFoundError:
            continue  # dependent deleted concurrently
    return unblocked


def move_todo(
    items: ItemStore,
    dependencies: DependencyStore,
    item_id: ItemId,
    status: Status,
) -> CompletionResult:
    return edit_todo(items, dependencies, item_id, status=status)


def complete_todo(
    items: ItemStore,
    dependencies: DependencyStore,
    item_id: ItemId,
) -> CompletionResult:
    return edit_todo(items, dependencies, item_id, status=Status.DONE)


def delete_todo(
    items: ItemStore,
    dependencies: DependencyStore,
    item_id: ItemId,
) -> list[TodoItem]:
    """Delete an item; returns dependents its removal unblocked.

    A dependency that names a vanished item is not a dependency. The
    graph says so on every read (DependencyGraph.restricted_to), so the
    edges are already meaningless the instant the item goes; dropping
    them here is housekeeping, and this being two writes rather than one
    cannot leave anything that reads as true.

    Losing those edges unblocks dependents exactly like completing the
    item does, so it is reported the same way.
    """
    if not items.exists(item_id):
        raise NotFoundError(item_id)
    graph = _live_graph(items, dependencies)
    deps = Dependencies(graph=graph, done_ids=items.done_ids())
    dependents = deps.dependents_of(item_id)
    blocked_before = deps.blocked_ids()
    items.delete(item_id)
    orphaned = [e for e in graph.edges if item_id in e]
    if orphaned:
        dependencies.save(graph.without_edges(orphaned))
    if not dependents:
        return []
    return _newly_unblocked(items, dependencies, dependents, blocked_before)


def block_todo(
    items: ItemStore,
    dependencies: DependencyStore,
    blocked_id: ItemId,
    blocker_id: ItemId,
) -> TodoItem:
    return block_todo_batch(items, dependencies, blocked_id, [blocker_id])


def unblock_todo(
    items: ItemStore,
    dependencies: DependencyStore,
    blocked_id: ItemId,
    blocker_id: ItemId,
) -> TodoItem:
    return unblock_todo_batch(items, dependencies, blocked_id, [blocker_id])


def block_todo_batch(
    items: ItemStore,
    dependencies: DependencyStore,
    blocked_id: ItemId,
    blocker_ids: list[ItemId],
) -> TodoItem:
    """Add several blockers all-or-nothing.

    What may be added is the graph's rule, not this function's: the graph
    is loaded once and each addition goes through it. An edge that only
    forms a cycle together with an earlier edge in the same batch is
    refused by the same code as any other, because the graph being folded
    over already contains that earlier edge. Nothing is written until
    every addition has been allowed, and then the whole set is written at
    once — there is no half-applied batch to compensate for.
    """
    if not items.exists(blocked_id):
        raise NotFoundError(blocked_id)
    graph = _live_graph(items, dependencies)
    for blocker_id in blocker_ids:
        graph = graph.with_edge(blocker_id, blocked_id)
    for blocker_id in blocker_ids:
        if not items.exists(blocker_id):
            raise NotFoundError(blocker_id)
    dependencies.save(graph)
    return items.get(blocked_id)


def unblock_todo_batch(
    items: ItemStore,
    dependencies: DependencyStore,
    blocked_id: ItemId,
    blocker_ids: list[ItemId],
) -> TodoItem:
    """Remove several blockers all-or-nothing.

    Validates every id against the current blockers before removing
    anything, so a typo errors out (like block does) instead of silently
    succeeding while the real blocker stays in place.
    """
    if not items.exists(blocked_id):
        raise NotFoundError(blocked_id)
    graph = _live_graph(items, dependencies)
    blockers = graph.blockers_of(blocked_id)
    for blocker_id in blocker_ids:
        if blocker_id not in blockers:
            raise DependencyError(
                f"Item #{blocked_id} is not blocked by #{blocker_id}."
            )
    dependencies.save(graph.without_edges((b, blocked_id) for b in blocker_ids))
    return items.get(blocked_id)


def _to_project_name(name: str) -> ProjectName:
    # ProjectName carries the single-line contract. "none" is the CLI's
    # clear-sentinel for --project, so a project by that name would be
    # unreachable from edit — a fact about the flag, not about the name.
    project_name = ProjectName(name)
    if project_name.lower() == "none":
        raise ValueError("'none' is a reserved project name.")
    return project_name


def add_project(
    projects: ProjectStore,
    name: str,
    *,
    description: str = "",
) -> Project:
    return projects.create(_to_project_name(name), Description(description))


def edit_project(
    projects: ProjectStore,
    project_id: ProjectId,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Project:
    project = projects.get(project_id)
    if name is not None:
        project.set_name(_to_project_name(name))
    if description is not None:
        project.set_description(Description(description))
    return projects.save(project)


def set_project_status(
    projects: ProjectStore,
    project_id: ProjectId,
    status: ProjectStatus,
) -> Project:
    project = projects.get(project_id)
    project.set_status(status)
    return projects.save(project)


def delete_project(
    projects: ProjectStore,
    items: ItemStore,
    log: ProjectLogStore,
    project_id: ProjectId,
) -> None:
    """Delete a project; its items survive, filed under nothing.

    What a project's disappearance means for the items that named it and
    for its log ranges over three aggregates, so it is said here, once,
    where all three are in view.
    """
    projects.get(project_id)  # raises ProjectNotFoundError before anything moves
    items.unassign_project(project_id)
    log.delete_for_project(project_id)
    projects.delete(project_id)


def log_project_update(
    log: ProjectLogStore,
    project_id: ProjectId,
    body: str,
) -> ProjectUpdate:
    return log.append(project_id, UpdateBody(body))


def delete_project_update(
    log: ProjectLogStore,
    update_id: UpdateId,
) -> None:
    log.delete(update_id)
