"""A store write is one unit: all of it happens, or none of it does.

The application never asks for a transaction — it has no word for one.
What it relies on is that keeping an aggregate is a single act, which is
the store's promise to make good on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from tests.factory import NewItem, add_blocker, add_todo, delete_todo, set_status
from todo.adapters.sqlite_dependency_store import SqliteDependencyStore
from todo.adapters.sqlite_item_store import SqliteItemStore
from todo.adapters.sqlite_project_store import SqliteProjectStore
from todo.domain.item_id import ItemId
from todo.domain.status import Status
from todo.domain.todo_item import TodoItem
from todo.exceptions import NotFoundError, StorageError
from todo.infra.cli.main import _report


class TestGraphWritesAreOneUnit:
    def test_a_refused_batch_leaves_the_graph_untouched(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        for title in ("a", "b", "c"):
            add_todo(items, NewItem(title=title))
        add_blocker(items, dependencies, 1, [2])

        with pytest.raises(NotFoundError):
            add_blocker(items, dependencies, 1, [3, 999])

        # Neither the valid half of the batch nor the pre-existing edge
        # is disturbed: the graph is written once, after every addition
        # has been allowed.
        assert dependencies.load().blockers_of(ItemId(1)) == [ItemId(2)]

    def test_saving_a_graph_replaces_it_wholesale(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        for title in ("a", "b", "c"):
            add_todo(items, NewItem(title=title))
        add_blocker(items, dependencies, 1, [2])
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
        add_todo(store, NewItem(title="Blocker"))
        add_todo(store, NewItem(title="Waiting"))
        add_blocker(store, dependencies, ItemId(2), [ItemId(1)])

        store.vanish_id = ItemId(2)  # rm the dependent right after the UPDATE
        result = set_status(store, dependencies, ItemId(1), Status.DONE)
        # The completion stands. The toast names #2 because a toast
        # carries ids and nothing is loaded to make one — whoever renders
        # it deals with an item that is no longer there.
        assert store.get(ItemId(1)).is_done
        assert [item_id for toast in result for item_id in toast.items] == [ItemId(2)]

    def test_a_vanished_dependent_is_reported_without_a_title(
        self, dependencies: SqliteDependencyStore, db_path: Path
    ) -> None:
        """The CLI looks a title up to word the toast; the item may be
        gone by then, and that must not turn into a traceback."""
        store = _DepVanishesStore(db_path)
        add_todo(store, NewItem(title="Blocker"))
        add_todo(store, NewItem(title="Waiting"))
        add_blocker(store, dependencies, ItemId(2), [ItemId(1)])

        store.vanish_id = ItemId(2)
        toasts = set_status(store, dependencies, ItemId(1), Status.DONE)
        runner = CliRunner()
        with runner.isolation() as (out, err, _):
            _report(store, toasts)
        assert err.getvalue().decode() == "🔓 #2 is now unblocked\n"


class TestStorageErrorWrapping:
    """sqlite-level failures surface as StorageError (a TodoError), so the
    TUI's single error guard catches them like the CLI does."""

    def test_a_failed_write_is_a_todo_error(self, items: SqliteItemStore) -> None:
        add_todo(items, NewItem(title="x"))
        item = items.get(ItemId(1))
        items.close()
        with pytest.raises(StorageError):
            items.save(item)

    def test_delete_wraps_sqlite_errors(self, items: SqliteItemStore) -> None:
        add_todo(items, NewItem(title="x"))
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
        add_todo(items, NewItem(title="a"))
        graph = dependencies.load()
        dependencies.close()
        with pytest.raises(StorageError):
            dependencies.save(graph)


class TestTheGapBetweenTwoWrites:
    """Two aggregates cannot be written in one go, so the order decides
    what a crash between them leaves behind."""

    def test_edges_go_before_the_item_they_name(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        add_todo(items, NewItem(title="blocker"))
        add_todo(items, NewItem(title="waiting"))
        add_blocker(items, dependencies, ItemId(2), [ItemId(1)])

        delete_todo(items, dependencies, ItemId(1))
        assert dependencies.load().edges == frozenset()
        graph = dependencies.load()
        done = items.done_ids()
        assert graph.blockers_of(ItemId(2)) == []
        assert graph.is_blocked(ItemId(2), done) is False
