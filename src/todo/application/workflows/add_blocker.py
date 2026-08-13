"""Add the relation that makes one item blocked by others.

Added, not created: the items already exist, and what goes in is the
relation between them.
"""

from __future__ import annotations

from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemStore
from todo.domain.item_id import ItemId
from todo.exceptions import NotFoundError


class AddBlocker:
    def __init__(self, items: ItemStore, dependencies: DependencyStore) -> None:
        self._items = items
        self._dependencies = dependencies

    def execute(self, blocked_id: ItemId, blocker_ids: list[ItemId]) -> None:
        """All of them or none of them.

        What may be added is the graph's rule, not this workflow's: the
        graph is loaded once and every addition goes through it, so an
        edge that only closes a loop together with an earlier one in the
        same batch is refused by the same code as any other. Nothing is
        written until every addition has been allowed.
        """
        if not self._items.exists(blocked_id):
            raise NotFoundError(blocked_id)
        graph = self._dependencies.load()
        for blocker_id in blocker_ids:
            graph = graph.with_edge(blocker_id, blocked_id)
        for blocker_id in blocker_ids:
            if not self._items.exists(blocker_id):
                raise NotFoundError(blocker_id)
        self._dependencies.save(graph)
