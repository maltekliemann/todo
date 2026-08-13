"""Which items block which, and the rule that spans all of them."""

from __future__ import annotations

from collections.abc import Container, Iterable
from dataclasses import dataclass

from todo.domain.item_id import ItemId
from todo.exceptions import DependencyError

# (blocker, blocked): the blocker must be done before the blocked item.
Edge = tuple[ItemId, ItemId]


@dataclass(frozen=True)
class DependencyGraph:
    """Every dependency, as one value that is valid or does not exist.

    An edge belongs to neither of the items it joins — "#3 blocks #1" and
    "#1 waits on #3" are one fact, not two — and the rule that makes it
    admissible ranges over the whole set: you cannot tell whether an edge
    closes a loop by looking at its two ends. So the consistency boundary
    is the graph, not the item, and the way in is construction:

        graph = DependencyGraph(edges).with_edge(blocker, blocked)

    which returns a valid graph or raises. There is no DependencyGraph
    with a cycle in it, so there is none to persist.

    Loading validates too, not only adding. That is the redundant-looking
    half, and it is the half that catches a graph written by something
    that went around this type.
    """

    edges: frozenset[Edge]

    def __post_init__(self) -> None:
        for blocker, blocked in self.edges:
            if blocker == blocked:
                raise DependencyError(f"Item {blocker.label} blocks itself.")
        for blocker, blocked in self.edges:
            # Reachable backwards, with this edge itself left out of the
            # walk: that is what "this edge closes a loop" means.
            if self._reaches(blocked, blocker, ignoring=(blocker, blocked)):
                raise DependencyError("The dependencies contain a cycle.")

    def with_edge(self, blocker: ItemId, blocked: ItemId) -> DependencyGraph:
        """This graph plus one edge, or DependencyError if it cannot hold.

        Both messages are raised here rather than left to __post_init__
        because this is the call a person made: it can name the addition
        that was refused, while loading can only say the set is bad.
        """
        if blocker == blocked:
            raise DependencyError("An item cannot block itself.")
        if self._reaches(blocked, blocker):
            raise DependencyError("Adding this blocker would create a cycle.")
        return DependencyGraph(self.edges | {(blocker, blocked)})

    def restricted_to(self, item_ids: Container[ItemId]) -> DependencyGraph:
        """This graph as it stands for those items.

        A dependency between items where one of them does not exist is
        not a dependency — there is nothing left to wait for. It cannot
        be otherwise: an edge names two items and the graph cannot write
        them, so an item can always vanish out from under an edge, and a
        graph that took such an edge at face value would report a blocker
        nobody can ever finish.

        This is what makes the gap legal. Deleting an item and pruning
        the edges that named it are two writes, so between them the
        stored edges say something that is no longer true. Read through
        here, that state means what it should, and the pruning is
        housekeeping rather than the thing correctness rests on.
        """
        return DependencyGraph(
            frozenset(
                (blocker, blocked)
                for blocker, blocked in self.edges
                if blocker in item_ids and blocked in item_ids
            )
        )

    def without_edges(self, edges: Iterable[Edge]) -> DependencyGraph:
        """This graph less those edges.

        Nothing to check: taking a dependency away cannot close a loop,
        and an edge that was not there was already not there.
        """
        return DependencyGraph(self.edges - frozenset(edges))

    def blockers_of(self, item_id: ItemId) -> list[ItemId]:
        """What this item waits on."""
        return sorted(blocker for blocker, blocked in self.edges if blocked == item_id)

    def dependents_of(self, item_id: ItemId) -> list[ItemId]:
        """What waits on this item."""
        return sorted(blocked for blocker, blocked in self.edges if blocker == item_id)

    def is_blocked(self, item_id: ItemId, done_ids: Container[ItemId]) -> bool:
        """Whether anything this item waits on is still unfinished.

        Needs the graph and the finished set together, which is why it is
        neither a field on the item nor a column in a query.
        """
        if item_id in done_ids:
            # A finished item waits on nothing, whatever the edges say.
            return False
        return any(blocker not in done_ids for blocker in self.blockers_of(item_id))

    def _reaches(
        self, start: ItemId, target: ItemId, *, ignoring: Edge | None = None
    ) -> bool:
        """Is `target` reachable from `start` by following blocks-edges?"""
        blocks: dict[ItemId, list[ItemId]] = {}
        for edge in self.edges:
            if edge == ignoring:
                continue
            blocks.setdefault(edge[0], []).append(edge[1])

        seen: set[ItemId] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current == target:
                return True
            if current in seen:
                continue
            seen.add(current)
            stack.extend(blocks.get(current, []))
        return False
