"""Items finished since a point in time."""

from __future__ import annotations

from todo.application.contracts.item_store import ItemStore
from todo.domain.moment import Moment
from todo.domain.todo_item import TodoItem


class Summarize:
    def __init__(self, items: ItemStore) -> None:
        self._items = items

    def execute(self, since: Moment) -> list[TodoItem]:
        return self._items.done_since(since)
