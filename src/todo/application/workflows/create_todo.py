"""Create an item."""

from __future__ import annotations

from todo.application.contracts.item_store import ItemStore
from todo.domain.todo_item import TodoItem


class CreateTodo:
    def __init__(self, items: ItemStore) -> None:
        self._items = items

    def execute(self, item: TodoItem) -> None:
        """Nothing comes back: the caller took the identity and built the
        item, so it already holds everything this could hand it."""
        self._items.create(item)
