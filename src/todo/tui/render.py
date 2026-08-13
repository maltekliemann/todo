"""Rendering helpers shared by the table, the dialogs and the detail pane."""

from __future__ import annotations

from todo.adapters.output import _deadline_str
from todo.application.commands import CompletionResult
from todo.application.dependencies import Dependencies
from todo.domain.todo_item import TodoItem


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


def meta_lines(item: TodoItem, deps: Dependencies) -> list[str]:
    """The metadata block shared by the detail pane and the inspect modal.

    One source of truth so the two renderings can never drift. User text
    (project name, tags) is escaped — both widgets parse markup.
    """
    first = f"Priority: {item.priority.value}    Status: {item.status.value}"
    if item.deadline:
        first += f"    Deadline: {_deadline_str(item)}"
    second = (
        f"Created: {item.created_at.strftime('%b %d, %Y %H:%M')}    "
        f"Updated: {item.updated_at.strftime('%b %d, %Y %H:%M')}"
    )
    if item.done_at:
        second += f"    Done: {item.done_at.strftime('%b %d, %Y %H:%M')}"
    lines = [first, second]
    if item.project:
        lines.append(f"Project: {escape_markup(item.project.name)}")
    if item.tags:
        lines.append(f"Tags: {escape_markup(', '.join(sorted(item.tags)))}")
    blockers = deps.blockers_of(item.id)
    if blockers:
        lines.append(f"Blocked by: {', '.join(f'#{i}' for i in blockers)}")
    dependents = deps.dependents_of(item.id)
    if dependents:
        lines.append(f"Blocking: {', '.join(f'#{i}' for i in dependents)}")
    return lines


def unblocked_notices(result: CompletionResult | list[TodoItem]) -> list[str]:
    """One message per dependent a completion just freed.

    Every screen that can complete an item owes the user this news, so the
    wording lives here rather than in whichever screen happened to be open.
    """
    deps = result.unblocked if isinstance(result, CompletionResult) else result
    return [f"🔓 #{d.id} {escape_markup(d.title)} is now unblocked" for d in deps]
