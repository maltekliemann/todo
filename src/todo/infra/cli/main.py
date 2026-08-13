from __future__ import annotations

import sys
from datetime import date

import click

from todo.adapters.output import create_output
from todo.adapters.sqlite_dependency_store import SqliteDependencyStore
from todo.adapters.sqlite_item_store import SqliteItemStore
from todo.adapters.sqlite_project_log_store import SqliteProjectLogStore
from todo.adapters.sqlite_project_store import SqliteProjectStore
from todo.application.commands import (
    add_project,
    add_todo,
    block_todo_batch,
    complete_todo,
    delete_project,
    delete_project_update,
    delete_todo,
    edit_project,
    edit_todo,
    log_project_update,
    move_todo,
    set_project_status,
    unblock_todo_batch,
)
from todo.application.dependencies import Dependencies
from todo.application.queries import (
    count_tags,
    list_projects,
    list_todos,
    project_detail,
    project_names,
    resolve_project,
    show_project,
    show_todo,
    summary,
)
from todo.application.unset import UNSET, Unset
from todo.config import get_db_path
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.project_id import ProjectId
from todo.domain.project_status import ProjectStatus
from todo.domain.status import Status
from todo.domain.todo_item import TodoItem
from todo.domain.update_id import UpdateId
from todo.exceptions import (
    DependencyError,
    DuplicateProjectError,
    NotFoundError,
    ProjectNotFoundError,
    StorageError,
    UpdateNotFoundError,
)

_PRIORITY_CHOICES = [p.value for p in Priority]
_STATUS_CHOICES = [s.value for s in Status]


def _items() -> SqliteItemStore:
    return SqliteItemStore(get_db_path())


def _projects() -> SqliteProjectStore:
    return SqliteProjectStore(get_db_path())


def _dependencies() -> SqliteDependencyStore:
    return SqliteDependencyStore(get_db_path())


def _log() -> SqliteProjectLogStore:
    return SqliteProjectLogStore(get_db_path())


def _warn_unblocked(unblocked: list[TodoItem]) -> None:
    for dep in unblocked:
        click.echo(f"🔓 #{dep.id} {dep.title} is now unblocked", err=True)


def _parse_deadline_or_exit(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        click.echo(f"Invalid deadline '{value}'. Use YYYY-MM-DD.", err=True)
        sys.exit(1)


def _resolve_project_obj_or_exit(projects: SqliteProjectStore, ref: str) -> Project:
    try:
        return resolve_project(projects, ref)
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
        item = add_todo(
            items,
            title,
            body=body,
            priority=Priority.from_string(priority),
            status=Status.from_string(status),
            deadline=dl,
            tags=list(tag) if tag else None,
            project_id=project_id,
        )
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_item(item, deps, project_names(projects))
    else:
        out.print_item(item, deps, project_names(projects))


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
        found = list_todos(
            items,
            dependencies,
            status=Status.from_string(status) if status else None,
            priority=Priority.from_string(priority) if priority else None,
            tags=list(tag) if tag else None,
            search=search,
            project_id=project_id,
            include_done=include_all,
            blocked=blocked,
            ready=ready,
        )
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_list(found, deps, project_names(projects))
    else:
        out.print_list(found, deps)


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
        item = show_todo(items, ItemId(item_id))
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_item(item, deps, project_names(projects))
    else:
        out.print_item(item, deps, project_names(projects))


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

    dl: date | None | Unset = UNSET
    if deadline is not None:
        if deadline.lower() == "none":
            dl = None
        else:
            dl = _parse_deadline_or_exit(deadline)

    project_id: ProjectId | None | Unset = UNSET
    if project_ref is not None:
        if project_ref.lower() == "none":
            project_id = None
        else:
            project_id = _resolve_project_or_exit(projects, project_ref)

    # 'none' clears, like --deadline and --project. Omitting --tag leaves
    # tags untouched; a blank tag is an error, so this sentinel is the
    # only way to clear them (and cannot come from an unset shell var).
    tags: list[str] | None = None
    if tag:
        tags = [] if len(tag) == 1 and tag[0].lower() == "none" else list(tag)

    try:
        result = edit_todo(
            items,
            dependencies,
            ItemId(item_id),
            title=title,
            body=body,
            priority=Priority.from_string(priority) if priority else None,
            status=Status.from_string(status) if status else None,
            deadline=dl,
            tags=tags,
            project_id=project_id,
        )
    except (NotFoundError, ValueError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    _warn_unblocked(result.unblocked)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_item(result.item, deps, project_names(projects))
    else:
        out.print_item(result.item, deps, project_names(projects))


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
        result = move_todo(
            items, dependencies, ItemId(item_id), Status.from_string(status)
        )
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    _warn_unblocked(result.unblocked)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_item(result.item, deps, project_names(projects))
    else:
        out.print_item(result.item, deps, project_names(projects))


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
        result = complete_todo(items, dependencies, ItemId(item_id))
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    _warn_unblocked(result.unblocked)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_item(result.item, deps, project_names(projects))
    else:
        out.print_item(result.item, deps, project_names(projects))


@main.command()
@click.argument("item_id", type=int)
def rm(item_id: int) -> None:
    """Delete a todo item."""
    items = _items()
    dependencies = _dependencies()
    out = create_output()
    try:
        unblocked = delete_todo(items, dependencies, ItemId(item_id))
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    _warn_unblocked(unblocked)
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
        since_dt, done = summary(items, since)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_summary(since_dt, done, deps, project_names(projects))
    else:
        out.print_summary(since_dt, done, deps)


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
        item = block_todo_batch(
            items, dependencies, ItemId(item_id), [ItemId(b) for b in blocker_ids]
        )
    except (NotFoundError, DependencyError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_item(item, deps, project_names(projects))
    else:
        out.print_item(item, deps, project_names(projects))


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
        item = unblock_todo_batch(
            items, dependencies, ItemId(item_id), [ItemId(b) for b in blocker_ids]
        )
    except (NotFoundError, DependencyError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_item(item, deps, project_names(projects))
    else:
        out.print_item(item, deps, project_names(projects))


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
        created = add_project(projects, name, description=description)
    except (DuplicateProjectError, ValueError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    detail = project_detail(items, log, created)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_project(detail, deps, project_names(projects))
    else:
        out.print_project(detail, deps, project_names(projects))


@project.command("list")
@click.option("--all", "include_ended", is_flag=True, help="Include cancelled and done")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_list(include_ended: bool, as_json: bool) -> None:
    """List projects with open/done counts."""
    projects = _projects()
    items = _items()
    out = create_output()
    summaries = list_projects(projects, items, include_ended=include_ended)
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
    try:
        detail = show_project(projects, items, log, ref)
    except ProjectNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_project(detail, deps, project_names(projects))
    else:
        out.print_project(detail, deps, project_names(projects))


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
    project_id = _resolve_project_or_exit(projects, ref)
    try:
        edited = edit_project(projects, project_id, name=name, description=description)
    except (DuplicateProjectError, ValueError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    detail = project_detail(items, log, edited)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_project(detail, deps, project_names(projects))
    else:
        out.print_project(detail, deps, project_names(projects))


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
    updated = set_project_status(projects, project_id, new_status)
    detail = project_detail(items, log, updated)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_project(detail, deps, project_names(projects))
    else:
        out.print_project(detail, deps, project_names(projects))


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
        log_project_update(log, proj.id, text)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    detail = project_detail(items, log, proj)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_project(detail, deps, project_names(projects))
    else:
        out.print_project(detail, deps, project_names(projects))


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
        entry = log.get(UpdateId(update_id))
        delete_project_update(log, entry.id)
    except UpdateNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    proj = projects.get(entry.project_id)
    detail = project_detail(items, log, proj)
    deps = Dependencies.load(items, dependencies)
    if as_json:
        out.print_json_project(detail, deps, project_names(projects))
    else:
        out.print_project(detail, deps, project_names(projects))


@project.command("rm")
@click.argument("ref")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_rm(ref: str, as_json: bool) -> None:
    """Delete a project; its items survive unassigned."""
    projects = _projects()
    items = _items()
    log = _log()
    # Read the record before deleting it: --json reports what was removed.
    project = _resolve_project_obj_or_exit(projects, ref)
    delete_project(projects, items, log, project.id)
    if as_json:
        create_output().print_json_deleted_project(project)
    else:
        click.echo(f"Deleted project #{project.id}. Items were unassigned.")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def tags(as_json: bool) -> None:
    """List all tags with usage counts."""
    items = _items()
    out = create_output()
    counts = count_tags(items)
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
