from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemQuery, ItemStore
from todo.application.contracts.project_log_store import ProjectLogStore
from todo.application.contracts.project_store import ProjectStore
from todo.application.dependencies import Dependencies
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName
from todo.domain.project_update import ProjectUpdate
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.todo_item import TodoItem
from todo.exceptions import ProjectNotFoundError


def list_todos(
    items: ItemStore,
    dependencies: DependencyStore,
    *,
    status: Status | None = None,
    priority: Priority | None = None,
    tags: list[str] | None = None,
    search: str | None = None,
    project_id: ProjectId | None = None,
    include_done: bool = False,
    blocked: bool = False,
    ready: bool = False,
) -> list[TodoItem]:
    if blocked and ready:
        raise ValueError("'blocked' and 'ready' are mutually exclusive.")
    # Stored tags are stripped at the write boundary; filters must apply
    # the same normalization or the same input silently matches nothing.
    # A filter no stored tag could ever equal (blank, or containing the
    # comma delimiter) is an error — never a silent no-filter or an
    # adjacency match against the raw column.
    wanted: set[Tag] = set()
    if tags is not None:
        for tag in tags:
            # Normalized by Tag itself, not by a lookalike: a filter that
            # normalizes differently from the write path cannot match the
            # exact string that created the tag.
            try:
                normalized = Tag(tag)
            except ValueError as exc:
                raise ValueError(f"Cannot filter by that tag: {exc}") from None
            wanted.add(normalized)
    found = items.find(
        ItemQuery(
            status=status,
            priority=priority,
            tags=frozenset(wanted),
            text=search,
            project_id=project_id,
            include_done=include_done,
        )
    )
    if blocked or ready:
        # Blocked-ness is the graph's answer, not a column: load it once
        # for the whole page rather than per item.
        deps = Dependencies.load(items, dependencies)
        if blocked:
            return [i for i in found if deps.is_blocked(i.id)]
        return [i for i in found if not deps.is_blocked(i.id) and not i.is_done]
    return found


def show_todo(
    items: ItemStore,
    item_id: ItemId,
) -> TodoItem:
    return items.get(item_id)


def resolve_project(projects: ProjectStore, ref: str) -> Project:
    """Resolve a project reference.

    Numeric refs mean the id shown in `project list` (falling back to a
    project literally named so); anything else is a name. Id must win for
    numeric refs — name-first resolution let a numerically-named project
    shadow another project's id in every command, including `project rm`.
    """
    # Normalized by ProjectName itself, not by a lookalike: the exact
    # string a project was created with has to resolve to it. A ref that
    # is not a nameable string names no project.
    try:
        ref = ProjectName(ref)
    except ValueError:
        raise ProjectNotFoundError(ref) from None
    # isdecimal (not isdigit: '²'.isdigit() is True but int('²') raises) and
    # a length cap (SQLite binds 64-bit ints) decide what counts as an id.
    if ref.isdecimal() and len(ref) <= 18:
        try:
            return projects.get(ProjectId(int(ref)))
        except ProjectNotFoundError:
            return projects.get_by_name(ref)
    return projects.get_by_name(ref)


@dataclass(frozen=True)
class ProjectSummary:
    project: Project
    open_count: int
    done_count: int


def list_projects(
    projects: ProjectStore,
    items: ItemStore,
    *,
    include_ended: bool = False,
) -> list[ProjectSummary]:
    counts = items.counts_by_project()
    return [
        ProjectSummary(
            project=p,
            open_count=counts[p.id].open if p.id in counts else 0,
            done_count=counts[p.id].done if p.id in counts else 0,
        )
        for p in projects.find_all(include_ended=include_ended)
    ]


def list_all_projects(
    projects: ProjectStore,
    *,
    include_ended: bool = False,
) -> list[Project]:
    """Projects without count computation — for hot paths that only need
    names/ids (TUI filter cycling and resolution)."""
    return projects.find_all(include_ended=include_ended)


# A page of items shows project names; the items only name ids.
ProjectNames = dict[ProjectId, ProjectName]


def project_names(projects: ProjectStore) -> ProjectNames:
    """Every project's name by id, for views that show items.

    An item names its project by identity, so whoever renders one has to
    look the name up. Once for a whole page, not once per item.
    """
    return {p.id: p.name for p in projects.find_all(include_ended=True)}


@dataclass(frozen=True)
class ProjectDetail:
    project: Project
    items: list[TodoItem]
    updates: list[ProjectUpdate]


def project_detail(
    items: ItemStore,
    log: ProjectLogStore,
    project: Project,
) -> ProjectDetail:
    """Detail for an already-resolved project — items (done included) + log.

    Callers that hold a Project must use this instead of re-resolving via a
    ref string: name-first resolution could pick a different project whose
    name happens to equal this project's numeric id.
    """
    return ProjectDetail(
        project=project,
        items=items.find(ItemQuery(project_id=project.id, include_done=True)),
        updates=log.entries_for(project.id),
    )


def show_project(
    projects: ProjectStore,
    items: ItemStore,
    log: ProjectLogStore,
    ref: str,
) -> ProjectDetail:
    """A project plus all of its items (done included) and its update log."""
    return project_detail(items, log, resolve_project(projects, ref))


def count_tags(items: ItemStore) -> list[tuple[str, int]]:
    """All tags with usage counts (done items included), most used first."""
    counts: dict[str, int] = {}
    for tags in items.tags_of_every_item():
        for tag in tags:
            counts[tag] = counts.get(tag, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


def parse_since(since: str) -> datetime:
    """Parse a --since value into a datetime.

    Accepts either:
      - A relative duration like "7 days", "2 weeks", "1 month"
      - An ISO date like "2025-04-01"
    """
    parts = since.strip().split()
    if len(parts) == 2:
        amount_str, unit = parts
        try:
            amount = int(amount_str)
        except ValueError:
            pass
        else:
            unit = unit.lower().rstrip("s")  # "days" -> "day"
            days_per_unit = {"day": 1, "week": 7, "month": 30}.get(unit)
            if days_per_unit is None:
                raise ValueError(f"Unknown time unit: '{unit}'")
            if amount < 1:
                # A negative amount would silently build an inverted future
                # window that reports "no items" as a valid empty summary.
                raise ValueError(f"Cannot parse '{since}': amount must be positive.")
            try:
                return datetime.now(tz=ZoneInfo("UTC")) - timedelta(
                    days=amount * days_per_unit
                )
            except OverflowError:
                # timedelta/datetime overflow is not ValueError, but to the
                # caller it's the same malformed --since input.
                raise ValueError(f"Cannot parse '{since}': amount too large.") from None

    # Try ISO date
    try:
        dt = datetime.strptime(since, "%Y-%m-%d")
        return dt.replace(tzinfo=ZoneInfo("UTC"))
    except ValueError:
        pass

    raise ValueError(
        f"Cannot parse '{since}'. Use a relative duration like '7 days' "
        "or an ISO date like '2025-04-01'."
    )


def summary(
    items: ItemStore,
    since: str,
) -> tuple[datetime, list[TodoItem]]:
    since_dt = parse_since(since)
    return since_dt, items.done_since(since_dt)
