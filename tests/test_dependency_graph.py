"""The dependency graph: the rule that no item can wait on itself.

No storage, no fixtures — the point of the graph being a domain value is
that its rules are testable as arithmetic.
"""

from __future__ import annotations

import pytest

from todo.domain.dependency_graph import DependencyGraph
from todo.domain.item_id import ItemId
from todo.exceptions import DependencyError


def graph(*edges: tuple[int, int]) -> DependencyGraph:
    return DependencyGraph(frozenset((ItemId(a), ItemId(b)) for a, b in edges))


class TestAdding:
    def test_an_edge_is_added(self) -> None:
        assert graph().with_edge(ItemId(1), ItemId(2)).edges == {(1, 2)}

    def test_the_original_is_untouched(self) -> None:
        before = graph((1, 2))
        before.with_edge(ItemId(2), ItemId(3))
        assert before.edges == {(1, 2)}

    def test_adding_the_same_edge_twice_changes_nothing(self) -> None:
        assert graph((1, 2)).with_edge(ItemId(1), ItemId(2)).edges == {(1, 2)}

    def test_a_diamond_is_not_a_cycle(self) -> None:
        """Two paths reaching the same item is ordinary, not a loop."""
        diamond = graph((1, 2), (1, 3), (2, 4)).with_edge(ItemId(3), ItemId(4))
        assert len(diamond.edges) == 4


class TestRefusing:
    def test_an_item_cannot_block_itself(self) -> None:
        with pytest.raises(DependencyError, match="cannot block itself"):
            graph().with_edge(ItemId(1), ItemId(1))

    def test_a_direct_cycle_is_refused(self) -> None:
        with pytest.raises(DependencyError, match="cycle"):
            graph((1, 2)).with_edge(ItemId(2), ItemId(1))

    def test_a_transitive_cycle_is_refused(self) -> None:
        with pytest.raises(DependencyError, match="cycle"):
            graph((1, 2), (2, 3)).with_edge(ItemId(3), ItemId(1))

    def test_a_long_chain_is_walked(self) -> None:
        chain = [(i, i + 1) for i in range(1, 50)]
        with pytest.raises(DependencyError, match="cycle"):
            graph(*chain).with_edge(ItemId(50), ItemId(1))

    def test_converging_paths_are_walked_once(self) -> None:
        """Two routes into the same item must not be explored twice — on a
        diamond-heavy graph that is the difference between linear and
        exponential."""
        converging = graph((1, 2), (1, 3), (2, 4), (3, 4), (4, 5))
        # Reaches everything downstream of 1 without looping on 4.
        assert converging.with_edge(ItemId(9), ItemId(1)).edges >= {(9, 1)}
        with pytest.raises(DependencyError, match="cycle"):
            converging.with_edge(ItemId(5), ItemId(1))

    def test_a_refused_addition_leaves_the_graph_alone(self) -> None:
        before = graph((1, 2))
        with pytest.raises(DependencyError):
            before.with_edge(ItemId(2), ItemId(1))
        assert before.edges == {(1, 2)}


class TestLoading:
    """Construction validates too, which is what catches a set written by
    something that went around this type."""

    def test_a_cyclic_edge_set_cannot_be_loaded(self) -> None:
        with pytest.raises(DependencyError, match="cycle"):
            graph((1, 2), (2, 1))

    def test_a_self_edge_cannot_be_loaded(self) -> None:
        with pytest.raises(DependencyError, match="blocks itself"):
            graph((1, 1))

    def test_a_valid_set_loads(self) -> None:
        assert graph((1, 2), (2, 3), (1, 3)).edges == {(1, 2), (2, 3), (1, 3)}

    def test_the_empty_graph_is_valid(self) -> None:
        assert graph().edges == frozenset()
