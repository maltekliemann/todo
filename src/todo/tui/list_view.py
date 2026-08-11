from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import date, datetime

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.coordinate import Coordinate
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import DataTable, Footer, Input, Label, Select, Static

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import (
    add_todo,
    block_todo,
    complete_todo,
    delete_todo,
    edit_todo,
    move_todo,
)
from todo.application.contracts.storage import UNSET, Unset
from todo.application.queries import list_todos, show_todo
from todo.domain.enums import Priority, Status
from todo.domain.models import TodoItem
from todo.exceptions import DependencyError, NotFoundError

_SEPARATOR_PREFIX = "__sep_"


def _is_separator(value: object) -> bool:
    return isinstance(value, str) and value.startswith(_SEPARATOR_PREFIX)


class TodoTable(DataTable[str]):
    """DataTable that skips over separator rows when navigating with up/down."""

    def _current_row_key(self) -> object:
        if self.row_count == 0:
            return None
        try:
            return self.coordinate_to_cell_key(
                Coordinate(self.cursor_row, 0)
            ).row_key.value
        except Exception:
            return None

    def _skip_separators(self, direction: int) -> None:
        # direction: +1 = down, -1 = up
        while _is_separator(self._current_row_key()):
            new_row = self.cursor_row + direction
            if new_row < 0 or new_row >= self.row_count:
                # Hit a boundary — try the opposite direction so the cursor
                # never rests on a separator.
                opposite = -direction
                while _is_separator(self._current_row_key()):
                    other_row = self.cursor_row + opposite
                    if other_row < 0 or other_row >= self.row_count:
                        return
                    self.move_cursor(row=other_row)
                return
            self.move_cursor(row=new_row)

    def action_cursor_down(self) -> None:
        super().action_cursor_down()
        self._skip_separators(1)

    def action_cursor_up(self) -> None:
        super().action_cursor_up()
        self._skip_separators(-1)


def _priority_label(p: Priority) -> str:
    if p == Priority.URGENT:
        return "!! URG"
    if p == Priority.HIGH:
        return "!  HIGH"
    if p == Priority.MEDIUM:
        return "   MED"
    return "   LOW"


def _status_icon(s: Status) -> str:
    if s == Status.DONE:
        return "✓"
    if s == Status.IN_PROGRESS:
        return "●"
    return "○"


def _relative_age(dt: datetime) -> str:
    now = datetime.now(tz=dt.tzinfo)
    delta = now - dt
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
    weeks = days // 7
    if weeks < 4:
        return f"{weeks}w"
    return f"{days // 30}mo"


def _deadline_str(item: TodoItem) -> str:
    if item.deadline is None:
        return ""
    days = item.days_until_deadline
    assert days is not None
    if item.is_overdue:
        return f"\U0001f534 {item.deadline.strftime('%b %d')} ({abs(days)}d late)"
    if item.deadline_urgent:
        return f"⚠ {item.deadline.strftime('%b %d')} ({days}d)"
    return item.deadline.strftime("%b %d")


def _item_to_editor_text(item: TodoItem) -> str:
    return (
        f"title: {item.title}\n"
        f"priority: {item.priority.value}\n"
        f"status: {item.status.value}\n"
        f"deadline: {item.deadline.isoformat() if item.deadline else ''}\n"
        f"tags: {', '.join(item.tags)}\n"
        f"\n"
        f"# Body (everything below this line is the body):\n"
        f"{item.body}"
    )


def _parse_editor_text(text: str) -> dict[str, str]:
    lines = text.split("\n")
    fields: dict[str, str] = {}
    body_lines: list[str] = []
    in_body = False
    for line in lines:
        if in_body:
            body_lines.append(line)
            continue
        if line.startswith("# Body"):
            in_body = True
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower()
            if key in ("title", "priority", "status", "deadline", "tags"):
                fields[key] = value.strip()
    fields["body"] = "\n".join(body_lines).strip()
    return fields


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
            yield Label("[y] Yes   [n] No", id="confirm-hint")

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

    def __init__(self, storage: SqliteStorage) -> None:
        super().__init__()
        self._storage = storage

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
        tags = (
            [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else None
        )

        item = add_todo(
            self._storage,
            title,
            priority=priority,
            deadline=deadline,
            tags=tags,
        )
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


class BlockDialog(ModalScreen[str | None]):
    """Prompt for a blocker id and add the blocking relation.

    The command call happens here so validation/dependency errors can be
    shown inline while keeping the dialog open. Dismisses with the entered
    string on success, or ``None`` on cancel.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, storage: SqliteStorage, blocked_id: int) -> None:
        super().__init__()
        self._storage = storage
        self._blocked_id = blocked_id

    def compose(self) -> ComposeResult:
        with Vertical(id="block-container"):
            yield Label(f"Block #{self._blocked_id} by (item id):")
            yield Input(id="block-input", placeholder="Blocker item id...")
            yield Label("", id="block-error")

    def on_mount(self) -> None:
        self.query_one("#block-input", Input).focus()

    @on(Input.Submitted, "#block-input")
    def on_submit(self) -> None:
        value = self.query_one("#block-input", Input).value.strip()
        error_w = self.query_one("#block-error", Label)
        try:
            blocker_id = int(value)
            block_todo(self._storage, self._blocked_id, blocker_id)
        except (NotFoundError, DependencyError, ValueError) as exc:
            message = str(exc) if str(exc) else "Invalid blocker id"
            error_w.update(message)
            return
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)


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
            yield Static(f"[b]#{item.id}  {item.title}[/b]", id="inspect-title")
            meta_lines = [
                f"Priority: {item.priority.value}    Status: {item.status.value}",
            ]
            if item.deadline:
                meta_lines.append(f"Deadline: {_deadline_str(item)}")
            meta_lines.append(
                f"Created: {item.created_at.strftime('%b %d, %Y %H:%M')}    "
                f"Updated: {item.updated_at.strftime('%b %d, %Y %H:%M')}"
            )
            if item.done_at:
                meta_lines.append(f"Done: {item.done_at.strftime('%b %d, %Y %H:%M')}")
            if item.tags:
                meta_lines.append(f"Tags: {', '.join(item.tags)}")
            if item.blocked_by:
                meta_lines.append(
                    f"Blocked by: {', '.join(f'#{i}' for i in item.blocked_by)}"
                )
            if item.blocking:
                meta_lines.append(
                    f"Blocking: {', '.join(f'#{i}' for i in item.blocking)}"
                )
            yield Static("\n".join(meta_lines), id="inspect-meta")
            with VerticalScroll(id="inspect-body-scroll"):
                yield Static(
                    item.body if item.body else "[dim](no description)[/dim]",
                    id="inspect-body",
                )
            yield Label("Esc / q / i to close", id="inspect-hint")

    def action_close(self) -> None:
        self.dismiss()


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
        Binding("escape", "clear_search", "Clear filter", show=True),
    ]

    POLL_INTERVAL_SECONDS = 2.0

    def __init__(self, storage: SqliteStorage) -> None:
        super().__init__()
        self._storage = storage
        self._items: list[TodoItem] = []
        self._search_query: str = ""
        self._last_data_version: int = 0

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
        table.add_columns("#", "Pri", "Status", "Title", "Deadline", "Age")
        table.focus()
        self._refresh_list()
        self._last_data_version = self._storage.data_version()
        self.set_interval(self.POLL_INTERVAL_SECONDS, self._poll_for_external_changes)

    def _poll_for_external_changes(self) -> None:
        version = self._storage.data_version()
        if version != self._last_data_version:
            self._last_data_version = version
            self._refresh_list()

    @on(DataTable.RowHighlighted, "#item-list")
    def on_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:
            self._update_detail(event.row_key.value)

    @on(DataTable.RowSelected, "#item-list")
    def on_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key is None or _is_separator(event.row_key.value):
            return
        self.action_inspect()

    def _refresh_list(self) -> None:
        table = self.query_one("#item-list", TodoTable)
        previous_id = self._selected_item_id()
        previous_cursor = table.cursor_row
        table.clear()

        self._items = list_todos(self._storage, include_done=True)

        if self._search_query:
            q = self._search_query.lower()
            self._items = [
                i
                for i in self._items
                if q in i.title.lower()
                or q in i.body.lower()
                or any(q in t.lower() for t in i.tags)
            ]

        # Group items by status, preserving the per-group ordering from the
        # storage layer (priority, then created_at).
        status_order = [
            Status.IN_PROGRESS,
            Status.TODO,
            Status.BACKLOG,
            Status.DONE,
        ]
        groups: dict[Status, list[TodoItem]] = {s: [] for s in status_order}
        for item in self._items:
            groups[item.status].append(item)

        row_index_of: dict[int, int] = {}
        index = 0
        for status in status_order:
            items = groups[status]
            if not items:
                continue
            table.add_row(
                "",
                "",
                f"── {status.value} ({len(items)}) ──",
                "",
                "",
                "",
                key=f"{_SEPARATOR_PREFIX}{status.value}",
            )
            index += 1
            for item in items:
                deadline_text = _deadline_str(item) if status != Status.DONE else ""
                title_text = (
                    f"\U0001f6a7 {item.title}" if item.is_blocked else item.title
                )
                table.add_row(
                    str(item.id),
                    _priority_label(item.priority),
                    f"{_status_icon(item.status)} {item.status.value}",
                    title_text,
                    deadline_text,
                    _relative_age(item.created_at),
                    key=str(item.id),
                )
                row_index_of[item.id] = index
                index += 1

        if table.row_count > 0:
            if previous_id is not None and previous_id in row_index_of:
                table.move_cursor(row=row_index_of[previous_id])
            elif row_index_of:
                # Land on the first item row, not the leading separator.
                first_item_row = min(row_index_of.values())
                clamped = min(previous_cursor, table.row_count - 1)
                target = clamped if clamped >= first_item_row else first_item_row
                table.move_cursor(row=target)
                table._skip_separators(1)
            else:
                table.move_cursor(row=0)

        self._last_data_version = self._storage.data_version()

        search_status = self.query_one("#search-status", Static)
        if self._search_query:
            search_status.update(
                f"[dim]Search: [/dim][b]{self._search_query}[/b]  "
                f"[dim]([Esc] to clear)[/dim]"
            )
        else:
            search_status.update("")

    def _update_detail(self, item_id: object) -> None:
        if item_id is None or _is_separator(item_id):
            self.query_one("#detail-title", Static).update("")
            self.query_one("#detail-meta", Static).update("")
            self.query_one("#detail-body", Static).update("")
            return

        try:
            item = show_todo(self._storage, int(str(item_id)))
        except (NotFoundError, ValueError):
            return

        title_w = self.query_one("#detail-title", Static)
        meta_w = self.query_one("#detail-meta", Static)
        body_w = self.query_one("#detail-body", Static)

        dl_str = f"  Deadline: {_deadline_str(item)}" if item.deadline else ""
        done_str = (
            f"   Done: {item.done_at.strftime('%b %d, %Y %H:%M')}"
            if item.done_at
            else ""
        )
        tags_str = f"\nTags: {', '.join(item.tags)}" if item.tags else ""
        blocked_by_str = (
            f"\nBlocked by: {', '.join(f'#{i}' for i in item.blocked_by)}"
            if item.blocked_by
            else ""
        )
        blocking_str = (
            f"\nBlocking: {', '.join(f'#{i}' for i in item.blocking)}"
            if item.blocking
            else ""
        )

        title_w.update(f"[b]#{item.id}  {item.title}[/b]")
        meta_w.update(
            f"Priority: {item.priority.value}  Status: {item.status.value}"
            f"{dl_str}\n"
            f"Created: {item.created_at.strftime('%b %d, %Y %H:%M')}   "
            f"Updated: {item.updated_at.strftime('%b %d, %Y %H:%M')}"
            f"{done_str}"
            f"{tags_str}"
            f"{blocked_by_str}"
            f"{blocking_str}"
        )
        body_w.update(item.body if item.body else "")

    def _selected_item_id(self) -> int | None:
        table = self.query_one("#item-list", DataTable)
        if table.row_count == 0:
            return None
        try:
            row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        except Exception:
            return None
        if row_key.value is None or _is_separator(row_key.value):
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

        self.app.push_screen(NewItemDialog(self._storage), after)

    def action_done(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        complete_todo(self._storage, item_id)
        self._refresh_list()

    def action_inspect(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        try:
            item = show_todo(self._storage, item_id)
        except NotFoundError:
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

        editor = os.environ.get("EDITOR", "vi")
        text = _item_to_editor_text(item)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".todo.txt", delete=False
        ) as f:
            f.write(text)
            tmp_path = f.name

        try:
            with self.app.suspend():
                subprocess.run([editor, tmp_path], check=True)

            with open(tmp_path) as f:
                edited = f.read()

            if edited.strip() == text.strip():
                return

            fields = _parse_editor_text(edited)

            deadline_val: date | None | Unset = UNSET
            dl_str = fields.get("deadline", "")
            if dl_str == "":
                deadline_val = None
            else:
                try:
                    deadline_val = date.fromisoformat(dl_str)
                except ValueError:
                    deadline_val = UNSET

            tags = None
            if fields.get("tags"):
                tags = [t.strip() for t in fields["tags"].split(",") if t.strip()]

            edit_todo(
                self._storage,
                item_id,
                title=fields.get("title") or None,
                body=fields.get("body") or "",
                priority=(
                    Priority.from_string(fields["priority"])
                    if fields.get("priority")
                    else None
                ),
                status=(
                    Status.from_string(fields["status"])
                    if fields.get("status")
                    else None
                ),
                deadline=deadline_val,
                tags=tags,
            )
            self._refresh_list()
        finally:
            os.unlink(tmp_path)

    def action_delete(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return

        def after(confirmed: bool | None) -> None:
            if confirmed:
                delete_todo(self._storage, item_id)
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

    def action_status_next(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        try:
            item = show_todo(self._storage, item_id)
        except NotFoundError:
            return
        next_status = item.status.next()
        if next_status is not None:
            if next_status == Status.DONE:
                complete_todo(self._storage, item_id)
            else:
                move_todo(self._storage, item_id, next_status)
            self._refresh_list()

    def action_status_prev(self) -> None:
        item_id = self._selected_item_id()
        if item_id is None:
            return
        try:
            item = show_todo(self._storage, item_id)
        except NotFoundError:
            return
        prev_status = item.status.prev()
        if prev_status is not None:
            move_todo(self._storage, item_id, prev_status)
            self._refresh_list()
