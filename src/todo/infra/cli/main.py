from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone

import click

from todo.adapters.sqlite_counter_store import SqliteCounterStore
from todo.adapters.sqlite_dependency_store import SqliteDependencyStore
from todo.adapters.sqlite_item_store import SqliteItemStore
from todo.adapters.sqlite_project_log_store import SqliteProjectLogStore
from todo.adapters.sqlite_project_store import SqliteProjectStore
from todo.application.queries.find_project import FindProject
from todo.application.queries.list_projects import ListProjects
from todo.application.queries.list_tags import ListTags
from todo.application.queries.list_todos import ListTodos
from todo.application.queries.load_dependencies import DoneIds, LoadDependencies
from todo.application.queries.project_names import LoadProjectNames
from todo.application.queries.show_project import ShowProject
from todo.application.queries.show_project_update import ShowProjectUpdate
from todo.application.queries.show_todo import ShowTodo
from todo.application.queries.summarize import Summarize
from todo.application.toast import Toast
from todo.application.workflows.add_blocker import AddBlocker
from todo.application.workflows.create_project import CreateProject
from todo.application.workflows.create_project_update import CreateProjectUpdate
from todo.application.workflows.create_todo import CreateTodo
from todo.application.workflows.delete_project import DeleteProject
from todo.application.workflows.delete_project_update import DeleteProjectUpdate
from todo.application.workflows.delete_todo import DeleteTodo
from todo.application.workflows.edit_project import EditProject
from todo.application.workflows.edit_todo import EditTodo
from todo.application.workflows.remove_blocker import RemoveBlocker
from todo.application.workflows.set_project_status import SetProjectStatus
from todo.application.workflows.set_status import SetStatus
from todo.application.workflows.take_item_id import TakeItemId
from todo.application.workflows.take_project_id import TakeProjectId
from todo.application.workflows.take_update_id import TakeUpdateId
from todo.config import get_db_path
from todo.domain.body import Body
from todo.domain.deadline import Deadline
from todo.domain.description import Description
from todo.domain.item_filter import ItemFilter
from todo.domain.item_id import ItemId
from todo.domain.moment import Moment
from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.project_filter import ProjectFilter
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName
from todo.domain.project_ref import ProjectRef
from todo.domain.project_status import ProjectStatus
from todo.domain.project_update import ProjectUpdate
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.title import Title
from todo.domain.todo_item import TodoItem
from todo.domain.update_body import UpdateBody
from todo.domain.update_id import UpdateId
from todo.exceptions import (
    DependencyError,
    DuplicateProjectError,
    NotFoundError,
    ProjectNotFoundError,
    StorageError,
    UpdateNotFoundError,
)
from todo.infra.cli.output import create_output

_PRIORITY_CHOICES = [p.value for p in Priority]
_STATUS_CHOICES = [s.value for s in Status]

# What --deadline, --tag and --project accept to mean "empty this". A fact
# about the flags, not about deadlines, tags or projects.
_CLEAR = "none"


def _items() -> SqliteItemStore:
    return SqliteItemStore(get_db_path())


def _projects() -> SqliteProjectStore:
    return SqliteProjectStore(get_db_path())


def _dependencies() -> SqliteDependencyStore:
    return SqliteDependencyStore(get_db_path())


def _log() -> SqliteProjectLogStore:
    return SqliteProjectLogStore(get_db_path())


def _item_ids() -> SqliteCounterStore:
    return SqliteCounterStore(get_db_path(), "items")


def _project_ids() -> SqliteCounterStore:
    return SqliteCounterStore(get_db_path(), "projects")


def _update_ids() -> SqliteCounterStore:
    return SqliteCounterStore(get_db_path(), "project_updates")


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _report(items: SqliteItemStore, toasts: list[Toast]) -> None:
    """A toast carries ids; the wording is this frontend's.

    The title is looked up here rather than carried along, because which
    item it is, is the fact — what to call it on screen is not.
    """
    for toast in toasts:
        for item_id in toast.items:
            try:
                named = f"{item_id.label} {ShowTodo(items).execute(item_id).title}"
            except NotFoundError:
                # Deleted between the write and this line: still worth
                # saying that it is no longer held up.
                named = item_id.label
            click.echo(f"🔓 {named} is now unblocked", err=True)


def _parse_since_or_exit(value: str) -> datetime:
    """Turn '7 days', '2 weeks' or '2026-04-01' into a moment.

    Argument parsing, so it lives with the argument.
    """
    parts = value.strip().split()
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
                # A negative amount would silently build an inverted
                # future window and report "no items" as a valid summary.
                raise ValueError(f"Cannot parse '{value}': amount must be positive.")
            try:
                return _now() - timedelta(days=amount * days_per_unit)
            except OverflowError:
                # Overflow is not a ValueError, but to whoever typed it
                # this is the same malformed --since.
                raise ValueError(f"Cannot parse '{value}': amount too large.") from None
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    raise ValueError(
        f"Cannot parse '{value}'. Use a relative duration like '7 days' "
        "or an ISO date like '2025-04-01'."
    )


def _parse_deadline_or_exit(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        click.echo(f"Invalid deadline '{value}'. Use YYYY-MM-DD.", err=True)
        sys.exit(1)


def _to_tags(raw: tuple[str, ...]) -> frozenset[Tag]:
    """Typed tags become the domain's. 'none' is this flag's way of
    saying "no tags", so a tag by that name could never be reached."""
    tags: set[Tag] = set()
    for value in raw:
        tag = Tag(value)
        if tag.lower() == _CLEAR:
            raise ValueError(f"'{_CLEAR}' is a reserved tag name.")
        tags.add(tag)
    return frozenset(tags)


def _to_project_name(value: str) -> ProjectName:
    # Same as tags: 'none' is what --project takes to mean "no project",
    # so a project by that name would be unreachable from edit.
    name = ProjectName(value)
    if name.lower() == _CLEAR:
        raise ValueError(f"'{_CLEAR}' is a reserved project name.")
    return name


def _resolve_project_obj_or_exit(projects: SqliteProjectStore, ref: str) -> Project:
    try:
        return FindProject(projects).execute(ProjectRef(ref))
    except ProjectNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


def _resolve_project_or_exit(projects: SqliteProjectStore, ref: str) -> ProjectId:
    return _resolve_project_obj_or_exit(projects, ref).id


class _SafeGroup(click.Group):
    """Report database-level failures cleanly instead of tracebacks."""

    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        # StorageError only: the adapter's contract is that every
        # database-level failure is wrapped — catching raw driver
        # exceptions here would paper over contract gaps that still
        # crash the TUI.
        except StorageError as e:
            click.echo(f"Database error: {e}", err=True)
            sys.exit(1)


@click.group(cls=_SafeGroup)
def main() -> None:
    """A persistent, SQLite-backed todo app."""


@main.command()
@click.argument("title")
@click.option(
    "--priority",
    "-p",
    type=click.Choice(_PRIORITY_CHOICES, case_sensitive=False),
    default="medium",
)
@click.option(
    "--status",
    "-s",
    type=click.Choice(_STATUS_CHOICES, case_sensitive=False),
    default="todo",
)
@click.option("--body", "-b", default="")
@click.option("--deadline", "-d", default=None, help="Due date (YYYY-MM-DD)")
@click.option("--tag", "-t", multiple=True, help="Tag (repeatable)")
@click.option("--project", "project_ref", default=None, help="Project name or id")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def add(
    title: str,
    priority: str,
    status: str,
    body: str,
    deadline: str | None,
    tag: tuple[str, ...],
    project_ref: str | None,
    as_json: bool,
) -> None:
    """Add a new todo item."""
    items = _items()
    dependencies = _dependencies()
    projects = _projects()
    out = create_output()
    dl = _parse_deadline_or_exit(deadline) if deadline else None
    project_id = (
        _resolve_project_or_exit(projects, project_ref)
        if project_ref is not None
        else None
    )
    try:
        stamp = _now()
        item = TodoItem(
            id=TakeItemId(_item_ids()).execute(),
            title=Title(title),
            body=Body(body),
            priority=Priority.from_string(priority),
            status=Status.TODO,
            created_at=stamp,
            updated_at=stamp,
            deadline=Deadline.from_date(dl) if dl else None,
            tags=_to_tags(tag),
            project_id=project_id,
        )
        # Through the item's own method, so the completion stamp is the
        # domain's answer and not something spelled out again here.
        chosen = Status.from_string(status)
        if chosen is not Status.TODO:
            item.set_status(chosen)
        CreateTodo(items).execute(item)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_item(item, graph, done, LoadProjectNames(projects).execute())
    else:
        out.print_item(item, graph, done, LoadProjectNames(projects).execute())


@main.command("list")
@click.option(
    "--status",
    "-s",
    type=click.Choice(_STATUS_CHOICES, case_sensitive=False),
    default=None,
)
@click.option(
    "--priority",
    "-p",
    type=click.Choice(_PRIORITY_CHOICES, case_sensitive=False),
    default=None,
)
@click.option("--tag", "-t", multiple=True, help="Filter by tag (repeatable, AND)")
@click.option("--search", default=None, help="Match text in title or body")
@click.option("--project", "project_ref", default=None, help="Project name or id")
@click.option("--all", "include_all", is_flag=True, help="Include done items")
@click.option("--blocked", is_flag=True, help="Only blocked items")
@click.option(
    "--ready", is_flag=True, help="Only actionable items (not done, not blocked)"
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def list_cmd(
    status: str | None,
    priority: str | None,
    tag: tuple[str, ...],
    search: str | None,
    project_ref: str | None,
    include_all: bool,
    blocked: bool,
    ready: bool,
    as_json: bool,
) -> None:
    """List todo items."""
    if blocked and ready:
        raise click.UsageError("--blocked and --ready are mutually exclusive.")
    items = _items()
    dependencies = _dependencies()
    projects = _projects()
    out = create_output()
    project_id = (
        _resolve_project_or_exit(projects, project_ref)
        if project_ref is not None
        else None
    )
    try:
        # Stored tags are normalized by Tag at the write boundary, so a
        # filter built the same way is the only one that can match them.
        found = ListTodos(items).execute(
            ItemFilter(
                status=Status.from_string(status) if status else None,
                priority=Priority.from_string(priority) if priority else None,
                tags=frozenset(Tag(t) for t in tag),
                text=search,
                project_id=project_id,
                include_done=include_all,
            )
        )
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if blocked or ready:
        # Blocked-ness is the graph's answer, asked per item.
        found = [
            i
            for i in found
            if graph.is_blocked(i.id, done) == blocked and (blocked or not i.is_done)
        ]
    if as_json:
        out.print_json_list(found, graph, done, LoadProjectNames(projects).execute())
    else:
        out.print_list(found, graph, done)


@main.command()
@click.argument("item_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def show(item_id: int, as_json: bool) -> None:
    """Show details for a todo item."""
    items = _items()
    dependencies = _dependencies()
    projects = _projects()
    out = create_output()
    try:
        item = ShowTodo(items).execute(ItemId(item_id))
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_item(item, graph, done, LoadProjectNames(projects).execute())
    else:
        out.print_item(item, graph, done, LoadProjectNames(projects).execute())


@main.command()
@click.argument("item_id", type=int)
@click.option("--title", default=None)
@click.option("--body", default=None)
@click.option(
    "--priority",
    "-p",
    type=click.Choice(_PRIORITY_CHOICES, case_sensitive=False),
    default=None,
)
@click.option(
    "--status",
    "-s",
    type=click.Choice(_STATUS_CHOICES, case_sensitive=False),
    default=None,
)
@click.option("--deadline", "-d", default=None, help="Due date (YYYY-MM-DD or 'none')")
@click.option(
    "--tag",
    "-t",
    multiple=True,
    help="Replace tags (repeatable), or 'none' to clear them",
)
@click.option(
    "--project", "project_ref", default=None, help="Project name or id, or 'none'"
)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def edit(
    item_id: int,
    title: str | None,
    body: str | None,
    priority: str | None,
    status: str | None,
    deadline: str | None,
    tag: tuple[str, ...],
    project_ref: str | None,
    as_json: bool,
) -> None:
    """Edit a todo item."""
    items = _items()
    dependencies = _dependencies()
    projects = _projects()
    out = create_output()

    # A flag that was not given is a flag this never touches: the item is
    # changed through its own methods, so there is no sentinel standing
    # in for the difference between leaving a field alone and emptying it.
    toasts: list[Toast] = []
    try:
        item = ShowTodo(items).execute(ItemId(item_id))
        if title is not None:
            item.set_title(Title(title))
        if body is not None:
            item.set_body(Body(body))
        if priority is not None:
            item.set_priority(Priority.from_string(priority))
        if deadline is not None:
            item.set_deadline(
                None
                if deadline.lower() == _CLEAR
                else Deadline.from_date(_parse_deadline_or_exit(deadline))
            )
        if tag:
            wanted = (
                frozenset[Tag]()
                if len(tag) == 1 and tag[0].lower() == _CLEAR
                else _to_tags(tag)
            )
            for gone in item.tags - wanted:
                item.remove_tag(gone)
            for added in wanted - item.tags:
                item.add_tag(added)
        if project_ref is not None:
            item.set_project_id(
                None
                if project_ref.lower() == _CLEAR
                else _resolve_project_or_exit(projects, _to_project_name(project_ref))
            )
        EditTodo(items).execute(item)
        if status is not None:
            # Last, so what is printed is the item as it finally stands
            # and the toast is made against that.
            toasts = SetStatus(items, dependencies).execute(
                ItemId(item_id), Status.from_string(status)
            )
        edited = ShowTodo(items).execute(ItemId(item_id))
    except (NotFoundError, ValueError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    _report(items, toasts)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_item(edited, graph, done, LoadProjectNames(projects).execute())
    else:
        out.print_item(edited, graph, done, LoadProjectNames(projects).execute())


@main.command()
@click.argument("item_id", type=int)
@click.argument("status", type=click.Choice(_STATUS_CHOICES, case_sensitive=False))
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def mv(item_id: int, status: str, as_json: bool) -> None:
    """Move a todo item to a new status."""
    items = _items()
    dependencies = _dependencies()
    projects = _projects()
    out = create_output()
    try:
        toasts = SetStatus(items, dependencies).execute(
            ItemId(item_id), Status.from_string(status)
        )
        result_item = ShowTodo(items).execute(ItemId(item_id))
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    _report(items, toasts)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_item(
            result_item, graph, done, LoadProjectNames(projects).execute()
        )
    else:
        out.print_item(result_item, graph, done, LoadProjectNames(projects).execute())


@main.command()
@click.argument("item_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def done(item_id: int, as_json: bool) -> None:
    """Mark a todo item as done."""
    items = _items()
    dependencies = _dependencies()
    projects = _projects()
    out = create_output()
    try:
        toasts = SetStatus(items, dependencies).execute(ItemId(item_id), Status.DONE)
        result_item = ShowTodo(items).execute(ItemId(item_id))
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    _report(items, toasts)
    graph = LoadDependencies(dependencies).execute()
    done_ids = DoneIds(items).execute()
    if as_json:
        out.print_json_item(
            result_item, graph, done_ids, LoadProjectNames(projects).execute()
        )
    else:
        out.print_item(
            result_item, graph, done_ids, LoadProjectNames(projects).execute()
        )


@main.command()
@click.argument("item_id", type=int)
def rm(item_id: int) -> None:
    """Delete a todo item."""
    items = _items()
    dependencies = _dependencies()
    out = create_output()
    try:
        toasts = DeleteTodo(items, dependencies).execute(ItemId(item_id))
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    _report(items, toasts)
    out.print_deleted(item_id)


@main.command("summary")
@click.option("--since", required=True, help="'7 days', '2 weeks', or '2025-04-01'")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def summary_cmd(since: str, as_json: bool) -> None:
    """Show a summary of completed items."""
    items = _items()
    dependencies = _dependencies()
    projects = _projects()
    out = create_output()
    try:
        since_dt = _parse_since_or_exit(since)
        finished = Summarize(items).execute(Moment.from_datetime(since_dt))
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_summary(
            since_dt, finished, graph, done, LoadProjectNames(projects).execute()
        )
    else:
        out.print_summary(since_dt, finished, graph, done)


@main.command()
@click.argument("item_id", type=int)
@click.argument("blocker_ids", type=int, nargs=-1, required=True)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def block(item_id: int, blocker_ids: tuple[int, ...], as_json: bool) -> None:
    """Mark ITEM_ID as blocked by the given blocker item(s), all-or-nothing."""
    items = _items()
    dependencies = _dependencies()
    projects = _projects()
    out = create_output()
    try:
        AddBlocker(items, dependencies).execute(
            ItemId(item_id), [ItemId(b) for b in blocker_ids]
        )
        item = ShowTodo(items).execute(ItemId(item_id))
    except (NotFoundError, DependencyError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_item(item, graph, done, LoadProjectNames(projects).execute())
    else:
        out.print_item(item, graph, done, LoadProjectNames(projects).execute())


@main.command()
@click.argument("item_id", type=int)
@click.argument("blocker_ids", type=int, nargs=-1, required=True)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def unblock(item_id: int, blocker_ids: tuple[int, ...], as_json: bool) -> None:
    """Remove the given blocker item(s) from ITEM_ID."""
    items = _items()
    dependencies = _dependencies()
    projects = _projects()
    out = create_output()
    try:
        toasts = RemoveBlocker(items, dependencies).execute(
            ItemId(item_id), [ItemId(b) for b in blocker_ids]
        )
        item = ShowTodo(items).execute(ItemId(item_id))
    except (NotFoundError, DependencyError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    _report(items, toasts)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_item(item, graph, done, LoadProjectNames(projects).execute())
    else:
        out.print_item(item, graph, done, LoadProjectNames(projects).execute())


@main.group()
def project() -> None:
    """Manage projects."""


@project.command("add")
@click.argument("name")
@click.option("--description", "-D", default="", help="Project description")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_add(name: str, description: str, as_json: bool) -> None:
    """Create a new project."""
    projects = _projects()
    items = _items()
    log = _log()
    dependencies = _dependencies()
    out = create_output()
    try:
        stamp = _now()
        created = Project(
            id=TakeProjectId(_project_ids()).execute(),
            name=_to_project_name(name),
            description=Description(description),
            created_at=stamp,
            updated_at=stamp,
        )
        CreateProject(projects).execute(created)
    except (DuplicateProjectError, ValueError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    detail = ShowProject(projects, items, log).execute(created.id)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_project(
            detail, graph, done, LoadProjectNames(projects).execute()
        )
    else:
        out.print_project(detail, graph, done, LoadProjectNames(projects).execute())


@project.command("list")
@click.option("--all", "include_ended", is_flag=True, help="Include cancelled and done")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_list(include_ended: bool, as_json: bool) -> None:
    """List projects with open/done counts."""
    projects = _projects()
    items = _items()
    out = create_output()
    summaries = ListProjects(projects, items).execute(
        ProjectFilter(include_ended=include_ended)
    )
    if as_json:
        out.print_json_projects(summaries)
    else:
        out.print_projects(summaries)


@project.command("show")
@click.argument("ref")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_show(ref: str, as_json: bool) -> None:
    """Show a project (by name or id) and its items."""
    projects = _projects()
    items = _items()
    log = _log()
    dependencies = _dependencies()
    out = create_output()
    project_id = _resolve_project_or_exit(projects, ref)
    try:
        detail = ShowProject(projects, items, log).execute(project_id)
    except ProjectNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_project(
            detail, graph, done, LoadProjectNames(projects).execute()
        )
    else:
        out.print_project(detail, graph, done, LoadProjectNames(projects).execute())


@project.command("edit")
@click.argument("ref")
@click.option("--name", default=None, help="New name")
@click.option("--description", "-D", default=None, help="New description")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_edit(
    ref: str, name: str | None, description: str | None, as_json: bool
) -> None:
    """Edit a project's name or description."""
    projects = _projects()
    items = _items()
    log = _log()
    dependencies = _dependencies()
    out = create_output()
    target = _resolve_project_obj_or_exit(projects, ref)
    try:
        if name is not None:
            target.set_name(_to_project_name(name))
        if description is not None:
            target.set_description(Description(description))
        EditProject(projects).execute(target)
    except (DuplicateProjectError, ValueError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    detail = ShowProject(projects, items, log).execute(target.id)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_project(
            detail, graph, done, LoadProjectNames(projects).execute()
        )
    else:
        out.print_project(detail, graph, done, LoadProjectNames(projects).execute())


@project.command("status")
@click.argument("ref")
@click.argument("status")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_status_cmd(ref: str, status: str, as_json: bool) -> None:
    """Set a project's status: not-started, in-progress, cancelled, done."""
    projects = _projects()
    items = _items()
    log = _log()
    dependencies = _dependencies()
    out = create_output()
    project_id = _resolve_project_or_exit(projects, ref)
    try:
        new_status = ProjectStatus.from_string(status)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    SetProjectStatus(projects).execute(project_id, new_status)
    detail = ShowProject(projects, items, log).execute(project_id)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_project(
            detail, graph, done, LoadProjectNames(projects).execute()
        )
    else:
        out.print_project(detail, graph, done, LoadProjectNames(projects).execute())


@project.group("log")
def project_log() -> None:
    """Read and write a project's log."""


@project_log.command("add")
@click.argument("ref")
@click.argument("text")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_log_add(ref: str, text: str, as_json: bool) -> None:
    """Append a timestamped update to a project's log."""
    projects = _projects()
    items = _items()
    log = _log()
    dependencies = _dependencies()
    out = create_output()
    proj = _resolve_project_obj_or_exit(projects, ref)
    try:
        CreateProjectUpdate(projects, log).execute(
            ProjectUpdate(
                id=TakeUpdateId(_update_ids()).execute(),
                project_id=proj.id,
                body=UpdateBody(text),
                created_at=_now(),
            )
        )
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    detail = ShowProject(projects, items, log).execute(proj.id)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_project(
            detail, graph, done, LoadProjectNames(projects).execute()
        )
    else:
        out.print_project(detail, graph, done, LoadProjectNames(projects).execute())


@project_log.command("rm")
@click.argument("update_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_log_rm(update_id: int, as_json: bool) -> None:
    """Delete one log entry by the id shown in `project show`."""
    projects = _projects()
    items = _items()
    log = _log()
    dependencies = _dependencies()
    out = create_output()
    try:
        # Read it first: which project to show afterwards is the entry's
        # own answer, and it stops being available once it is gone.
        entry = ShowProjectUpdate(log).execute(UpdateId(update_id))
        DeleteProjectUpdate(log).execute(entry.id)
    except UpdateNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    detail = ShowProject(projects, items, log).execute(entry.project_id)
    graph = LoadDependencies(dependencies).execute()
    done = DoneIds(items).execute()
    if as_json:
        out.print_json_project(
            detail, graph, done, LoadProjectNames(projects).execute()
        )
    else:
        out.print_project(detail, graph, done, LoadProjectNames(projects).execute())


@project.command("rm")
@click.argument("ref")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_rm(ref: str, as_json: bool) -> None:
    """Delete a project; its items survive unassigned."""
    projects = _projects()
    items = _items()
    log = _log()
    # Read the record before deleting it: --json reports what was removed.
    target = _resolve_project_obj_or_exit(projects, ref)
    DeleteProject(projects, items, log).execute(target.id)
    if as_json:
        create_output().print_json_deleted_project(target)
    else:
        click.echo(f"Deleted project #{target.id}. Items were unassigned.")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def tags(as_json: bool) -> None:
    """List all tags with usage counts."""
    items = _items()
    out = create_output()
    counts = ListTags(items).execute()
    if as_json:
        out.print_json_tags(counts)
    else:
        out.print_tags(counts)


@main.command()
def ui() -> None:
    """Launch the interactive TUI."""
    from todo.tui.app import TodoApp

    app = TodoApp()
    app.run()
