"""The item table: separator-aware navigation and the PRD's key bindings."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable

from todo.adapters.output import (
    _deadline_str,
    _deadline_style,
    _pri_style,
    _priority_label,
    _relative_age,
    _status_icon,
)
from todo.domain.enums import Status
from todo.domain.models import TodoItem
from todo.tui.render import join_styles

SEPARATOR_PREFIX = "__sep_"

COLUMNS = ("#", "Pri", "Status", "Title", "Deadline", "Age")

# Groups in reading order: what you are doing, then what is next, then
# what is parked, then what is finished.
_STATUS_ORDER = (Status.IN_PROGRESS, Status.TODO, Status.BACKLOG, Status.DONE)


def is_separator(value: object) -> bool:
    return isinstance(value, str) and value.startswith(SEPARATOR_PREFIX)


class TodoTable(DataTable["str | Text"]):
    """DataTable that skips over separator rows when navigating with up/down.

    Also carries the PRD's navigation keys: j/k alongside the arrows, and
    the horizontal keys repurposed from column movement (meaningless under
    a row cursor) to stepping the selected item's status.
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("l", "cursor_right", "Status >", show=False),
        Binding("h", "cursor_left", "Status <", show=False),
        # Under a row cursor DataTable's horizontal keys scroll the table,
        # and taking them for the status step would otherwise leave a title
        # wider than the terminal unreachable (home/end jump to the
        # extremes; nothing else scrolls by a column).
        Binding("shift+right", "scroll_right", "Scroll right", show=False),
        Binding("shift+left", "scroll_left", "Scroll left", show=False),
    ]

    class StatusStep(Message):
        """Request from the table to move the selected item's status."""

        def __init__(self, table: TodoTable, delta: int) -> None:
            super().__init__()
            self.table = table
            self.delta = delta

        @property
        def control(self) -> TodoTable:
            return self.table

    def _current_row_key(self) -> object:
        if self.row_count == 0:
            return None
        try:
            return self.coordinate_to_cell_key(
                Coordinate(self.cursor_row, 0)
            ).row_key.value
        except Exception:
            return None

    def _row_key_at(self, row: int) -> object:
        try:
            return self.coordinate_to_cell_key(Coordinate(row, 0)).row_key.value
        except Exception:
            return None

    def _first_non_separator(self, start: int, direction: int) -> int | None:
        row = start
        while 0 <= row < self.row_count:
            if not is_separator(self._row_key_at(row)):
                return row
            row += direction
        return None

    def _skip_separators(self, direction: int) -> None:
        # direction: +1 = down, -1 = up. Scan that way for the first item
        # row; at a boundary scan the other way, so the cursor never rests
        # on a separator.
        if not is_separator(self._current_row_key()):
            return
        target = self._first_non_separator(self.cursor_row, direction)
        if target is None:
            target = self._first_non_separator(self.cursor_row, -direction)
        if target is not None:
            self.move_cursor(row=target)

    def action_cursor_down(self) -> None:
        super().action_cursor_down()
        self._skip_separators(1)

    def action_cursor_up(self) -> None:
        super().action_cursor_up()
        self._skip_separators(-1)

    def action_cursor_right(self) -> None:
        self.post_message(self.StatusStep(self, 1))

    def action_cursor_left(self) -> None:
        self.post_message(self.StatusStep(self, -1))

    def populate(self, items: list[TodoItem]) -> dict[int, int]:
        """Rebuild every row, grouped by status under a separator.

        Returns item id -> row index, which is what the caller needs to put
        the cursor back where it was. Ordering inside a group is the
        storage layer's (priority, then created_at) and is preserved.
        """
        self.clear()
        groups: dict[Status, list[TodoItem]] = {s: [] for s in _STATUS_ORDER}
        for item in items:
            groups[item.status].append(item)

        row_index_of: dict[int, int] = {}
        index = 0
        for status in _STATUS_ORDER:
            group = groups[status]
            if not group:
                continue
            self.add_row(
                "",
                "",
                f"── {status.value} ({len(group)}) ──",
                "",
                "",
                "",
                key=f"{SEPARATOR_PREFIX}{status.value}",
            )
            index += 1
            for item in group:
                self.add_row(*_cells(item), key=str(item.id))
                row_index_of[item.id] = index
                index += 1
        return row_index_of


def _cells(item: TodoItem) -> list[Text]:
    """One row's cells, styled.

    Always Text, never str: DataTable parses plain strings as markup and
    titles are user-controlled. Priority and deadline proximity carry their
    own colour; everything else inherits the row's.
    """
    deadline_text = _deadline_str(item) if item.status != Status.DONE else ""
    values = [
        str(item.id),
        _priority_label(item.priority),
        f"{_status_icon(item.status)} {item.status.value}",
        f"\U0001f6a7 {item.title}" if item.is_blocked else item.title,
        deadline_text,
        _relative_age(item.created_at),
    ]
    row_style = "dim" if item.is_blocked else ""
    styles = [row_style] * len(values)
    styles[1] = join_styles(row_style, _pri_style(item.priority))
    if deadline_text:
        styles[4] = join_styles(row_style, _deadline_style(item))
    return [Text(v, style=s) for v, s in zip(values, styles)]
