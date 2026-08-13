"""Keep an item as it now stands.

The caller changes the item through its own methods and hands it over;
there is nothing here to tell "leave this alone" from "empty this",
because nothing is described in parts.
"""

from __future__ import annotations

from todo.application.contracts.item_store import ItemStore
from todo.domain.todo_item import TodoItem


class EditTodo:
    def __init__(self, items: ItemStore) -> None:
        self._items = items

    def execute(self, item: TodoItem) -> None:
        self._items.save(item)
