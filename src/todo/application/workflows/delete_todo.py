"""Delete an item."""

from __future__ import annotations

from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemStore
from todo.application.toast import Toast, Unblocked
from todo.domain.item_id import ItemId
from todo.exceptions import NotFoundError


class DeleteTodo:
    """An item and the edges that named it are two aggregates, so this is
    two writes. The edges go first: an edge naming an item that is not
    there is a blocker nobody can ever finish, and that is the state a
    reader must never see."""

    def __init__(self, items: ItemStore, dependencies: DependencyStore) -> None:
        self._items = items
        self._dependencies = dependencies

    def execute(self, item_id: ItemId) -> list[Toast]:
        if not self._items.exists(item_id):
            raise NotFoundError(item_id)
        graph = self._dependencies.load()
        done = self._items.done_ids()
        blocked_before = {
            dependent
            for dependent in graph.dependents_of(item_id)
            if graph.is_blocked(dependent, done)
        }
        pruned = graph.without_edges(edge for edge in graph.edges if item_id in edge)
        self._dependencies.save(pruned)
        self._items.delete(item_id)
        done = self._items.done_ids()
        # Losing a blocker to a deletion unblocks exactly as finishing it
        # would, so it is said the same way.
        unblocked = sorted(
            dependent
            for dependent in blocked_before
            if not pruned.is_blocked(dependent, done)
        )
        return [Unblocked(items=unblocked)] if unblocked else []
