"""Change an item's status."""

from __future__ import annotations

from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemStore
from todo.application.toast import Toast, Unblocked
from todo.domain.item_id import ItemId
from todo.domain.status import Status


class SetStatus:
    """Finishing an item can leave the items it blocked with nothing left
    to wait for, and that is worth saying — so the graph is here too."""

    def __init__(self, items: ItemStore, dependencies: DependencyStore) -> None:
        self._items = items
        self._dependencies = dependencies

    def execute(self, item_id: ItemId, status: Status) -> list[Toast]:
        item = self._items.get(item_id)
        # Only a completion can leave anything with nothing left to wait
        # for, so nothing else pays for reading the graph.
        completing = status.done and not item.is_done
        graph = self._dependencies.load() if completing else None
        blocked_before: set[ItemId] = set()
        if graph is not None:
            done = self._items.done_ids()
            blocked_before = {
                dependent
                for dependent in graph.dependents_of(item_id)
                if graph.is_blocked(dependent, done)
            }
        item.set_status(status)
        self._items.save(item)
        if graph is None or not blocked_before:
            return []
        done = self._items.done_ids()
        unblocked = sorted(
            dependent
            for dependent in blocked_before
            if not graph.is_blocked(dependent, done)
        )
        return [Unblocked(items=unblocked)] if unblocked else []
