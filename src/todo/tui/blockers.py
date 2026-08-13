"""The blocker picker: a menu of candidates you can search from."""

from __future__ import annotations

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from todo.application.commands import block_todo, unblock_todo
from todo.application.contracts.storage import StorageProtocol
from todo.application.queries import list_todos, show_todo
from todo.domain.models import TodoItem
from todo.exceptions import TodoError


def _is_exact_id(item: TodoItem, query: str) -> bool:
    return bool(query) and query.lstrip("#") == str(item.id)


def _matches_item(item: TodoItem, query: str) -> bool:
    """Search matches the title or the id, with or without the '#'."""
    if not query:
        return True
    return query in item.title.casefold() or _is_exact_id(item, query)


class BlockDialog(ModalScreen[bool]):
    """Pick what an item waits on, from a searchable list.

    Every other item is a candidate; the ones already blocking this item
    are marked and sorted first, and choosing one toggles the relation.
    Typing narrows by title or id — nobody should have to remember the
    number of the thing that blocks them.

    It is a menu you can search from: the list holds focus from the moment
    it opens, with a row under the cursor. Up/down walk it, Enter chooses
    the highlighted row, and typing filters in place. The search box
    displays the filter and never takes focus — typing is a way to narrow
    the menu, not the way into it.

    Choosing applies the change and closes, as it always has. The command
    call happens here so validation, cycle and storage errors show inline
    instead of closing the dialog on the user's work.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

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
            search = Input(id="block-search", placeholder="Type to filter")
            # A readout of the filter, not a destination: focus belongs to
            # the menu, and Tab or a stray click must not move it here.
            search.can_focus = False
            yield search
            yield OptionList(id="block-options")
            yield Label("", id="block-error")
            yield Label(
                "↑↓ move · Enter choose · type to filter · Esc close", id="block-hint"
            )

    def on_mount(self) -> None:
        self._load()
        self.query_one("#block-options", OptionList).focus()

    def on_key(self, event: events.Key) -> None:
        """Typing filters the menu without leaving it.

        The list has focus, so printable keys arrive here unclaimed; they
        edit the filter instead of falling on the floor. Keys the list
        binds (up/down, Enter, Home/End, page keys) never reach this
        handler.
        """
        if event.key == "backspace":
            self._set_query(self._query[:-1])
            event.stop()
        elif event.character is not None and event.character.isprintable():
            self._set_query(self._query + event.character)
            event.stop()

    @property
    def _query(self) -> str:
        return self.query_one("#block-search", Input).value

    def _set_query(self, value: str) -> None:
        # Writing the Input fires Input.Changed, which repopulates: one
        # path from filter text to rows, whoever changed it.
        self.query_one("#block-search", Input).value = value

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
        matches.sort(
            key=lambda i: (
                # An id typed exactly designates that item, the way the
                # id prompt this replaced did. Then current blockers,
                # which are what you came to remove.
                not _is_exact_id(i, query),
                i.id not in self._blocker_ids,
            )
        )

        options = self.query_one("#block-options", OptionList)
        options.clear_options()
        self._shown_ids = [i.id for i in matches]
        for i in matches:
            mark = "✓" if i.id in self._blocker_ids else " "
            # Text, never markup: titles are user-controlled.
            options.add_option(Option(Text(f"{mark} #{i.id}  {i.title}")))
        # A stale rejection under a fresh candidate reads as "this one is
        # no good either".
        self._clear_error()
        # A menu always has a row under the cursor.
        options.highlighted = 0 if self._shown_ids else None

    def _show_error(self, exc: Exception) -> None:
        # Error text can echo raw user input; never render it as markup.
        self.query_one("#block-error", Label).update(
            Text(str(exc) or "Could not change the blocker")
        )

    def _clear_error(self) -> None:
        self.query_one("#block-error", Label).update("")

    @on(Input.Changed, "#block-search")
    def on_search_changed(self) -> None:
        self._populate()

    def action_highlight_next(self) -> None:
        self.query_one("#block-options", OptionList).action_cursor_down()

    def action_highlight_previous(self) -> None:
        self.query_one("#block-options", OptionList).action_cursor_up()

    @on(OptionList.OptionSelected, "#block-options")
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        # Clicking a candidate is choosing it. Without this the click only
        # moved focus into the list, leaving the dialog inert.
        self._choose(event.option_index)

    def _choose(self, index: int | None) -> None:
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
