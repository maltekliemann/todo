"""Which items block which, and the rule that spans all of them."""

from __future__ import annotations

from dataclasses import dataclass

from todo.exceptions import DependencyError

# (blocker, blocked): the blocker must be done before the blocked item.
Edge = tuple[int, int]


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
                raise DependencyError(f"Item #{blocker} blocks itself.")
        for blocker, blocked in self.edges:
            # Reachable backwards, with this edge itself left out of the
            # walk: that is what "this edge closes a loop" means.
            if self._reaches(blocked, blocker, ignoring=(blocker, blocked)):
                raise DependencyError("The dependencies contain a cycle.")

    def with_edge(self, blocker: int, blocked: int) -> DependencyGraph:
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

    def _reaches(
        self, start: int, target: int, *, ignoring: Edge | None = None
    ) -> bool:
        """Is `target` reachable from `start` by following blocks-edges?"""
        blocks: dict[int, list[int]] = {}
        for edge in self.edges:
            if edge == ignoring:
                continue
            blocks.setdefault(edge[0], []).append(edge[1])

        seen: set[int] = set()
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
