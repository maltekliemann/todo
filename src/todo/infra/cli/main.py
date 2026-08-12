from __future__ import annotations

import sys
from datetime import date

import click

from todo.adapters.output import create_output
from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import (
    add_project,
    add_todo,
    archive_project,
    block_todo_batch,
    complete_todo,
    delete_project,
    delete_todo,
    edit_project,
    edit_todo,
    log_project_update,
    move_todo,
    unblock_todo_batch,
)
from todo.application.contracts.storage import UNSET, Unset
from todo.application.queries import (
    count_tags,
    list_projects,
    list_todos,
    resolve_project,
    show_project,
    show_todo,
    summary,
)
from todo.config import get_db_path
from todo.domain.enums import Priority, Status
from todo.domain.models import TodoItem
from todo.exceptions import (
    DependencyError,
    DuplicateProjectError,
    NotFoundError,
    ProjectNotFoundError,
)

_PRIORITY_CHOICES = [p.value for p in Priority]
_STATUS_CHOICES = [s.value for s in Status]


def _storage() -> SqliteStorage:
    return SqliteStorage(get_db_path())


def _warn_unblocked(unblocked: list[TodoItem]) -> None:
    for dep in unblocked:
        click.echo(f"🔓 #{dep.id} {dep.title} is now unblocked", err=True)


def _parse_deadline_or_exit(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        click.echo(f"Invalid deadline '{value}'. Use YYYY-MM-DD.", err=True)
        sys.exit(1)


def _resolve_project_or_exit(storage: SqliteStorage, ref: str) -> int:
    try:
        return resolve_project(storage, ref).id
    except ProjectNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@click.group()
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
    storage = _storage()
    out = create_output()
    dl = _parse_deadline_or_exit(deadline) if deadline else None
    project_id = _resolve_project_or_exit(storage, project_ref) if project_ref else None
    item = add_todo(
        storage,
        title,
        body=body,
        priority=Priority.from_string(priority),
        status=Status.from_string(status),
        deadline=dl,
        tags=list(tag) if tag else None,
        project_id=project_id,
    )
    if as_json:
        out.print_json_item(item)
    else:
        out.print_item(item)


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
    storage = _storage()
    out = create_output()
    project_id = _resolve_project_or_exit(storage, project_ref) if project_ref else None
    items = list_todos(
        storage,
        status=Status.from_string(status) if status else None,
        priority=Priority.from_string(priority) if priority else None,
        tags=list(tag) if tag else None,
        search=search,
        project_id=project_id,
        include_done=include_all,
        blocked=blocked,
        ready=ready,
    )
    if as_json:
        out.print_json_list(items)
    else:
        out.print_list(items)


@main.command()
@click.argument("item_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def show(item_id: int, as_json: bool) -> None:
    """Show details for a todo item."""
    storage = _storage()
    out = create_output()
    try:
        item = show_todo(storage, item_id)
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    if as_json:
        out.print_json_item(item)
    else:
        out.print_item(item)


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
@click.option("--tag", "-t", multiple=True, help="Replace tags (repeatable)")
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
    storage = _storage()
    out = create_output()

    dl: date | None | Unset = UNSET
    if deadline is not None:
        if deadline.lower() == "none":
            dl = None
        else:
            dl = _parse_deadline_or_exit(deadline)

    project_id: int | None | Unset = UNSET
    if project_ref is not None:
        if project_ref.lower() == "none":
            project_id = None
        else:
            project_id = _resolve_project_or_exit(storage, project_ref)

    try:
        result = edit_todo(
            storage,
            item_id,
            title=title,
            body=body,
            priority=Priority.from_string(priority) if priority else None,
            status=Status.from_string(status) if status else None,
            deadline=dl,
            tags=list(tag) if tag else None,
            project_id=project_id,
        )
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    _warn_unblocked(result.unblocked)
    if as_json:
        out.print_json_item(result.item)
    else:
        out.print_item(result.item)


@main.command()
@click.argument("item_id", type=int)
@click.argument("status", type=click.Choice(_STATUS_CHOICES, case_sensitive=False))
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def mv(item_id: int, status: str, as_json: bool) -> None:
    """Move a todo item to a new status."""
    storage = _storage()
    out = create_output()
    try:
        result = move_todo(storage, item_id, Status.from_string(status))
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    _warn_unblocked(result.unblocked)
    if as_json:
        out.print_json_item(result.item)
    else:
        out.print_item(result.item)


@main.command()
@click.argument("item_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def done(item_id: int, as_json: bool) -> None:
    """Mark a todo item as done."""
    storage = _storage()
    out = create_output()
    try:
        result = complete_todo(storage, item_id)
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    _warn_unblocked(result.unblocked)
    if as_json:
        out.print_json_item(result.item)
    else:
        out.print_item(result.item)


@main.command()
@click.argument("item_id", type=int)
def rm(item_id: int) -> None:
    """Delete a todo item."""
    storage = _storage()
    out = create_output()
    try:
        delete_todo(storage, item_id)
    except NotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    out.print_deleted(item_id)


@main.command("summary")
@click.option("--since", required=True, help="'7 days', '2 weeks', or '2025-04-01'")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def summary_cmd(since: str, as_json: bool) -> None:
    """Show a summary of completed items."""
    storage = _storage()
    out = create_output()
    try:
        since_dt, items = summary(storage, since)
    except ValueError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    if as_json:
        out.print_json_summary(since_dt, items)
    else:
        out.print_summary(since_dt, items)


@main.command()
@click.argument("item_id", type=int)
@click.argument("blocker_ids", type=int, nargs=-1, required=True)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def block(item_id: int, blocker_ids: tuple[int, ...], as_json: bool) -> None:
    """Mark ITEM_ID as blocked by the given blocker item(s), all-or-nothing."""
    storage = _storage()
    out = create_output()
    try:
        item = block_todo_batch(storage, item_id, list(blocker_ids))
    except (NotFoundError, DependencyError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    if as_json:
        out.print_json_item(item)
    else:
        out.print_item(item)


@main.command()
@click.argument("item_id", type=int)
@click.argument("blocker_ids", type=int, nargs=-1, required=True)
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def unblock(item_id: int, blocker_ids: tuple[int, ...], as_json: bool) -> None:
    """Remove the given blocker item(s) from ITEM_ID."""
    storage = _storage()
    out = create_output()
    try:
        item = unblock_todo_batch(storage, item_id, list(blocker_ids))
    except (NotFoundError, DependencyError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    if as_json:
        out.print_json_item(item)
    else:
        out.print_item(item)


@main.group()
def project() -> None:
    """Manage projects."""


@project.command("add")
@click.argument("name")
@click.option("--description", "-D", default="", help="Project description")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_add(name: str, description: str, as_json: bool) -> None:
    """Create a new project."""
    storage = _storage()
    out = create_output()
    try:
        created = add_project(storage, name, description=description)
    except DuplicateProjectError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    detail = show_project(storage, str(created.id))
    if as_json:
        out.print_json_project(detail)
    else:
        out.print_project(detail)


@project.command("list")
@click.option("--all", "include_archived", is_flag=True, help="Include archived")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_list(include_archived: bool, as_json: bool) -> None:
    """List projects with open/done counts."""
    storage = _storage()
    out = create_output()
    summaries = list_projects(storage, include_archived=include_archived)
    if as_json:
        out.print_json_projects(summaries)
    else:
        out.print_projects(summaries)


@project.command("show")
@click.argument("ref")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_show(ref: str, as_json: bool) -> None:
    """Show a project (by name or id) and its items."""
    storage = _storage()
    out = create_output()
    try:
        detail = show_project(storage, ref)
    except ProjectNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    if as_json:
        out.print_json_project(detail)
    else:
        out.print_project(detail)


@project.command("edit")
@click.argument("ref")
@click.option("--name", default=None, help="New name")
@click.option("--description", "-D", default=None, help="New description")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_edit(
    ref: str, name: str | None, description: str | None, as_json: bool
) -> None:
    """Edit a project's name or description."""
    storage = _storage()
    out = create_output()
    project_id = _resolve_project_or_exit(storage, ref)
    try:
        edited = edit_project(storage, project_id, name=name, description=description)
    except DuplicateProjectError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    detail = show_project(storage, str(edited.id))
    if as_json:
        out.print_json_project(detail)
    else:
        out.print_project(detail)


@project.command("archive")
@click.argument("ref")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_archive(ref: str, as_json: bool) -> None:
    """Archive a project (hidden from default project list)."""
    storage = _storage()
    out = create_output()
    project_id = _resolve_project_or_exit(storage, ref)
    archived = archive_project(storage, project_id)
    detail = show_project(storage, str(archived.id))
    if as_json:
        out.print_json_project(detail)
    else:
        out.print_project(detail)


@project.command("log")
@click.argument("ref")
@click.argument("text")
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def project_log(ref: str, text: str, as_json: bool) -> None:
    """Append a timestamped update to a project's log."""
    storage = _storage()
    out = create_output()
    project_id = _resolve_project_or_exit(storage, ref)
    log_project_update(storage, project_id, text)
    detail = show_project(storage, str(project_id))
    if as_json:
        out.print_json_project(detail)
    else:
        out.print_project(detail)


@project.command("rm")
@click.argument("ref")
def project_rm(ref: str) -> None:
    """Delete a project; its items survive unassigned."""
    storage = _storage()
    project_id = _resolve_project_or_exit(storage, ref)
    delete_project(storage, project_id)
    click.echo(f"Deleted project #{project_id}. Items were unassigned.")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Output JSON")
def tags(as_json: bool) -> None:
    """List all tags with usage counts."""
    storage = _storage()
    out = create_output()
    counts = count_tags(storage)
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
