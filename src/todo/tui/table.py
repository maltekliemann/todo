"""The item table: separator-aware navigation and the PRD's key bindings."""

from __future__ import annotations

from rich.text import Text
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable

from todo.domain.dependency_graph import DependencyGraph
from todo.domain.item_id import ItemId
from todo.domain.status import Status
from todo.domain.todo_item import TodoItem
from todo.tui.render import (
    deadline_str,
    deadline_style,
    join_styles,
    priority_label,
    priority_style,
    relative_age,
    status_icon,
)

SEPARATOR_PREFIX = "__sep_"

COLUMNS = ("#", "Pri", "Status", "Title", "Tags", "Deps", "Deadline", "Age")

# Blocker ids past this many collapse into a "+n" tail: the column has to
# stay narrow enough to leave the title room.
_MAX_BLOCKER_IDS = 2

# Same deal for tags, but measured in columns rather than tags: what
# squeezes the title is width, and three long tags take more of it than
# five short ones. The full list stays in the detail pane.
_TAG_BUDGET = 24

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

    def populate(
        self, items: list[TodoItem], graph: DependencyGraph, done: frozenset[ItemId]
    ) -> dict[int, int]:
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
            label = f"── {status.value} ({len(group)}) ──"
            cells = ["" for _ in COLUMNS]
            cells[COLUMNS.index("Title")] = label
            self.add_row(*cells, key=f"{SEPARATOR_PREFIX}{status.value}")
            index += 1
            for item in group:
                self.add_row(*_cells(item, graph, done), key=str(item.id))
                row_index_of[item.id] = index
                index += 1
        return row_index_of


def deps_cell(item: TodoItem, graph: DependencyGraph, done: frozenset[ItemId]) -> str:
    """What this item waits on, and how many wait on it.

    '←#2,#3' are the blockers by id — you need the id to act on them —
    while '→3' is only a count, because the ids of dependents are not
    something you act on from this row.

    The '←' half is gated on is_blocked, the same flag that decides the 🚧
    marker: once every blocker is done the item waits on nothing, and a
    cell still naming them would contradict the marker beside it. The full
    history stays in the detail pane.
    """
    parts = []
    blockers = graph.blockers_of(item.id)
    if blockers and graph.is_blocked(item.id, done):
        shown = blockers[:_MAX_BLOCKER_IDS]
        ids = ",".join(i.label for i in shown)
        hidden = len(blockers) - len(shown)
        parts.append(f"←{ids}+{hidden}" if hidden else f"←{ids}")
    dependents = graph.dependents_of(item.id)
    if dependents:
        parts.append(f"→{len(dependents)}")
    return " ".join(parts)


def tags_cell(item: TodoItem) -> str:
    """Whole tags by name up to the width budget, '+n' tail for the rest.

    Never cut mid-tag: a cut tag cannot be read back, and two different
    tags could truncate to the same text. The one exception is a single
    tag wider than the whole budget — it is cut with a visible ellipsis,
    because a bare '+n' would name no tag at all.
    """
    tags = sorted(item.tags)
    shown: list[str] = []
    for tag in tags:
        if shown and len(", ".join([*shown, tag])) > _TAG_BUDGET:
            break
        shown.append(tag)
    hidden = len(tags) - len(shown)
    text = ", ".join(shown)
    if len(text) > _TAG_BUDGET:
        text = text[: _TAG_BUDGET - 1] + "…"
    return f"{text} +{hidden}" if hidden else text


def _cells(
    item: TodoItem, graph: DependencyGraph, done: frozenset[ItemId]
) -> list[Text]:
    """One row's cells, styled.

    Always Text, never str: DataTable parses plain strings as markup and
    titles are user-controlled. Priority and deadline proximity carry their
    own colour; everything else inherits the row's.
    """
    deadline_text = deadline_str(item) if item.status.active else ""
    values = [
        str(item.id),
        priority_label(item.priority),
        f"{status_icon(item.status)} {item.status.value}",
        f"\U0001f6a7 {item.title}" if graph.is_blocked(item.id, done) else item.title,
        tags_cell(item),
        deps_cell(item, graph, done),
        deadline_text,
        relative_age(item.created_at),
    ]
    row_style = "dim" if graph.is_blocked(item.id, done) else ""
    styles = [row_style] * len(values)
    styles[COLUMNS.index("Pri")] = join_styles(row_style, priority_style(item.priority))
    # Dim always: tags are for finding the row, the title is for reading it.
    styles[COLUMNS.index("Tags")] = join_styles(row_style, "dim")
    if deadline_text:
        styles[COLUMNS.index("Deadline")] = join_styles(row_style, deadline_style(item))
    return [Text(v, style=s) for v, s in zip(values, styles)]
