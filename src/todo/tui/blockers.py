"""The dependency picker: a menu of candidates you can search from.

One dialog for both ends of the relation. A dependency is an edge between
two items, owned by neither: "#3 blocks #1" and "#1 waits on #3" are the
same row in the same table, so the only thing that changes between the two
directions is which way round the edge is written.
"""

from __future__ import annotations

from enum import Enum

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemStore
from todo.application.queries.list_todos import ListTodos
from todo.application.queries.load_dependencies import LoadDependencies
from todo.application.queries.show_todo import ShowTodo
from todo.application.workflows.add_blocker import AddBlocker
from todo.application.workflows.remove_blocker import RemoveBlocker
from todo.domain.item_filter import ItemFilter
from todo.domain.item_id import ItemId
from todo.domain.todo_item import TodoItem
from todo.exceptions import TodoError


def _is_exact_id(item: TodoItem, query: str) -> bool:
    return bool(query) and query.lstrip("#") == str(item.id)


def _matches_item(item: TodoItem, query: str) -> bool:
    """Search matches the title or the id, with or without the '#'."""
    if not query:
        return True
    return query in item.title.casefold() or _is_exact_id(item, query)


class Relation(Enum):
    """Which end of the edge the dialog is editing."""

    WAITS_ON = "waits on"
    BLOCKS = "blocks"


class BlockDialog(ModalScreen[bool]):
    """Pick what an item waits on — or what waits on it — from a list.

    Every other item is a candidate; the ones already on the chosen end of
    the relation are marked and sorted first, and choosing one toggles the
    edge. Typing narrows by title or id — nobody should have to remember
    the number of the thing that blocks them.

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

    def __init__(
        self,
        items: ItemStore,
        dependencies: DependencyStore,
        item_id: ItemId,
        relation: Relation = Relation.WAITS_ON,
    ) -> None:
        super().__init__()
        self._items = items
        self._dependencies = dependencies
        self._item_id = item_id
        self._relation = relation
        self._candidates: list[TodoItem] = []
        self._related_ids: set[ItemId] = set()
        self._shown_ids: list[ItemId] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="block-container"):
            question = (
                f"What does #{self._item_id} wait on?"
                if self._relation is Relation.WAITS_ON
                else f"What waits on #{self._item_id}?"
            )
            yield Label(question, id="block-title")
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
            ShowTodo(self._items).execute(self._item_id)  # raises if it is gone
            graph = LoadDependencies(self._dependencies).execute()
            self._related_ids = set(
                graph.blockers_of(self._item_id)
                if self._relation is Relation.WAITS_ON
                else graph.dependents_of(self._item_id)
            )
            self._candidates = [
                i
                for i in ListTodos(self._items).execute(ItemFilter(include_done=True))
                if i.id != self._item_id
            ]
        except TodoError as exc:
            self._candidates = []
            self._related_ids = set()
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
                i.id not in self._related_ids,
            )
        )

        options = self.query_one("#block-options", OptionList)
        options.clear_options()
        self._shown_ids = [i.id for i in matches]
        for i in matches:
            mark = "✓" if i.id in self._related_ids else " "
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
            Text(str(exc) or "Could not change the dependency")
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
        other_id = self._shown_ids[index]
        self._toggle(other_id, removing=other_id in self._related_ids)

    def _toggle(self, other_id: ItemId, *, removing: bool) -> None:
        # The edge always reads (blocked, blocker); which of the two ids is
        # which is the only thing the direction decides.
        if self._relation is Relation.WAITS_ON:
            blocked_id, blocker_id = self._item_id, other_id
        else:
            blocked_id, blocker_id = other_id, self._item_id
        try:
            if removing:
                RemoveBlocker(self._items, self._dependencies).execute(
                    blocked_id, [blocker_id]
                )
            else:
                AddBlocker(self._items, self._dependencies).execute(
                    blocked_id, [blocker_id]
                )
        except TodoError as exc:
            # Cycles, unknown ids, AND storage-level failures (e.g. a locked
            # database): report inline, never crash, never close.
            self._show_error(exc)
            return
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class BlockerPicker(ModalScreen[frozenset[ItemId]]):
    """Mark what a not-yet-created item will wait on.

    The same searchable menu as BlockDialog, with one difference of
    contract: the item does not exist yet, so there is no edge to write.
    Choosing toggles a mark instead of applying a change, and Esc hands
    the marked set back to the form that opened it. Closing and being
    done are the same thing — what is marked is what was chosen, and a
    picker opened again starts from that.
    """

    BINDINGS = [Binding("escape", "done", "Done")]

    def __init__(self, items: ItemStore, selected: frozenset[ItemId]) -> None:
        super().__init__()
        self._items = items
        self._selected: set[ItemId] = set(selected)
        self._candidates: list[TodoItem] = []
        self._shown_ids: list[ItemId] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="block-container"):
            yield Label("What will this wait on?", id="block-title")
            search = Input(id="block-search", placeholder="Type to filter")
            # A readout of the filter, not a destination: focus belongs to
            # the menu, and Tab or a stray click must not move it here.
            search.can_focus = False
            yield search
            yield OptionList(id="block-options")
            yield Label("", id="block-error")
            yield Label(
                "↑↓ move · Enter toggle · type to filter · Esc done",
                id="block-hint",
            )

    def on_mount(self) -> None:
        self._load()
        self.query_one("#block-options", OptionList).focus()

    def on_key(self, event: events.Key) -> None:
        """Typing filters the menu without leaving it — same contract as
        BlockDialog's."""
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
        self.query_one("#block-search", Input).value = value

    def _load(self) -> None:
        try:
            self._candidates = ListTodos(self._items).execute(
                ItemFilter(include_done=True)
            )
        except TodoError as exc:
            self._candidates = []
            self._show_error(exc)
        # Marked rows first, decided ONCE at load: a picker opened again
        # leads with what was chosen before, but a toggle never resorts
        # the menu under the cursor.
        self._candidates.sort(key=lambda i: i.id not in self._selected)
        self._populate()

    def _populate(self) -> None:
        query = self.query_one("#block-search", Input).value.strip().casefold()
        matches = [i for i in self._candidates if _matches_item(i, query)]
        # An id typed exactly designates that item.
        matches.sort(key=lambda i: not _is_exact_id(i, query))

        options = self.query_one("#block-options", OptionList)
        highlighted = options.highlighted
        options.clear_options()
        self._shown_ids = [i.id for i in matches]
        for i in matches:
            mark = "✓" if i.id in self._selected else " "
            # Text, never markup: titles are user-controlled.
            options.add_option(Option(Text(f"{mark} #{i.id}  {i.title}")))
        if not self._shown_ids:
            options.highlighted = None
        elif highlighted is None:
            options.highlighted = 0
        else:
            # A toggle redraws the marks; the cursor stays on its row so
            # several blockers can be marked without re-navigating.
            options.highlighted = min(highlighted, len(self._shown_ids) - 1)

    def _show_error(self, exc: Exception) -> None:
        # Error text can echo raw user input; never render it as markup.
        self.query_one("#block-error", Label).update(
            Text(str(exc) or "Could not read the items")
        )

    @on(Input.Changed, "#block-search")
    def on_search_changed(self) -> None:
        # A changed filter is a fresh navigation: the cursor belongs on
        # the first match, not wherever it sat in the old rows.
        self.query_one("#block-options", OptionList).highlighted = None
        self._populate()

    @on(OptionList.OptionSelected, "#block-options")
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        index = event.option_index
        if not (0 <= index < len(self._shown_ids)):
            return
        toggled = self._shown_ids[index]
        if toggled in self._selected:
            self._selected.discard(toggled)
        else:
            self._selected.add(toggled)
        self._populate()

    def action_done(self) -> None:
        self.dismiss(frozenset(self._selected))
