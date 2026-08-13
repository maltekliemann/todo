"""Items, narrowed by a filter."""

from __future__ import annotations

from todo.application.contracts.item_store import ItemStore
from todo.domain.item_filter import ItemFilter
from todo.domain.todo_item import TodoItem


class ListTodos:
    def __init__(self, items: ItemStore) -> None:
        self._items = items

    def execute(self, item_filter: ItemFilter) -> list[TodoItem]:
        return self._items.find(item_filter)
