"""One item."""

from __future__ import annotations

from todo.application.contracts.item_store import ItemStore
from todo.domain.item_id import ItemId
from todo.domain.todo_item import TodoItem


class ShowTodo:
    def __init__(self, items: ItemStore) -> None:
        self._items = items

    def execute(self, item_id: ItemId) -> TodoItem:
        return self._items.get(item_id)
