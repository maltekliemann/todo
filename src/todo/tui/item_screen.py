"""The item menu: every field an item has, edited where it is shown.

One screen for opening an item and for changing it. Each field is a row;
Enter on a row opens the right way to change that field — a text prompt, a
menu of the values it can take, or the blocker picker. Nothing is typed as
`key: value` and nothing has to be remembered.

The body is the exception: it is prose, so Enter on its row hands it to
$EDITOR.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from todo.application.commands import CompletionResult, edit_todo
from todo.application.contracts.storage import StorageProtocol
from todo.application.dependencies import Dependencies
from todo.application.queries import list_all_projects, show_todo
from todo.domain.priority import Priority
from todo.domain.status import Status
from todo.domain.todo_item import TodoItem
from todo.exceptions import NotFoundError, TodoError
from todo.tui.blockers import BlockDialog, Relation
from todo.tui.edit_session import EditorSession
from todo.tui.prompts import ChoicePrompt, TextPrompt
from todo.tui.render import unblocked_notices
from todo.tui.tag_input import parse_tag_input

# Shown where a field has no value. An empty cell reads as a rendering
# bug; this reads as "nothing set yet".
EMPTY = "—"

# (key, row label), in the order the rows appear.
FIELDS: tuple[tuple[str, str], ...] = (
    ("title", "Title"),
    ("priority", "Priority"),
    ("status", "Status"),
    ("deadline", "Deadline"),
    ("tags", "Tags"),
    ("project", "Project"),
    ("blocked_by", "Blocked by"),
    ("blocking", "Blocking"),
    ("body", "Body"),
)

_LABEL_WIDTH = max(len(label) for _, label in FIELDS) + 2


def body_summary(body: str) -> str:
    if not body:
        return "empty"
    lines = len(body.splitlines())
    return f"{lines} line{'' if lines == 1 else 's'}"


def field_value(item: TodoItem, key: str, deps: Dependencies) -> str:
    """The current value of one field, as the row shows it."""
    if key == "title":
        return item.title
    if key == "priority":
        return item.priority.value
    if key == "status":
        return item.status.value
    if key == "deadline":
        return item.deadline.isoformat() if item.deadline else EMPTY
    if key == "tags":
        return ", ".join(item.tags) or EMPTY
    if key == "project":
        return item.project.name if item.project else EMPTY
    if key == "blocked_by":
        return ", ".join(f"#{i}" for i in deps.blockers_of(item.id)) or EMPTY
    if key == "blocking":
        return ", ".join(f"#{i}" for i in deps.dependents_of(item.id)) or EMPTY
    return body_summary(item.body)


def _row(label: str, value: str) -> Text:
    # Text, never markup: titles, tags and project names are user text.
    row = Text()
    row.append(label.ljust(_LABEL_WIDTH), style="dim")
    row.append(value)
    return row


class ItemScreen(ModalScreen[bool]):
    """Show one item and change it in place.

    Returns True if anything was written, so the list behind it knows to
    refresh. Every failure reports inline and leaves the screen open —
    losing what you were doing to a rejected date is not acceptable.
    """

    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, storage: StorageProtocol, item: TodoItem) -> None:
        super().__init__()
        self._storage = storage
        self._item = item
        self._changed = False

    def compose(self) -> ComposeResult:
        with Vertical(id="item-container"):
            yield Static("", id="item-heading")
            yield OptionList(id="item-fields")
            yield Label("", id="item-error")
            yield Label("↑↓ field · Enter edit · Esc close", id="item-hint")
            # Last, and the only flexible child: on a terminal too short
            # for everything, the preview is what gives way — never the
            # inline error or the keys.
            with VerticalScroll(id="item-body-scroll"):
                yield Static("", id="item-body")

    def on_mount(self) -> None:
        self._show_item()
        self.query_one("#item-fields", OptionList).focus()

    def _show_item(self) -> None:
        item = self._item
        # Reloaded with the item: an edge changed by the picker has to show.
        deps = Dependencies.load(self._storage)

        heading = Text(f"#{item.id}", style="bold")
        heading.append(
            f"  created {item.created_at:%b %d, %Y %H:%M}"
            f" · updated {item.updated_at:%b %d, %Y %H:%M}",
            style="dim",
        )
        if item.done_at:
            heading.append(f" · done {item.done_at:%b %d, %Y %H:%M}", style="dim")
        self.query_one("#item-heading", Static).update(heading)

        options = self.query_one("#item-fields", OptionList)
        # clear_options() drops the highlight; the row count is fixed, so
        # putting it back keeps the cursor on the field just edited.
        highlighted = options.highlighted
        options.clear_options()
        for key, label in FIELDS:
            options.add_option(Option(_row(label, field_value(item, key, deps))))
        options.highlighted = 0 if highlighted is None else highlighted

        self.query_one("#item-body", Static).update(
            Text(item.body) if item.body else Text("(no description)", style="dim")
        )

    def _show_message(self, message: str) -> None:
        label = self.query_one("#item-error", Label)
        # Never markup: this echoes storage errors and the user's own input.
        label.update(Text(message))
        # Shown only when it has something to say: an always-present blank
        # row costs a line of a short terminal, and the hint pays for it.
        label.display = True

    def _clear_message(self) -> None:
        label = self.query_one("#item-error", Label)
        label.update("")
        label.display = False

    def _reload(self) -> None:
        """Re-read the item after a write, so every row shows what is
        actually stored rather than what we think we just set."""
        try:
            self._item = show_todo(self._storage, self._item.id)
        except NotFoundError:
            # Deleted underneath us: there is nothing left to show, and
            # the list needs to hear about it.
            self.dismiss(True)
            return
        except TodoError as exc:
            self._show_message(str(exc) or "Could not read the item")
            return
        self._show_item()

    def _apply(self, call: Callable[[], CompletionResult]) -> None:
        try:
            result = call()
        except (TodoError, ValueError) as exc:
            # Rejections (empty title, reserved tag, cycle) and storage
            # failures alike: report and keep the screen.
            self._show_message(str(exc) or "Could not save the change")
            return
        self._changed = True
        for message in unblocked_notices(result):
            self.notify(message)
        self._reload()

    @on(OptionList.OptionSelected, "#item-fields")
    def on_field_selected(self, event: OptionList.OptionSelected) -> None:
        index = event.option_index
        if not (0 <= index < len(FIELDS)):
            return
        self._clear_message()
        self._edit(FIELDS[index][0])

    def _edit(self, key: str) -> None:
        item = self._item
        if key == "title":
            self.app.push_screen(TextPrompt("Title", item.title), self._save_title)
        elif key == "priority":
            self.app.push_screen(
                ChoicePrompt(
                    "Priority",
                    [(p.value, p.value) for p in Priority],
                    item.priority.value,
                ),
                self._save_priority,
            )
        elif key == "status":
            self.app.push_screen(
                ChoicePrompt(
                    "Status", [(s.value, s.value) for s in Status], item.status.value
                ),
                self._save_status,
            )
        elif key == "deadline":
            self.app.push_screen(
                TextPrompt(
                    "Deadline (YYYY-MM-DD, empty clears)",
                    item.deadline.isoformat() if item.deadline else "",
                    placeholder="YYYY-MM-DD",
                ),
                self._save_deadline,
            )
        elif key == "tags":
            self.app.push_screen(
                TextPrompt(
                    "Tags (comma-separated, empty clears)",
                    ", ".join(item.tags),
                    placeholder="tag, other tag",
                ),
                self._save_tags,
            )
        elif key == "project":
            self._edit_project()
        elif key == "blocked_by":
            self._edit_dependencies(Relation.WAITS_ON)
        elif key == "blocking":
            self._edit_dependencies(Relation.BLOCKS)
        elif key == "body":
            self._edit_body()

    def _save_title(self, value: str | None) -> None:
        if value is None:
            return
        self._apply(lambda: edit_todo(self._storage, self._item.id, title=value))

    def _save_priority(self, value: str | None) -> None:
        if value is None:
            return
        priority = Priority.from_string(value)
        self._apply(lambda: edit_todo(self._storage, self._item.id, priority=priority))

    def _save_status(self, value: str | None) -> None:
        if value is None:
            return
        status = Status.from_string(value)
        self._apply(lambda: edit_todo(self._storage, self._item.id, status=status))

    def _save_deadline(self, value: str | None) -> None:
        if value is None:
            return
        text = value.strip()
        deadline: date | None = None
        if text:
            try:
                deadline = date.fromisoformat(text)
            except ValueError:
                # Same contract as everywhere else: bad input is reported,
                # never silently ignored.
                self._show_message(f"Invalid date '{text}' — use YYYY-MM-DD")
                return
        self._apply(lambda: edit_todo(self._storage, self._item.id, deadline=deadline))

    def _save_tags(self, value: str | None) -> None:
        if value is None:
            return
        tags = parse_tag_input(value)
        self._apply(lambda: edit_todo(self._storage, self._item.id, tags=tags))

    def _edit_project(self) -> None:
        try:
            projects = list_all_projects(self._storage, include_archived=True)
        except TodoError as exc:
            self._show_message(str(exc) or "Could not read the projects")
            return
        choices = [("", f"({EMPTY} none)")] + [(str(p.id), p.name) for p in projects]
        current = str(self._item.project.id) if self._item.project else ""
        self.app.push_screen(
            ChoicePrompt("Project", choices, current), self._save_project
        )

    def _save_project(self, value: str | None) -> None:
        if value is None:
            return
        project_id = int(value) if value else None
        self._apply(
            lambda: edit_todo(self._storage, self._item.id, project_id=project_id)
        )

    def _edit_dependencies(self, relation: Relation) -> None:
        """Edit either end of the relation.

        The other direction writes the same edge with the ids the other way
        round — a dependency belongs to neither item, so there is nothing
        special about editing it from this side.
        """

        def after(changed: bool | None) -> None:
            if changed:
                self._changed = True
                self._reload()

        self.app.push_screen(BlockDialog(self._storage, self._item.id, relation), after)

    def _edit_body(self) -> None:
        result = EditorSession(self, self._storage).run(self._item)
        if result is None:
            # Cancelled, unchanged, or already reported by the session.
            return
        self._changed = True
        for message in unblocked_notices(result):
            self.notify(message)
        self._reload()

    def action_close(self) -> None:
        self.dismiss(self._changed)
