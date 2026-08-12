"""The item table: separator-aware navigation and the PRD's key bindings."""

from __future__ import annotations

from rich.text import Text  # noqa: F401  (used in the DataTable type parameter)
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable

SEPARATOR_PREFIX = "__sep_"


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
