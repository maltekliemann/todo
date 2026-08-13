"""Delete the relation that makes one item blocked by another.

Not "unblock": removing one blocker does not unblock the item — it may
have others. Unblocked is what an item becomes when every one of its
blockers is done, and nobody performs that.
"""

from __future__ import annotations

from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemStore
from todo.application.toast import Toast, Unblocked
from todo.domain.item_id import ItemId
from todo.exceptions import DependencyError, NotFoundError


class RemoveBlocker:
    def __init__(self, items: ItemStore, dependencies: DependencyStore) -> None:
        self._items = items
        self._dependencies = dependencies

    def execute(self, blocked_id: ItemId, blocker_ids: list[ItemId]) -> list[Toast]:
        """All of them or none of them.

        Every id is checked against the item's current blockers before
        anything is removed, so a typo is refused rather than quietly
        doing nothing while the real blocker stays where it was.
        """
        if not self._items.exists(blocked_id):
            raise NotFoundError(blocked_id)
        graph = self._dependencies.load()
        blockers = graph.blockers_of(blocked_id)
        for blocker_id in blocker_ids:
            if blocker_id not in blockers:
                raise DependencyError(
                    f"Item {blocked_id.label} is not blocked by {blocker_id.label}."
                )
        done = self._items.done_ids()
        was_blocked = graph.is_blocked(blocked_id, done)
        pruned = graph.without_edges(
            (blocker_id, blocked_id) for blocker_id in blocker_ids
        )
        self._dependencies.save(pruned)
        if was_blocked and not pruned.is_blocked(blocked_id, done):
            return [Unblocked(items=[blocked_id])]
        return []
