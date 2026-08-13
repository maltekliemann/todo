"""Rendering helpers shared by the table, the dialogs and the detail pane.

How an item looks is a question each frontend answers for itself. These
used to be borrowed from the CLI's printer through names it had marked
private; the TUI paints cells in a terminal UI and the CLI writes lines
to a stream, and the day one of them wants a different deadline format
is the day a shared helper becomes a flag.
"""

from __future__ import annotations

from datetime import datetime

from todo.application.queries.project_names import ProjectNames
from todo.application.toast import Toast
from todo.domain.dependency_graph import DependencyGraph
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.status import Status
from todo.domain.todo_item import TodoItem

# All labels are the same width, so a longer one cannot shift the column
# beside it.
_PRIORITY_LABELS = {
    Priority.URGENT: "!! URG ",
    Priority.HIGH: "!  HIGH",
    Priority.MEDIUM: "   MED ",
    Priority.LOW: "   LOW ",
}


def join_styles(*styles: str) -> str:
    """Combine Rich style strings, dropping the empty ones."""
    return " ".join(s for s in styles if s)


def escape_markup(text: str) -> str:
    """Escape user text for a markup-parsing sink.

    rich.markup.escape only escapes "[" before [a-z#/@], but Textual's
    Content.from_markup also parses [WIP], [Red] and [$VAR] — so a title
    like "[WIP] refactor" was silently swallowed.

    Escape brackets ONLY. Textual (unlike rich) never collapses "\\\\" back
    to a single backslash, so doubling them here rendered every Windows
    path, regex and LaTeX fragment with doubled slashes.
    """
    return text.replace("[", "\\[")


def priority_label(priority: Priority) -> str:
    return _PRIORITY_LABELS[priority]


def priority_style(priority: Priority) -> str:
    if priority == Priority.URGENT:
        return "bold red"
    if priority == Priority.HIGH:
        return "dark_orange"
    if priority == Priority.LOW:
        return "dim"
    return ""


def status_icon(status: Status) -> str:
    if status == Status.DONE:
        return "✓"
    if status == Status.IN_PROGRESS:
        return "●"
    return "○"


def deadline_str(item: TodoItem) -> str:
    """The deadline as a cell: nothing, a date, or a date and a warning."""
    if item.deadline is None:
        return ""
    days = item.days_until_deadline
    assert days is not None
    if item.is_overdue:
        return f"\U0001f534 {item.deadline.strftime('%b %d')} ({abs(days)}d overdue)"
    if item.deadline_urgent:
        return f"⚠ {item.deadline.strftime('%b %d')} ({days}d)"
    return item.deadline.strftime("%b %d")


def deadline_style(item: TodoItem) -> str:
    if item.is_overdue:
        return "bold red"
    if item.deadline_urgent:
        return "yellow"
    return "dim"


def relative_age(dt: datetime) -> str:
    """How long ago, in one or two characters."""
    delta = datetime.now(tz=dt.tzinfo) - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 7:
        return f"{days}d"
    if days < 30:
        # Threshold on days, not weeks: 28-29 days is '4w', never '0mo'.
        return f"{days // 7}w"
    return f"{days // 30}mo"


def meta_lines(
    item: TodoItem,
    graph: DependencyGraph,
    names: ProjectNames,
) -> list[str]:
    """The metadata block shared by the detail pane and the item screen.

    One source of truth so the two renderings can never drift. User text
    (project name, tags) is escaped — both widgets parse markup.
    """
    first = f"Priority: {item.priority.value}    Status: {item.status.value}"
    if item.deadline:
        first += f"    Deadline: {deadline_str(item)}"
    second = (
        f"Created: {item.created_at.strftime('%b %d, %Y %H:%M')}    "
        f"Updated: {item.updated_at.strftime('%b %d, %Y %H:%M')}"
    )
    if item.done_at:
        second += f"    Done: {item.done_at.strftime('%b %d, %Y %H:%M')}"
    lines = [first, second]
    project_name = names.of(item.project_id)
    if project_name is not None:
        lines.append(f"Project: {escape_markup(project_name)}")
    if item.tags:
        lines.append(f"Tags: {escape_markup(', '.join(sorted(item.tags)))}")
    blockers = graph.blockers_of(item.id)
    if blockers:
        lines.append(f"Blocked by: {', '.join(i.label for i in blockers)}")
    blocks = graph.dependents_of(item.id)
    if blocks:
        lines.append(f"Blocking: {', '.join(i.label for i in blocks)}")
    return lines


def toast_messages(toasts: list[Toast], titles: dict[ItemId, str]) -> list[str]:
    """A toast carries ids; the wording is this frontend's.

    Titles are looked up by whoever has them, so this stays a function of
    the facts and nothing else.
    """
    return [
        f"🔓 {item_id.label} {escape_markup(titles.get(item_id, ''))} is now unblocked"
        for toast in toasts
        for item_id in toast.items
    ]
