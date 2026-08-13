"""The blocking relations, and which items are finished.

The graph is handed over as itself: what blocks an item, what it blocks
and whether it is blocked are already methods on it. Read once per page,
asked per row. The finished set is the other half of that last question.
"""

from __future__ import annotations

from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemStore
from todo.domain.dependency_graph import DependencyGraph
from todo.domain.item_id import ItemId


class LoadDependencies:
    def __init__(self, dependencies: DependencyStore) -> None:
        self._dependencies = dependencies

    def execute(self) -> DependencyGraph:
        return self._dependencies.load()


class DoneIds:
    def __init__(self, items: ItemStore) -> None:
        self._items = items

    def execute(self) -> frozenset[ItemId]:
        return self._items.done_ids()
