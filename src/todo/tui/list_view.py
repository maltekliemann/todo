from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import DataTable, Footer, Static

from todo.application.contracts.counter_store import CounterStore
from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemStore
from todo.application.queries.list_tags import ListTags
from todo.application.queries.list_todos import ListTodos
from todo.application.queries.load_dependencies import DoneIds, LoadDependencies
from todo.application.queries.show_todo import ShowTodo
from todo.application.toast import Toast
from todo.application.workflows.delete_todo import DeleteTodo
from todo.application.workflows.set_status import SetStatus
from todo.domain.dependency_graph import DependencyGraph
from todo.domain.item_filter import ItemFilter
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.todo_item import TodoItem
from todo.exceptions import NotFoundError, TodoError
from todo.tui.blockers import BlockDialog
from todo.tui.detail import DetailPane
from todo.tui.dialogs import ConfirmDialog, NewItemDialog, SearchDialog
from todo.tui.filters import Filters
from todo.tui.item_screen import ItemScreen
from todo.tui.render import escape_markup, toast_messages
from todo.tui.table import COLUMNS, TodoTable, is_separator

_STATUS_GROUP = Binding.Group("Status", compact=True)
_FILTER_GROUP = Binding.Group("Filter", compact=True)


class TodoListView(Widget):
    # The footer is a single non-wrapping row: every description here is
    # paying for itself in columns, and related keys are grouped under one
    # label rather than repeating a word each.
    BINDINGS = [
        Binding("n", "new", "New", show=True),
        # One screen for reading an item and for changing it, so there is
        # no "which key was the editable one?".
        Binding("i,e", "open", "Open", show=True),
        Binding("d", "done", "Done", show=True),
        Binding("x,delete", "delete", "Del", show=True),
        Binding("b", "block", "Block", show=True),
        Binding(
            "less_than_sign",
            "status_prev",
            "Status <",
            key_display="<",
            group=_STATUS_GROUP,
        ),
        Binding(
            "greater_than_sign",
            "status_next",
            "Status >",
            key_display=">",
            group=_STATUS_GROUP,
        ),
        # 1-4 stay out of the footer: four more keys plus their group
        # label is 17 columns, and the priority digits are the easiest
        # bindings to guess.
        Binding("1", "filter_priority('urgent')", "Urgent", show=False),
        Binding("2", "filter_priority('high')", "High", show=False),
        Binding("3", "filter_priority('medium')", "Medium", show=False),
        Binding("4", "filter_priority('low')", "Low", show=False),
        Binding("slash", "search", "Search", key_display="/", group=_FILTER_GROUP),
        Binding("t", "cycle_tag", "Tag filter", group=_FILTER_GROUP),
        Binding("0", "clear_filters", "Clear filters", group=_FILTER_GROUP),
        Binding(
            "full_stop", "toggle_cursor_mode", "Cursor", key_display=".", show=True
        ),
        Binding("q", "quit_app", "Quit", show=True),
        # Not in the footer: escape duplicates what 0 does, and the footer
        # row is the scarce resource.
        Binding("escape", "clear_search", "Clear filter", show=False),
    ]

    def __init__(
        self,
        items: ItemStore,
        dependencies: DependencyStore,
        item_ids: CounterStore,
    ) -> None:
        super().__init__()
        self._item_store = items
        self._dependency_store = dependencies
        self._item_id_counter = item_ids
        self._items: list[TodoItem] = []
        self._item_by_id: dict[ItemId, TodoItem] = {}
        self._graph = DependencyGraph(frozenset())
        self._done: frozenset[ItemId] = frozenset()
        self._filters = Filters()
        self._cursor_follows_item: bool = True
        # One error toast per failure streak: a persistently broken
        # database must not stack a notification every poll tick.
        self._read_error_reported: bool = False

    def compose(self) -> ComposeResult:
        yield TodoTable(id="item-list", cursor_type="row", zebra_stripes=True)
        yield DetailPane(id="detail-panel")
        yield Static("", id="search-status")
        yield Footer(compact=True, show_command_palette=False)

    def on_mount(self) -> None:
        table = self.query_one("#item-list", DataTable)
        table.add_columns(*COLUMNS)
        table.focus()
        self._refresh_list()

    def _report_read_failure(self, exc: TodoError, *, from_poll: bool) -> None:
        """Notify about a failed read, once per failure streak when the
        poll timer is the source — an unattended 2s loop must not stack a
        toast per tick. Failures the user just triggered always report."""
        if from_poll and self._read_error_reported:
            return
        self._read_error_reported = True
        self.notify(escape_markup(str(exc)), severity="error")

    @on(DataTable.RowHighlighted, "#item-list")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:
            self._update_detail(event.row_key.value)

    @on(TodoTable.StatusStep, "#item-list")
    def on_status_step(self, event: TodoTable.StatusStep) -> None:
        if event.delta > 0:
            self.action_status_next()
        else:
            self.action_status_prev()

    @on(DataTable.RowSelected, "#item-list")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key is None or is_separator(event.row_key.value):
            return
        self.action_open()

    def _refresh_list(
        self, *, from_poll: bool = False, select_id: ItemId | None = None
    ) -> None:
        """Refresh, degrading storage failures to a notification.

        Every action path (including the except-handlers of guarded
        mutations) ends in a refresh, so a raw StorageError here would
        crash the session no matter how well the action itself is guarded.

        `select_id` asks for a specific item under the cursor afterwards;
        it wins over both cursor modes, and is ignored if that item is not
        in the refreshed list.
        """
        try:
            self._refresh_list_unguarded(select_id=select_id)
        except TodoError as exc:
            self._report_read_failure(exc, from_poll=from_poll)
        else:
            self._read_error_reported = False

    def _successor_id(self, item_id: ItemId) -> ItemId | None:
        """The item listed after `item_id` right now.

        Stay mode is "let me move a run of items without chasing the
        cursor", and holding a row index does not deliver that: a status
        step re-sorts the moved item to the top of its new group, which is
        frequently the very row the cursor held. Naming the next item is
        what the mode actually means.
        """
        ids = [i.id for i in self._items]
        try:
            index = ids.index(item_id)
        except ValueError:
            return None
        return ids[index + 1] if index + 1 < len(ids) else None

    def _successor_if_staying(self, item_id: ItemId) -> ItemId | None:
        return None if self._cursor_follows_item else self._successor_id(item_id)

    def _rows_for_refresh(self) -> list[TodoItem]:
        """Every read a refresh needs."""

        # Tag and priority filtering happens in SQL via list_todos; only
        # the search filter stays in Filters, because it also matches tag
        # names, which storage-level search (title/body) does not cover.
        return ListTodos(self._item_store).execute(
            ItemFilter(
                include_done=True,
                tags=frozenset({Tag(self._filters.tag)} if self._filters.tag else ()),
                priority=self._filters.priority,
            )
        )

    def _refresh_list_unguarded(self, *, select_id: ItemId | None = None) -> None:
        table = self.query_one("#item-list", TodoTable)
        previous_id = self._selected_item_id()
        previous_cursor = table.cursor_row

        # All storage reads happen BEFORE the table is touched: a degraded
        # (notified) read failure must leave the last good rows visible,
        # not wipe the list into a dead blank state.
        items = self._rows_for_refresh()
        self._items = self._filters.apply_search(items)

        # The detail pane renders from this cache instead of re-querying
        # storage on every cursor move; the refresh that builds the rows is
        # the same one that builds the cache, so they cannot disagree.
        self._item_by_id = {i.id: i for i in self._items}

        # One load for the whole refresh: the rows and the detail pane
        # must answer from the same graph.
        self._graph = LoadDependencies(self._dependency_store).execute()
        self._done = DoneIds(self._item_store).execute()
        row_index_of = table.populate(self._items, self._graph, self._done)

        if table.row_count > 0:
            follow = self._cursor_follows_item
            if select_id is not None and select_id in row_index_of:
                table.move_cursor(row=row_index_of[select_id])
            elif follow and previous_id is not None and previous_id in row_index_of:
                table.move_cursor(row=row_index_of[previous_id])
            elif row_index_of:
                # Stay at the same visual row (sticky mode / item vanished);
                # land on an item row, not a separator.
                first_item_row = min(row_index_of.values())
                clamped = min(previous_cursor, table.row_count - 1)
                target = clamped if clamped >= first_item_row else first_item_row
                table.move_cursor(row=target)
                table._skip_separators(1)
            else:
                table.move_cursor(row=0)
        else:
            # An emptied table fires no RowHighlighted event, so the pane
            # would keep showing a deleted/filtered-out item forever.
            self._update_detail(None)

        # Record the version captured BEFORE the reads above, so a write
        # that landed during them is still pending for the next poll.

        search_status = self.query_one("#search-status", Static)
        parts = self._filters.status_parts()
        hint = "  [dim]([0] clears)[/dim]" if parts else ""
        if not self._cursor_follows_item:
            parts.append("[dim]Cursor:[/dim] [b]advance[/b]")
        if parts:
            search_status.update("  ".join(parts) + hint)
        else:
            search_status.update("")

    def _update_detail(self, item_id: object) -> None:
        pane = self.query_one("#detail-panel", DetailPane)
        if item_id is None or is_separator(item_id):
            pane.clear()
            return

        try:
            key = ItemId(int(str(item_id)))
        except (TypeError, ValueError):
            return
        # _refresh_list already hydrated this item; render from the cache
        # instead of re-running four SQL queries per cursor move. The row
        # keys and the cache come from the same refresh, so a miss only
        # means a stale event — fall back to a guarded query.
        item = self._item_by_id.get(key)
        if item is None:
            try:
                item = ShowTodo(self._item_store).execute(key)
            except TodoError:
                return

        pane.show(item, self._graph)

    def _selected_item_id(self) -> ItemId | None:
        table = self.query_one("#item-list", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:
            return None
        if row_key.value is None or is_separator(row_key.value):
            return None
        try:
            return ItemId(int(str(row_key.value)))
        except (ValueError, TypeError):
            return None

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_new(self) -> None:
        def after(item: TodoItem | None) -> None:
            if item is not None:
                # The next action is almost always about the new item, so
                # it lands under the cursor — unless a filter hides it, in
                # which case select_id is ignored and the cursor stays.
                self._refresh_list(select_id=item.id)

        self.app.push_screen(
            NewItemDialog(
                self._item_store, self._dependency_store, self._item_id_counter
            ),
            after,
        )

    def action_done(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        successor = self._successor_if_staying(item_id)
        try:
            toasts = SetStatus(self._item_store, self._dependency_store).execute(
                item_id, Status.DONE
            )
        except TodoError as exc:
            # E.g. deleted by another process, or the database is locked.
            self.notify(escape_markup(str(exc)), severity="error")
            self._refresh_list()
            return
        self._notify_unblocked(toasts)
        self._refresh_list(select_id=successor)

    def _notify_unblocked(self, toasts: list[Toast]) -> None:
        titles = {i.id: str(i.title) for i in self._items}
        for message in toast_messages(toasts, titles):
            self.notify(message)

    def action_open(self) -> None:
        """Open the selected item's own screen: every field, editable.

        The item is read here rather than inside the screen so a stale row
        (deleted by another process, or by a poll that has not landed yet)
        never opens an empty screen.
        """
        item_id = self._selected_item_id()
        if item_id is None:
            return
        try:
            item = ShowTodo(self._item_store).execute(item_id)
        except NotFoundError:
            return
        except TodoError as exc:
            self.notify(escape_markup(str(exc)), severity="error")
            return

        def after(changed: bool | None) -> None:
            if changed:
                self._refresh_list()

        self.app.push_screen(
            ItemScreen(self._item_store, self._dependency_store, item),
            after,
        )

    def action_delete(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return

        def after(confirmed: bool | None) -> None:
            if confirmed:
                try:
                    unblocked = DeleteTodo(
                        self._item_store, self._dependency_store
                    ).execute(item_id)
                except TodoError as exc:
                    # E.g. deleted by another process while the dialog was open.
                    self.notify(escape_markup(str(exc)), severity="error")
                else:
                    self._notify_unblocked(unblocked)
                self._refresh_list()

        self.app.push_screen(ConfirmDialog(f"Delete #{item_id}?"), after)

    def action_block(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return

        def after(changed: bool | None) -> None:
            if changed:
                self._refresh_list()

        self.app.push_screen(
            BlockDialog(self._item_store, self._dependency_store, item_id), after
        )

    def action_search(self) -> None:
        def after(query: str | None) -> None:
            if query is not None:
                self._filters.search = query
                self._refresh_list()

        self.app.push_screen(SearchDialog(), after)

    def action_clear_search(self) -> None:
        if self._filters.search:
            self._filters.search = ""
            self._refresh_list()

    def action_cycle_tag(self) -> None:
        try:
            tags = [str(c.tag) for c in ListTags(self._item_store).execute()]
        except TodoError as exc:
            self.notify(escape_markup(str(exc)), severity="error")
            return
        self._filters.cycle_tag(tags)
        self._refresh_list()

    def action_filter_priority(self, value: str) -> None:
        self._filters.toggle_priority(Priority.from_string(value))
        self._refresh_list()

    def action_toggle_cursor_mode(self) -> None:
        """Toggle what the cursor does after you move the selected item.

        'Follow item' keeps it on that item wherever it lands. 'Advance to
        next' moves it to the item that came after, so holding 'd' or '>'
        walks a list top-down.
        """
        self._cursor_follows_item = not self._cursor_follows_item
        mode = "follow item" if self._cursor_follows_item else "advance to next"
        self.notify(f"Cursor mode: {mode}")
        self._refresh_list()

    def action_clear_filters(self) -> None:
        if self._filters.any_active():
            self._filters.clear()
            self._refresh_list()

    def action_status_next(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        try:
            item = ShowTodo(self._item_store).execute(item_id)
        except NotFoundError:
            return
        except TodoError as exc:
            self.notify(escape_markup(str(exc)), severity="error")
            return
        next_status = item.status.next()
        if next_status is not None:
            successor = self._successor_if_staying(item_id)
            try:
                toasts = SetStatus(self._item_store, self._dependency_store).execute(
                    item_id, next_status
                )
            except TodoError as exc:
                self.notify(escape_markup(str(exc)), severity="error")
                self._refresh_list()
                return
            self._notify_unblocked(toasts)
            self._refresh_list(select_id=successor)

    def action_status_prev(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        try:
            item = ShowTodo(self._item_store).execute(item_id)
        except NotFoundError:
            return
        except TodoError as exc:
            self.notify(escape_markup(str(exc)), severity="error")
            return
        prev_status = item.status.prev()
        if prev_status is not None:
            successor = self._successor_if_staying(item_id)
            try:
                SetStatus(self._item_store, self._dependency_store).execute(
                    item_id, prev_status
                )
            except TodoError as exc:
                self.notify(escape_markup(str(exc)), severity="error")
                self._refresh_list()
                return
            self._refresh_list(select_id=successor)
