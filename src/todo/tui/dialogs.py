"""The modal screens: confirm, new item, search, blocker, inspect."""

from __future__ import annotations

from datetime import date

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Select, Static
from textual.widgets.option_list import Option

from todo.application.commands import add_todo, block_todo, unblock_todo
from todo.application.contracts.storage import StorageProtocol
from todo.application.queries import list_todos, show_todo
from todo.domain.enums import Priority
from todo.domain.models import TodoItem
from todo.domain.tags import split_tags
from todo.exceptions import TodoError
from todo.tui.render import escape_markup, meta_lines


def _matches_item(item: TodoItem, query: str) -> bool:
    """Search matches the title or the id, with or without the '#'."""
    if not query:
        return True
    return query in item.title.casefold() or query.lstrip("#") == str(item.id)


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n,escape", "no", "No"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Container(id="confirm-container"):
            yield Label(self._message)
            # Text, not markup: Textual parses "[y]"/"[n]" as style tags
            # and would render the hint with no key labels at all.
            yield Label(Text("[y] Yes   [n] No"), id="confirm-hint")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class AdvancingSelect(Select[str]):
    """Priority Select with keyboard-friendly behavior.

    - Enter / Down (when closed): advance to the next field
    - Up (when closed): go back to the previous field
    - Right (when closed): step priority up (low → medium → high → urgent)
    - Left (when closed): step priority down (urgent → high → medium → low)
    - Space: open the dropdown
    """

    _PRIORITY_ORDER = ["low", "medium", "high", "urgent"]

    BINDINGS = [
        Binding("enter", "advancing_submit", show=False),
        Binding("down", "advancing_submit", show=False),
        Binding("up", "advancing_retreat", show=False),
        Binding("left", "step_down", show=False),
        Binding("right", "step_up", show=False),
    ]

    class Submitted(Message):
        def __init__(self, select: "AdvancingSelect") -> None:
            super().__init__()
            self.select = select

        @property
        def control(self) -> "AdvancingSelect":
            return self.select

    class Retreated(Message):
        def __init__(self, select: "AdvancingSelect") -> None:
            super().__init__()
            self.select = select

        @property
        def control(self) -> "AdvancingSelect":
            return self.select

    def action_advancing_submit(self) -> None:
        if not self.expanded:
            self.post_message(self.Submitted(self))

    def action_advancing_retreat(self) -> None:
        if not self.expanded:
            self.post_message(self.Retreated(self))

    def action_step_down(self) -> None:
        self._step(-1)

    def action_step_up(self) -> None:
        self._step(1)

    def _step(self, direction: int) -> None:
        if self.expanded:
            return
        try:
            idx = self._PRIORITY_ORDER.index(str(self.value))
        except ValueError:
            idx = 1
        new_idx = max(0, min(len(self._PRIORITY_ORDER) - 1, idx + direction))
        self.value = self._PRIORITY_ORDER[new_idx]


class NewItemDialog(ModalScreen[TodoItem | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "field_advance", show=False),
        Binding("up", "field_retreat", show=False),
    ]

    def __init__(self, storage: StorageProtocol, project_id: int | None = None) -> None:
        super().__init__()
        self._storage = storage
        # The list's active project filter. Creating an item while a
        # filter is on used to store it unfiled, so it never appeared and
        # the user re-added it — inheriting the filter matches intent.
        self._project_id = project_id

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-container"):
            yield Label("New Todo", id="dialog-title")
            yield Label("Title:")
            yield Input(id="new-title", placeholder="What needs to be done?")
            yield Label("Priority:")
            yield AdvancingSelect(
                [(p.value, p.value) for p in Priority],
                value="medium",
                id="new-priority",
                allow_blank=False,
            )
            yield Label("Deadline (YYYY-MM-DD, optional):")
            yield Input(id="new-deadline", placeholder="")
            yield Label("Tags (comma-separated, optional):")
            yield Input(id="new-tags", placeholder="")
            yield Label("", id="dialog-error")
            yield Label(
                "↓/Enter next · ↑ prev · ←/→ priority · Esc cancel",
                id="dialog-hint",
            )

    def on_mount(self) -> None:
        self.query_one("#new-title", Input).focus()

    def _set_error(self, msg: str) -> None:
        self.query_one("#dialog-error", Label).update(msg)

    def _clear_error(self) -> None:
        self.query_one("#dialog-error", Label).update("")

    def _check_title(self) -> bool:
        title = self.query_one("#new-title", Input).value.strip()
        if not title:
            self._set_error("Title is required")
            return False
        return True

    def _check_deadline(self) -> bool:
        deadline_str = self.query_one("#new-deadline", Input).value.strip()
        if not deadline_str:
            return True
        try:
            date.fromisoformat(deadline_str)
        except ValueError:
            self._set_error("Invalid date — use YYYY-MM-DD")
            return False
        return True

    @on(Input.Submitted, "#new-title")
    def _on_title_submit(self) -> None:
        if not self._check_title():
            return
        self._clear_error()
        self.query_one("#new-priority", AdvancingSelect).focus()

    @on(AdvancingSelect.Submitted, "#new-priority")
    def _on_priority_submit(self) -> None:
        self._clear_error()
        self.query_one("#new-deadline", Input).focus()

    @on(AdvancingSelect.Retreated, "#new-priority")
    def _on_priority_retreat(self) -> None:
        self._clear_error()
        self.query_one("#new-title", Input).focus()

    @on(Input.Submitted, "#new-deadline")
    def _on_deadline_submit(self) -> None:
        if not self._check_deadline():
            return
        self._clear_error()
        self.query_one("#new-tags", Input).focus()

    @on(Input.Submitted, "#new-tags")
    def _on_tags_submit(self) -> None:
        self.action_save()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_field_advance(self) -> None:
        focused = self.focused
        if focused is None:
            return
        if focused.id == "new-title":
            self._on_title_submit()
        elif focused.id == "new-deadline":
            self._on_deadline_submit()
        elif focused.id == "new-tags":
            self._on_tags_submit()
        # priority is handled by AdvancingSelect's own down binding

    def action_field_retreat(self) -> None:
        focused = self.focused
        if focused is None:
            return
        if focused.id == "new-deadline":
            self._clear_error()
            self.query_one("#new-priority", AdvancingSelect).focus()
        elif focused.id == "new-tags":
            self._clear_error()
            self.query_one("#new-deadline", Input).focus()
        # title has no previous; priority is handled by AdvancingSelect's own up binding

    def action_save(self) -> None:
        if not self._check_title():
            self.query_one("#new-title", Input).focus()
            return
        if not self._check_deadline():
            self.query_one("#new-deadline", Input).focus()
            return

        title = self.query_one("#new-title", Input).value.strip()
        priority = Priority.from_string(
            str(self.query_one("#new-priority", AdvancingSelect).value)
        )
        deadline_str = self.query_one("#new-deadline", Input).value.strip()
        deadline = date.fromisoformat(deadline_str) if deadline_str else None
        tags_str = self.query_one("#new-tags", Input).value.strip()
        tags = split_tags(tags_str) if tags_str else None

        try:
            item = add_todo(
                self._storage,
                title,
                priority=priority,
                deadline=deadline,
                tags=tags,
                project_id=self._project_id,
            )
        except (TodoError, ValueError) as exc:
            # E.g. a locked database or a rejected tag: report inline and
            # keep the dialog (and the user's typed input) alive.
            self.query_one("#dialog-error", Label).update(
                Text(str(exc) if str(exc) else "Could not save item")
            )
            return
        self.dismiss(item)


class SearchDialog(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="search-container"):
            yield Label("Search (Enter to apply, Esc to cancel):")
            yield Input(id="search-input", placeholder="Title, body, or tag...")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    @on(Input.Submitted, "#search-input")
    def on_submit(self) -> None:
        value = self.query_one("#search-input", Input).value.strip()
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class BlockDialog(ModalScreen[bool]):
    """Pick what an item waits on, from a searchable list.

    Every other item is a candidate; the ones already blocking this item
    are marked and sorted first, and choosing one toggles the relation.
    Typing narrows by title or id — nobody should have to remember the
    number of the thing that blocks them.

    Choosing applies the change and closes, as it always has. The command
    call happens here so validation, cycle and storage errors show inline
    instead of closing the dialog on the user's work.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "highlight_next", show=False),
        Binding("up", "highlight_previous", show=False),
    ]

    def __init__(self, storage: StorageProtocol, blocked_id: int) -> None:
        super().__init__()
        self._storage = storage
        self._blocked_id = blocked_id
        self._candidates: list[TodoItem] = []
        self._blocker_ids: set[int] = set()
        self._shown_ids: list[int] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="block-container"):
            yield Label(f"What does #{self._blocked_id} wait on?", id="block-title")
            yield Input(id="block-search", placeholder="Search by title or id")
            yield OptionList(id="block-options")
            yield Label("", id="block-error")
            yield Label("Enter toggles · ↑↓ moves · Esc closes", id="block-hint")

    def on_mount(self) -> None:
        self._load()
        self.query_one("#block-search", Input).focus()

    def _load(self) -> None:
        """Read the candidates, degrading a storage failure to the inline
        error — an unreadable database must not close the dialog."""
        try:
            item = show_todo(self._storage, self._blocked_id)
            self._blocker_ids = set(item.blocked_by)
            self._candidates = [
                i
                for i in list_todos(self._storage, include_done=True)
                if i.id != self._blocked_id
            ]
        except TodoError as exc:
            self._candidates = []
            self._blocker_ids = set()
            self._show_error(exc)
        self._populate()

    def _populate(self) -> None:
        query = self.query_one("#block-search", Input).value.strip().casefold()
        matches = [i for i in self._candidates if _matches_item(i, query)]
        # Current blockers first: they are what you came to remove.
        matches.sort(key=lambda i: i.id not in self._blocker_ids)

        options = self.query_one("#block-options", OptionList)
        options.clear_options()
        self._shown_ids = [i.id for i in matches]
        for i in matches:
            mark = "✓" if i.id in self._blocker_ids else " "
            # Text, never markup: titles are user-controlled.
            options.add_option(Option(Text(f"{mark} #{i.id}  {i.title}")))
        if self._shown_ids:
            options.highlighted = 0

    def _show_error(self, exc: Exception) -> None:
        # Error text can echo raw user input; never render it as markup.
        self.query_one("#block-error", Label).update(
            Text(str(exc) or "Could not change the blocker")
        )

    @on(Input.Changed, "#block-search")
    def on_search_changed(self) -> None:
        self._populate()

    def action_highlight_next(self) -> None:
        self.query_one("#block-options", OptionList).action_cursor_down()

    def action_highlight_previous(self) -> None:
        self.query_one("#block-options", OptionList).action_cursor_up()

    @on(Input.Submitted, "#block-search")
    def on_submit(self) -> None:
        value = self.query_one("#block-search", Input).value.strip()
        # "-3" still removes blocker #3 outright, as it always has.
        if value.startswith("-") and value[1:].isdigit():
            self._toggle(int(value[1:]), removing=True)
            return
        options = self.query_one("#block-options", OptionList)
        index = options.highlighted
        if index is None or not (0 <= index < len(self._shown_ids)):
            return
        blocker_id = self._shown_ids[index]
        self._toggle(blocker_id, removing=blocker_id in self._blocker_ids)

    def _toggle(self, blocker_id: int, *, removing: bool) -> None:
        try:
            if removing:
                unblock_todo(self._storage, self._blocked_id, blocker_id)
            else:
                block_todo(self._storage, self._blocked_id, blocker_id)
        except TodoError as exc:
            # Cycles, unknown ids, AND storage-level failures (e.g. a locked
            # database): report inline, never crash, never close.
            self._show_error(exc)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class InspectDialog(ModalScreen[None]):
    """Read-only modal showing the full content of a todo item."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("i", "close", "Close"),
    ]

    def __init__(self, item: TodoItem) -> None:
        super().__init__()
        self._item = item

    def compose(self) -> ComposeResult:
        item = self._item
        with Vertical(id="inspect-container"):
            yield Static(
                f"[b]#{item.id}  {escape_markup(item.title)}[/b]", id="inspect-title"
            )
            yield Static("\n".join(meta_lines(item)), id="inspect-meta")
            with VerticalScroll(id="inspect-body-scroll"):
                yield Static(
                    Text(item.body) if item.body else "[dim](no description)[/dim]",
                    id="inspect-body",
                )
            yield Label("Esc / q / i to close", id="inspect-hint")

    def action_close(self) -> None:
        self.dismiss()
