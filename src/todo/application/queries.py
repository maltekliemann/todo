from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from todo.application.contracts.storage import StorageProtocol
from todo.domain.enums import Priority, Status
from todo.domain.models import Project, ProjectUpdate, TodoItem
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
    """Resolve a project by name, falling back to id for numeric refs."""
    try:
        return storage.get_project_by_name(ref)
    except ProjectNotFoundError:
        if ref.isdigit():
            return storage.get_project(int(ref))
        raise


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
    items = storage.list(include_done=True)
    open_counts: dict[int, int] = {}
    done_counts: dict[int, int] = {}
    for item in items:
        if item.project_id is None:
            continue
        bucket = done_counts if item.is_done else open_counts
        bucket[item.project_id] = bucket.get(item.project_id, 0) + 1
    return [
        ProjectSummary(
            project=p,
            open_count=open_counts.get(p.id, 0),
            done_count=done_counts.get(p.id, 0),
        )
        for p in storage.list_projects(include_archived=include_archived)
    ]


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
    for item in storage.list(include_done=True):
        for tag in item.tags:
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
            if unit == "day":
                return datetime.now(tz=ZoneInfo("UTC")) - timedelta(days=amount)
            if unit == "week":
                return datetime.now(tz=ZoneInfo("UTC")) - timedelta(weeks=amount)
            if unit == "month":
                return datetime.now(tz=ZoneInfo("UTC")) - timedelta(days=amount * 30)
            raise ValueError(f"Unknown time unit: '{unit}'")

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
