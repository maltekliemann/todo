"""The read side of the dependency graph.

A dependency is not a property of either item it joins, so an item cannot
carry one. What a view needs — what this waits on, what waits on it,
whether it is still held up — is answered here, from the graph and the
set of finished items, and handed to the presenters alongside the items.
"""

from __future__ import annotations

from dataclasses import dataclass

from todo.application.contracts.storage import StorageProtocol
from todo.domain.dependency_graph import DependencyGraph


@dataclass(frozen=True)
class Dependencies:
    graph: DependencyGraph
    done_ids: frozenset[int]

    @classmethod
    def load(cls, storage: StorageProtocol) -> Dependencies:
        return cls(
            graph=DependencyGraph(frozenset(storage.dependency_edges())),
            done_ids=frozenset(storage.done_ids()),
        )

    def blockers_of(self, item_id: int) -> list[int]:
        return self.graph.blockers_of(item_id)

    def dependents_of(self, item_id: int) -> list[int]:
        return self.graph.dependents_of(item_id)

    def is_blocked(self, item_id: int) -> bool:
        return self.graph.is_blocked(item_id, self.done_ids)

    def blocked_ids(self) -> set[int]:
        """Every item still waiting on something."""
        return {blocked for _, blocked in self.graph.edges if self.is_blocked(blocked)}
