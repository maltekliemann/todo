"""A store write is one unit: all of it happens, or none of it does.

The application never asks for a transaction — it has no word for one.
What it relies on is that keeping an aggregate is a single act, which is
the store's promise to make good on.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from todo.adapters.sqlite_dependency_store import SqliteDependencyStore
from todo.adapters.sqlite_item_store import SqliteItemStore
from todo.adapters.sqlite_project_store import SqliteProjectStore
from todo.application.commands import (
    add_todo,
    block_todo,
    block_todo_batch,
    complete_todo,
)
from todo.application.dependencies import Dependencies
from todo.domain.item_id import ItemId
from todo.domain.todo_item import TodoItem
from todo.exceptions import NotFoundError, StorageError


class TestGraphWritesAreOneUnit:
    def test_a_refused_batch_leaves_the_graph_untouched(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        for title in ("a", "b", "c"):
            add_todo(items, title)
        block_todo(items, dependencies, 1, 2)

        with pytest.raises(NotFoundError):
            block_todo_batch(items, dependencies, 1, [3, 999])

        # Neither the valid half of the batch nor the pre-existing edge
        # is disturbed: the graph is written once, after every addition
        # has been allowed.
        assert dependencies.load().blockers_of(ItemId(1)) == [ItemId(2)]

    def test_saving_a_graph_replaces_it_wholesale(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        for title in ("a", "b", "c"):
            add_todo(items, title)
        block_todo(items, dependencies, 1, 2)
        graph = dependencies.load()

        dependencies.save(graph.without_edges([(ItemId(2), ItemId(1))]))
        assert dependencies.load().edges == frozenset()


class _DepVanishesStore(SqliteItemStore):
    """Simulates a concurrent 'todo rm' of a dependent between the
    completing save and the unblock-reporting reads."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.vanish_id: ItemId | None = None

    def save(self, item: TodoItem) -> TodoItem:
        result = super().save(item)
        if self.vanish_id is not None:
            victim, self.vanish_id = self.vanish_id, None
            super().delete(victim)
        return result


class TestCompletionInvariant:
    def test_vanished_dependent_does_not_fail_completion(
        self, dependencies: SqliteDependencyStore, db_path: Path
    ) -> None:
        """Completing an item must not report failure after mutating just
        because a dependent disappeared concurrently."""
        store = _DepVanishesStore(db_path)
        add_todo(store, "Blocker")
        add_todo(store, "Waiting")
        block_todo(store, dependencies, ItemId(2), ItemId(1))

        store.vanish_id = ItemId(2)  # rm the dependent right after the UPDATE
        result = complete_todo(store, dependencies, ItemId(1))
        assert result.item.is_done
        assert result.unblocked == []  # vanished dep simply omitted


class TestStorageErrorWrapping:
    """sqlite-level failures surface as StorageError (a TodoError), so the
    TUI's single error guard catches them like the CLI does."""

    def test_a_failed_write_is_a_todo_error(self, items: SqliteItemStore) -> None:
        add_todo(items, "x")
        item = items.get(ItemId(1))
        items.close()
        with pytest.raises(StorageError):
            items.save(item)

    def test_delete_wraps_sqlite_errors(self, items: SqliteItemStore) -> None:
        add_todo(items, "x")
        items.close()
        with pytest.raises(StorageError):
            items.delete(ItemId(1))

    def test_delete_project_wraps_sqlite_errors(
        self, projects: SqliteProjectStore
    ) -> None:
        projects.close()
        with pytest.raises(StorageError):
            projects.delete(1)  # type: ignore[arg-type]

    def test_graph_save_wraps_sqlite_errors(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        add_todo(items, "a")
        graph = dependencies.load()
        dependencies.close()
        with pytest.raises(StorageError):
            dependencies.save(graph)


class TestTheGapBetweenTwoWrites:
    """Two aggregates cannot be written in one go. What makes that
    survivable is that the state in between is a state the domain calls
    legal — not that the window is small."""

    def test_edges_left_behind_by_a_crash_read_as_nothing(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        add_todo(items, "blocker")
        add_todo(items, "waiting")
        block_todo(items, dependencies, ItemId(2), ItemId(1))

        # Exactly what a crash between delete_todo's two writes leaves:
        # the item gone, its edges still stored.
        items.delete(ItemId(1))
        assert dependencies.load().blockers_of(ItemId(2)) == [ItemId(1)]

        deps = Dependencies.load(items, dependencies)
        assert deps.blockers_of(ItemId(2)) == []
        assert deps.is_blocked(ItemId(2)) is False

    def test_the_next_write_clears_them(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        add_todo(items, "blocker")
        add_todo(items, "waiting")
        block_todo(items, dependencies, ItemId(2), ItemId(1))
        items.delete(ItemId(1))

        add_todo(items, "third")
        block_todo(items, dependencies, ItemId(3), ItemId(2))
        # The graph is saved as it was read — for the items that exist —
        # so the stale edge does not come back with it.
        assert dependencies.load().edges == frozenset({(ItemId(2), ItemId(3))})
