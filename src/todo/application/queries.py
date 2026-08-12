from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from todo.application.contracts.storage import StorageProtocol
from todo.domain.enums import Priority, Status
from todo.domain.models import Project, ProjectUpdate, TodoItem
from todo.domain.tags import split_tags
from todo.exceptions import ProjectNotFoundError


def list_todos(
    storage: StorageProtocol,
    *,
    status: Status | None = None,
    priority: Priority | None = None,
    tags: list[str] | None = None,
    search: str | None = None,
    project_id: int | None = None,
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
    if tags is not None:
        cleaned: list[str] = []
        for tag in tags:
            stripped = tag.strip()
            if not stripped:
                raise ValueError("Tag filter cannot be empty.")
            if "," in stripped:
                raise ValueError(
                    f"Tag filter '{stripped}' contains a comma; "
                    "use separate --tag flags."
                )
            cleaned.append(stripped)
        tags = cleaned
    items = storage.list(
        status=status,
        priority=priority,
        tags=tags,
        search=search,
        project_id=project_id,
        include_done=include_done,
    )
    if blocked:
        items = [i for i in items if i.is_blocked]
    elif ready:
        items = [i for i in items if not i.is_blocked and not i.is_done]
    return items


def show_todo(
    storage: StorageProtocol,
    item_id: int,
) -> TodoItem:
    return storage.get(item_id)


def resolve_project(storage: StorageProtocol, ref: str) -> Project:
    """Resolve a project reference.

    Numeric refs mean the id shown in `project list` (falling back to a
    project literally named so); anything else is a name. Id must win for
    numeric refs — name-first resolution let a numerically-named project
    shadow another project's id in every command, including `project rm`.
    """
    # Refs get the same whitespace normalization the write path applied to
    # names — the exact string a project was created with must resolve.
    ref = " ".join(ref.split())
    # isdecimal (not isdigit: '²'.isdigit() is True but int('²') raises) and
    # a length cap (SQLite binds 64-bit ints) decide what counts as an id.
    if ref.isdecimal() and len(ref) <= 18:
        try:
            return storage.get_project(int(ref))
        except ProjectNotFoundError:
            return storage.get_project_by_name(ref)
    return storage.get_project_by_name(ref)


@dataclass(frozen=True)
class ProjectSummary:
    project: Project
    open_count: int
    done_count: int


def list_projects(
    storage: StorageProtocol,
    *,
    include_archived: bool = False,
) -> list[ProjectSummary]:
    counts = storage.project_counts()
    return [
        ProjectSummary(
            project=p,
            open_count=counts.get(p.id, (0, 0))[0],
            done_count=counts.get(p.id, (0, 0))[1],
        )
        for p in storage.list_projects(include_archived=include_archived)
    ]


def list_all_projects(
    storage: StorageProtocol,
    *,
    include_archived: bool = False,
) -> list[Project]:
    """Projects without count computation — for hot paths that only need
    names/ids (TUI filter cycling and resolution)."""
    return storage.list_projects(include_archived=include_archived)


@dataclass(frozen=True)
class ProjectDetail:
    project: Project
    items: list[TodoItem]
    updates: list[ProjectUpdate]


def project_detail(
    storage: StorageProtocol,
    project: Project,
) -> ProjectDetail:
    """Detail for an already-resolved project — items (done included) + log.

    Callers that hold a Project must use this instead of re-resolving via a
    ref string: name-first resolution could pick a different project whose
    name happens to equal this project's numeric id.
    """
    return ProjectDetail(
        project=project,
        items=storage.list(project_id=project.id, include_done=True),
        updates=storage.list_project_updates(project.id),
    )


def show_project(
    storage: StorageProtocol,
    ref: str,
) -> ProjectDetail:
    """A project plus all of its items (done included) and its update log."""
    return project_detail(storage, resolve_project(storage, ref))


def count_tags(storage: StorageProtocol) -> list[tuple[str, int]]:
    """All tags with usage counts (done items included), most used first."""
    counts: dict[str, int] = {}
    for raw in storage.tag_strings():
        for tag in split_tags(raw):
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
    storage: StorageProtocol,
    since: str,
) -> tuple[datetime, list[TodoItem]]:
    since_dt = parse_since(since)
    items = storage.done_since(since_dt)
    return since_dt, items
