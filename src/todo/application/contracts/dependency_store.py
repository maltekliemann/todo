"""Where the dependency graph is kept.

The graph is one aggregate — an edge belongs to neither item it joins,
and the rule that admits it ranges over all of them — so it is stored as
one thing. There is no add-an-edge here: an edge is only ever admissible
with respect to the whole set, and the whole set is what the domain hands
over.
"""

from __future__ import annotations

from typing import Protocol

from todo.domain.dependency_graph import DependencyGraph


class DependencyStore(Protocol):
    def load(self) -> DependencyGraph:
        """Every dependency, as one value. Raises if what was kept is not
        a graph the domain would allow — something wrote around it."""
        ...

    def save(self, graph: DependencyGraph) -> None:
        """Keep exactly these dependencies, all at once or not at all.

        Exactly these: what was kept before is replaced, not merged. Load
        and save are not serialized against each other, so a second
        writer landing between someone's load and their save does not
        interleave with them — it erases what they added. The window is
        one call wide and this is a single-user program run one command
        at a time, which is the whole of why that is acceptable; see the
        note on ItemStore for the terms of that decision and what would
        end it.
        """
        ...
