from __future__ import annotations

import os
import subprocess
import tempfile

from rich.text import Text
from textual import on
from textual.app import ComposeResult, SuspendNotSupported
from textual.binding import Binding
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import DataTable, Footer, Static

from todo.application.commands import (
    CompletionResult,
    complete_todo,
    delete_todo,
    move_todo,
)
from todo.application.contracts.storage import StorageProtocol
from todo.application.queries import (
    count_tags,
    list_all_projects,
    list_todos,
    show_todo,
)
from todo.domain.enums import Priority
from todo.domain.models import TodoItem
from todo.exceptions import NotFoundError, TodoError
from todo.tui.dialogs import (
    BlockDialog,
    ConfirmDialog,
    InspectDialog,
    NewItemDialog,
    SearchDialog,
)
from todo.tui.editor import apply_editor_edit, editor_command, item_to_editor_text
from todo.tui.render import escape_markup, meta_lines
from todo.tui.table import COLUMNS, TodoTable, is_separator


class TodoListView(Widget):
    BINDINGS = [
        Binding("q", "quit_app", "Quit", show=True),
        Binding("n", "new", "New", show=True),
        Binding("i", "inspect", "Inspect", show=True),
        Binding("d", "done", "Done", show=True),
        Binding("e", "edit", "Edit", show=True),
        Binding("x,delete", "delete", "Delete", show=True),
        Binding("b", "block", "Block", show=True),
        Binding("greater_than_sign", "status_next", "Status >", show=True),
        Binding("less_than_sign", "status_prev", "Status <", show=True),
        Binding("slash", "search", "Search", show=True),
        Binding("t", "cycle_tag", "Tag filter", show=True),
        Binding("p", "cycle_project", "Project filter", show=True),
        Binding("1", "filter_priority('urgent')", "Urgent", show=False),
        Binding("2", "filter_priority('high')", "High", show=False),
        Binding("3", "filter_priority('medium')", "Medium", show=False),
        Binding("4", "filter_priority('low')", "Low", show=False),
        Binding("0", "clear_filters", "Clear filters", show=True),
        Binding("escape", "clear_search", "Clear filter", show=True),
        Binding("full_stop", "toggle_cursor_mode", "Cursor mode", show=True),
    ]

    POLL_INTERVAL_SECONDS = 2.0

    def __init__(self, storage: StorageProtocol) -> None:
        super().__init__()
        self._storage = storage
        self._items: list[TodoItem] = []
        self._item_by_id: dict[int, TodoItem] = {}
        self._search_query: str = ""
        self._tag_filter: str | None = None
        # Keyed on the stable project id, not the mutable name — an
        # external rename must not blank the filtered list. The name is
        # remembered alongside it so a deleted project can still be named
        # in the status bar instead of degrading to '?'.
        self._project_filter: int | None = None
        self._project_filter_name: str | None = None
        self._priority_filter: Priority | None = None
        self._cursor_follows_item: bool = True
        self._last_data_version: int = 0
        # One error toast per failure streak: a persistently broken
        # database must not stack a notification every poll tick.
        self._read_error_reported: bool = False

    def compose(self) -> ComposeResult:
        yield TodoTable(id="item-list", cursor_type="row", zebra_stripes=True)
        with Vertical(id="detail-panel"):
            yield Static("", id="detail-title")
            yield Static("", id="detail-meta")
            yield Static("", id="detail-body")
        yield Static("", id="search-status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#item-list", DataTable)
        table.add_columns(*COLUMNS)
        table.focus()
        # _refresh_list_unguarded is the ONLY writer of _last_data_version:
        # recording a version without a successful refresh would make the
        # poll see "no change" forever and never retry after a failure.
        self._refresh_list()
        self.set_interval(self.POLL_INTERVAL_SECONDS, self._poll_for_external_changes)

    def _poll_for_external_changes(self) -> None:
        try:
            version = self._storage.data_version()
        except TodoError as exc:
            # A broken database must not let the 2s timer kill the session.
            self._report_read_failure(exc, from_poll=True)
            return
        if version != self._last_data_version:
            # No version bookkeeping here: only a successful refresh
            # records it, so a failed refresh is retried next tick.
            self._refresh_list(from_poll=True)

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
        self.action_inspect()

    def _refresh_list(self, *, from_poll: bool = False) -> None:
        """Refresh, degrading storage failures to a notification.

        Every action path (including the except-handlers of guarded
        mutations) ends in a refresh, so a raw StorageError here would
        crash the session no matter how well the action itself is guarded.
        """
        try:
            self._refresh_list_unguarded()
        except TodoError as exc:
            self._report_read_failure(exc, from_poll=from_poll)
        else:
            self._read_error_reported = False

    def _rows_for_refresh(self) -> tuple[int, list[TodoItem], str | None]:
        """Every storage read a refresh needs, plus the data_version read
        BEFORE them.

        Reading the version first is what makes the poll safe: a commit
        landing while these reads (and the ensuing table rebuild) are in
        flight is newer than the version we return, so the next tick still
        sees a change and displays it. A version read afterwards would
        record that concurrent write as already seen and lose it.

        Returns (version, items, project_filter_label).
        """
        version = self._storage.data_version()

        # Tag/priority/project filtering happens in SQL via list_todos; only
        # the search filter stays here because it also matches tag names,
        # which storage-level search (title/body) does not cover.
        project_filter_id = self._project_filter
        project_filter_label = self._project_filter_name
        project_filter_missing = False
        if project_filter_id is not None:
            match = next(
                (
                    p
                    for p in list_all_projects(self._storage, include_archived=True)
                    if p.id == project_filter_id
                ),
                None,
            )
            if match is None:
                project_filter_missing = True
            else:
                # Label from the live row, so a rename shows the new name.
                project_filter_label = match.name
                self._project_filter_name = match.name

        if project_filter_missing:
            # Filtered project no longer exists: show nothing, like before,
            # but keep naming it — the last known name beats a bare '?'.
            return version, [], project_filter_label
        return (
            version,
            list_todos(
                self._storage,
                include_done=True,
                tags=[self._tag_filter] if self._tag_filter is not None else None,
                priority=self._priority_filter,
                project_id=project_filter_id,
            ),
            project_filter_label,
        )

    def _refresh_list_unguarded(self) -> None:
        table = self.query_one("#item-list", TodoTable)
        previous_id = self._selected_item_id()
        previous_cursor = table.cursor_row

        # All storage reads happen BEFORE the table is touched: a degraded
        # (notified) read failure must leave the last good rows visible,
        # not wipe the list into a dead blank state.
        version, self._items, project_filter_label = self._rows_for_refresh()

        if self._search_query:
            # casefold, matching the storage layer's SQL search semantics.
            q = self._search_query.casefold()
            self._items = [
                i
                for i in self._items
                if q in i.title.casefold()
                or q in i.body.casefold()
                or any(q in t.casefold() for t in i.tags)
            ]

        # The detail pane renders from this cache instead of re-querying
        # storage on every cursor move; the refresh that builds the rows is
        # the same one that builds the cache, so they cannot disagree.
        self._item_by_id = {i.id: i for i in self._items}

        row_index_of = table.populate(self._items)

        if table.row_count > 0:
            follow = self._cursor_follows_item
            if follow and previous_id is not None and previous_id in row_index_of:
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
        self._last_data_version = version

        search_status = self.query_one("#search-status", Static)
        parts: list[str] = []
        if self._search_query:
            parts.append(
                f"[dim]Search:[/dim] [b]{escape_markup(self._search_query)}[/b]"
            )
        if self._tag_filter is not None:
            parts.append(f"[dim]Tag:[/dim] [b]{escape_markup(self._tag_filter)}[/b]")
        if self._project_filter is not None:
            label = escape_markup(project_filter_label or "?")
            parts.append(f"[dim]Project:[/dim] [b]{label}[/b]")
        if self._priority_filter is not None:
            parts.append(f"[dim]Priority:[/dim] [b]{self._priority_filter.value}[/b]")
        hint = "  [dim]([0] clears)[/dim]" if parts else ""
        if not self._cursor_follows_item:
            parts.append("[dim]Cursor:[/dim] [b]stay[/b]")
        if parts:
            search_status.update("  ".join(parts) + hint)
        else:
            search_status.update("")

    def _update_detail(self, item_id: object) -> None:
        if item_id is None or is_separator(item_id):
            self.query_one("#detail-title", Static).update("")
            self.query_one("#detail-meta", Static).update("")
            self.query_one("#detail-body", Static).update("")
            return

        try:
            key = int(str(item_id))
        except (TypeError, ValueError):
            return
        # _refresh_list already hydrated this item; render from the cache
        # instead of re-running four SQL queries per cursor move. The row
        # keys and the cache come from the same refresh, so a miss only
        # means a stale event — fall back to a guarded query.
        item = self._item_by_id.get(key)
        if item is None:
            try:
                item = show_todo(self._storage, key)
            except TodoError:
                return

        title_w = self.query_one("#detail-title", Static)
        meta_w = self.query_one("#detail-meta", Static)
        body_w = self.query_one("#detail-body", Static)

        title_w.update(f"[b]#{item.id}  {escape_markup(item.title)}[/b]")
        meta_w.update("\n".join(meta_lines(item)))
        body_w.update(Text(item.body) if item.body else "")

    def _selected_item_id(self) -> int | None:
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
            return int(str(row_key.value))
        except (ValueError, TypeError):
            return None

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_new(self) -> None:
        def after(item: TodoItem | None) -> None:
            if item is not None:
                self._refresh_list()

        self.app.push_screen(
            NewItemDialog(self._storage, project_id=self._project_filter), after
        )

    def action_done(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        try:
            result = complete_todo(self._storage, item_id)
        except TodoError as exc:
            # E.g. deleted by another process, or the database is locked.
            self.notify(escape_markup(str(exc)), severity="error")
            self._refresh_list()
            return
        self._notify_unblocked(result)
        self._refresh_list()

    def _notify_unblocked(self, result: CompletionResult | list[TodoItem]) -> None:
        deps = result.unblocked if isinstance(result, CompletionResult) else result
        for dep in deps:
            self.notify(f"🔓 #{dep.id} {escape_markup(dep.title)} is now unblocked")

    def action_inspect(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        try:
            item = show_todo(self._storage, item_id)
        except NotFoundError:
            return
        except TodoError as exc:
            self.notify(escape_markup(str(exc)), severity="error")
            return
        self.app.push_screen(InspectDialog(item))

    def action_edit(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return

        try:
            item = show_todo(self._storage, item_id)
        except NotFoundError:
            return
        except TodoError as exc:
            self.notify(escape_markup(str(exc)), severity="error")
            return

        editor = os.environ.get("EDITOR", "vi")
        text = item_to_editor_text(item)

        try:
            tmp_path = self._write_editor_buffer(text)
        except OSError as exc:
            self.notify(f"Editor failed: {escape_markup(str(exc))}", severity="error")
            return

        try:
            with self.app.suspend():
                subprocess.run(editor_command(editor, tmp_path), check=True)
        except subprocess.CalledProcessError as exc:
            # The editor RAN and exited nonzero — the user may already have
            # saved their work into the buffer. Keep it and say where.
            self.notify(
                f"Editor failed: {escape_markup(str(exc))} — "
                f"your buffer is kept at {escape_markup(tmp_path)}",
                severity="error",
                timeout=12,
            )
            return
        except (
            ValueError,  # empty/misquoted $EDITOR
            OSError,  # missing binary, permission denied, ...
            SuspendNotSupported,
        ) as exc:
            # The editor never ran; the buffer holds nothing of the user's.
            self.notify(f"Editor failed: {escape_markup(str(exc))}", severity="error")
            os.unlink(tmp_path)
            return

        edited = self._read_edited_buffer(tmp_path)
        if edited is None:
            return

        self._apply_edited_buffer(item_id, text, edited, tmp_path)

    def _write_editor_buffer(self, text: str) -> str:
        """Write the buffer for $EDITOR, always as UTF-8.

        Explicit encoding, not the locale's: item text is arbitrary Unicode
        and a non-UTF-8 locale would fail to encode it.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".todo.txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            return f.name

    def _read_edited_buffer(self, tmp_path: str) -> str | None:
        """Read the buffer back after the editor ran; on failure, report
        where the (possibly recoverable) buffer lives — the flow must never
        strand a file with the user's work silently.

        UnicodeDecodeError (an editor that saved as latin-1/cp1252) is a
        ValueError, not an OSError, and would otherwise kill the session.
        """
        try:
            with open(tmp_path, encoding="utf-8") as f:
                return f.read()
        except (OSError, ValueError) as exc:
            self.notify(
                f"Editor failed: {escape_markup(str(exc))} — "
                f"your buffer is kept at {escape_markup(tmp_path)}",
                severity="error",
                timeout=12,
            )
            return None

    def _apply_edited_buffer(
        self, item_id: int, original: str, edited: str, tmp_path: str
    ) -> None:
        """Apply an edited $EDITOR buffer. On rejection the buffer file is
        kept and its path reported, so a field typo never destroys the
        user's work."""
        # Exact no-op check (plus the editor's final newline): anything
        # else — including whitespace-only body edits — is a real edit.
        if edited in (original, original + "\n"):
            os.unlink(tmp_path)
            return

        try:
            result = apply_editor_edit(self._storage, item_id, edited)
        except (ValueError, TodoError) as exc:
            self.notify(
                f"Edit rejected: {escape_markup(str(exc))} — "
                f"your buffer is kept at {escape_markup(tmp_path)}",
                severity="error",
                timeout=12,
            )
            return
        os.unlink(tmp_path)
        self._notify_unblocked(result)
        self._refresh_list()

    def action_delete(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return

        def after(confirmed: bool | None) -> None:
            if confirmed:
                try:
                    unblocked = delete_todo(self._storage, item_id)
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

        def after(result: str | None) -> None:
            if result is not None:
                self._refresh_list()

        self.app.push_screen(BlockDialog(self._storage, item_id), after)

    def action_search(self) -> None:
        def after(query: str | None) -> None:
            if query is not None:
                self._search_query = query
                self._refresh_list()

        self.app.push_screen(SearchDialog(), after)

    def action_clear_search(self) -> None:
        if self._search_query:
            self._search_query = ""
            self._refresh_list()

    def action_cycle_tag(self) -> None:
        """Cycle the tag filter: no filter -> each known tag -> no filter."""
        try:
            tags = [t for t, _ in count_tags(self._storage)]
        except TodoError as exc:
            self.notify(escape_markup(str(exc)), severity="error")
            return
        if not tags:
            return
        if self._tag_filter is None:
            self._tag_filter = tags[0]
        else:
            try:
                idx = tags.index(self._tag_filter)
            except ValueError:
                idx = -1
            self._tag_filter = tags[idx + 1] if idx + 1 < len(tags) else None
        self._refresh_list()

    def action_cycle_project(self) -> None:
        """Cycle the project filter: no filter -> each project -> no filter."""
        try:
            projects = list_all_projects(self._storage, include_archived=True)
        except TodoError as exc:
            self.notify(escape_markup(str(exc)), severity="error")
            return
        if not projects:
            return
        ids = [p.id for p in projects]
        if self._project_filter is None:
            idx = 0
        else:
            try:
                current = ids.index(self._project_filter)
            except ValueError:
                current = -1
            idx = current + 1
        if idx < len(ids):
            # Remember the name too: if the project is deleted while the
            # filter is active, the status bar can still name it.
            self._project_filter = ids[idx]
            self._project_filter_name = projects[idx].name
        else:
            self._project_filter = None
            self._project_filter_name = None
        self._refresh_list()

    def action_filter_priority(self, value: str) -> None:
        """Set the priority filter; pressing the same key again clears it."""
        priority = Priority.from_string(value)
        self._priority_filter = None if self._priority_filter == priority else priority
        self._refresh_list()

    def action_toggle_cursor_mode(self) -> None:
        """Toggle whether the cursor follows a moved item or stays put.

        'Stay' keeps the cursor on the same visual row after status moves,
        so repeatedly pressing 'd' cleans a list top-down.
        """
        self._cursor_follows_item = not self._cursor_follows_item
        mode = "follow item" if self._cursor_follows_item else "stay on row"
        self.notify(f"Cursor mode: {mode}")
        self._refresh_list()

    def action_clear_filters(self) -> None:
        if (
            self._search_query
            or self._tag_filter
            or self._project_filter
            or self._priority_filter
        ):
            self._search_query = ""
            self._tag_filter = None
            self._project_filter = None
            self._project_filter_name = None
            self._priority_filter = None
            self._refresh_list()

    def action_status_next(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        try:
            item = show_todo(self._storage, item_id)
        except NotFoundError:
            return
        except TodoError as exc:
            self.notify(escape_markup(str(exc)), severity="error")
            return
        next_status = item.status.next()
        if next_status is not None:
            try:
                result = move_todo(self._storage, item_id, next_status)
            except TodoError as exc:
                self.notify(escape_markup(str(exc)), severity="error")
                self._refresh_list()
                return
            self._notify_unblocked(result)
            self._refresh_list()

    def action_status_prev(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        try:
            item = show_todo(self._storage, item_id)
        except NotFoundError:
            return
        except TodoError as exc:
            self.notify(escape_markup(str(exc)), severity="error")
            return
        prev_status = item.status.prev()
        if prev_status is not None:
            try:
                move_todo(self._storage, item_id, prev_status)
            except TodoError as exc:
                self.notify(escape_markup(str(exc)), severity="error")
            self._refresh_list()
