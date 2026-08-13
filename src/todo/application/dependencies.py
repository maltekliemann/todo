"""The read side of the dependency graph.

A dependency is not a property of either item it joins, so an item cannot
carry one. What a view needs — what this waits on, what waits on it,
whether it is still held up — is answered here, from the graph and the
set of finished items, and handed to the presenters alongside the items.
"""

from __future__ import annotations

from dataclasses import dataclass

from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemStore
from todo.domain.dependency_graph import DependencyGraph
from todo.domain.item_id import ItemId


@dataclass(frozen=True)
class Dependencies:
    graph: DependencyGraph
    done_ids: frozenset[ItemId]

    @classmethod
    def load(cls, items: ItemStore, dependencies: DependencyStore) -> Dependencies:
        """Every half at once: whether an item is held up is a question
        about the edges, about which items still exist, and about what is
        finished — and no one store can answer it alone.

        The graph is read as it stands for the items that are there. An
        item and the edges that named it are deleted by two separate
        writes, so the stored edges can outlive the item; read this way
        they mean nothing, which is exactly right.
        """
        return cls(
            graph=dependencies.load().restricted_to(items.all_ids()),
            done_ids=items.done_ids(),
        )

    def blockers_of(self, item_id: ItemId) -> list[ItemId]:
        return self.graph.blockers_of(item_id)

    def dependents_of(self, item_id: ItemId) -> list[ItemId]:
        return self.graph.dependents_of(item_id)

    def is_blocked(self, item_id: ItemId) -> bool:
        return self.graph.is_blocked(item_id, self.done_ids)

    def blocked_ids(self) -> set[ItemId]:
        """Every item still waiting on something."""
        return {blocked for _, blocked in self.graph.edges if self.is_blocked(blocked)}
