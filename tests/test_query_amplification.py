"""Graph mutations must not rescan the dependency table per blocker."""

from __future__ import annotations

import pytest

from todo.adapters.sqlite_dependency_store import SqliteDependencyStore
from todo.adapters.sqlite_item_store import SqliteItemStore
from todo.application.commands import add_todo, block_todo, block_todo_batch
from todo.application.dependencies import Dependencies
from todo.domain.dependency_graph import DependencyGraph
from todo.domain.item_id import ItemId
from todo.domain.title import Title
from todo.domain.todo_item import TodoItem
from todo.exceptions import DependencyError, NotFoundError


class TestBatchGraphLoad:
    def test_batch_loads_edge_table_once(
        self,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        for title in ("a", "b", "c", "d"):
            add_todo(items, title)

        calls = 0
        original = SqliteDependencyStore.load

        def counting(self: SqliteDependencyStore) -> DependencyGraph:
            nonlocal calls
            calls += 1
            return original(self)

        monkeypatch.setattr(SqliteDependencyStore, "load", counting)
        block_todo_batch(items, dependencies, 1, [2, 3, 4])
        assert calls == 1  # counted before anything else reads the graph
        assert Dependencies.load(items, dependencies).blockers_of(1) == [2, 3, 4]

    def test_batch_still_detects_cycle_formed_within_the_batch(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        """The once-per-batch graph must be updated as edges are added, or
        a cycle whose edges are all new would slip through."""
        for title in ("a", "b"):
            add_todo(items, title)
        block_todo_batch(items, dependencies, 2, [1])  # 1 blocks 2
        with pytest.raises(DependencyError, match="cycle"):
            block_todo_batch(items, dependencies, 1, [2])
        # And entirely within one batch: 1 blocked by 2 then 2 blocked by 1
        # cannot both be applied — validated against the in-batch edge.
        add_todo(items, "c")
        with pytest.raises(DependencyError, match="itself|cycle"):
            block_todo_batch(items, dependencies, 3, [1, 3])

    def test_batch_error_precedence_unchanged(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        add_todo(items, "a")
        with pytest.raises(DependencyError, match="itself"):
            block_todo_batch(items, dependencies, 1, [1])
        with pytest.raises(NotFoundError):
            block_todo_batch(items, dependencies, 1, [999])


class TestCompletionDependentQueries:
    def test_completing_a_blocker_does_not_hydrate_every_dependent(
        self,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Completion needs before/after blocked-ness of dependents, not two
        full hydrations per dependent — use the blocked-ids set like the
        batch graph load does, and hydrate only the newly unblocked."""
        from todo.application.commands import complete_todo

        add_todo(items, "blocker")  # 1
        add_todo(items, "second blocker")  # 2
        for i in range(5):
            add_todo(items, f"dep{i}")  # 3..7
        block_todo_batch(
            items, dependencies, 3, [1]
        )  # only dep 3 unblocks when 1 is done
        for dep in (4, 5, 6, 7):
            block_todo_batch(items, dependencies, dep, [1, 2])

        calls = 0
        original = SqliteItemStore.get

        def counting(self: SqliteItemStore, item_id: ItemId) -> TodoItem:
            nonlocal calls
            calls += 1
            return original(self, item_id)

        monkeypatch.setattr(SqliteItemStore, "get", counting)
        result = complete_todo(items, dependencies, 1)
        assert [d.id for d in result.unblocked] == [3]
        # item + update's pair + one hydration per newly-unblocked dep —
        # NOT two hydrations for each of the five dependents.
        assert calls <= 6

    def test_delete_unblock_reporting_same_bound(
        self,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from todo.application.commands import delete_todo

        add_todo(items, "blocker")  # 1
        add_todo(items, "second blocker")  # 2
        for i in range(5):
            add_todo(items, f"dep{i}")  # 3..7
        block_todo_batch(items, dependencies, 3, [1])
        for dep in (4, 5, 6, 7):
            block_todo_batch(items, dependencies, dep, [1, 2])

        calls = 0
        original = SqliteItemStore.get

        def counting(self: SqliteItemStore, item_id: ItemId) -> TodoItem:
            nonlocal calls
            calls += 1
            return original(self, item_id)

        monkeypatch.setattr(SqliteItemStore, "get", counting)
        unblocked = delete_todo(items, dependencies, 1)
        assert [d.id for d in unblocked] == [3]
        assert calls <= 5


class TestAddBlockerExistenceChecks:
    def test_add_blocker_does_not_hydrate_for_existence(
        self,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """add_blocker only needs existence, not two full hydrations the
        caller already performed."""
        add_todo(items, "a")
        add_todo(items, "b")

        calls = 0
        original = SqliteItemStore.get

        def counting(self: SqliteItemStore, item_id: ItemId) -> TodoItem:
            nonlocal calls
            calls += 1
            return original(self, item_id)

        monkeypatch.setattr(SqliteItemStore, "get", counting)
        block_todo_batch(items, dependencies, 1, [2])
        assert calls <= 3  # batch's own checks + returned item, none inside add_blocker

    def test_add_blocker_keeps_not_found_contract(
        self, dependencies: SqliteDependencyStore, items: SqliteItemStore
    ) -> None:
        add_todo(items, "a")
        with pytest.raises(NotFoundError):
            block_todo(items, dependencies, 1, 999)
        with pytest.raises(NotFoundError):
            block_todo(items, dependencies, 999, 1)


class TestWritePathExistenceChecks:
    def test_edit_does_not_triple_hydrate(
        self,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """update()'s existence check must be a probe, not a third full
        dependency hydration of the same item."""
        from todo.application.commands import edit_todo

        add_todo(items, "x")
        calls = 0
        original = SqliteItemStore.get

        def counting(self: SqliteItemStore, item_id: ItemId) -> TodoItem:
            nonlocal calls
            calls += 1
            return original(self, item_id)

        monkeypatch.setattr(SqliteItemStore, "get", counting)
        edit_todo(items, dependencies, 1, title="renamed")
        assert calls <= 2  # the command's read + the returned item

    def test_delete_does_not_hydrate_for_existence(
        self,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from todo.application.commands import delete_todo

        add_todo(items, "x")
        calls = 0
        original = SqliteItemStore.get

        def counting(self: SqliteItemStore, item_id: ItemId) -> TodoItem:
            nonlocal calls
            calls += 1
            return original(self, item_id)

        monkeypatch.setattr(SqliteItemStore, "get", counting)
        delete_todo(items, dependencies, 1)
        assert calls <= 1  # only the command's victim read

    def test_save_writes_what_the_item_holds(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        """The adapter no longer decides the completion stamp — it used to
        pre-read the row's status to work it out. It writes what the item
        holds, and the item decided that in move_to."""
        from datetime import datetime

        from todo.application.commands import complete_todo, move_todo
        from todo.domain.body import Body
        from todo.domain.item_id import ItemId
        from todo.domain.priority import Priority
        from todo.domain.status import Status
        from todo.domain.todo_item import TodoItem

        now = datetime.now()
        missing = TodoItem(
            id=ItemId(999),
            title=Title("x"),
            body=Body(""),
            priority=Priority.MEDIUM,
            status=Status.TODO,
            created_at=now,
            updated_at=now,
        )
        with pytest.raises(NotFoundError):
            items.save(missing)

        add_todo(items, "x")
        completed = complete_todo(items, dependencies, ItemId(1)).item
        assert isinstance(completed.done_at, datetime)

        reopened = move_todo(items, dependencies, ItemId(1), Status.TODO).item
        assert reopened.done_at is None

    def test_batch_existence_validated_once_per_id(
        self,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """block_todo_batch must not enforce existence at two altitudes
        (full-hydration get per blocker plus the adapter's own probes)."""
        for title in ("a", "b", "c", "d"):
            add_todo(items, title)
        calls = 0
        original = SqliteItemStore.get

        def counting(self: SqliteItemStore, item_id: ItemId) -> TodoItem:
            nonlocal calls
            calls += 1
            return original(self, item_id)

        monkeypatch.setattr(SqliteItemStore, "get", counting)
        block_todo_batch(items, dependencies, 1, [2, 3, 4])
        assert calls <= 2  # blocked item + returned item, none per blocker

    def test_batch_missing_blocker_still_not_found_and_rolls_back(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore
    ) -> None:
        add_todo(items, "a")
        add_todo(items, "b")
        with pytest.raises(NotFoundError):
            block_todo_batch(items, dependencies, 1, [2, 999])
        assert (
            Dependencies.load(items, dependencies).blockers_of(1) == []
        )  # nothing half-applied


class TestGraphReadsPerCommand:
    def test_a_command_reads_the_graph_at_most_once(
        self,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Dependents used to ride along on item hydration, which cost two
        dependency queries on every single read. They come from the graph
        now, which must be read once per command that needs it — never per
        item, never twice."""
        from todo.application.commands import complete_todo, delete_todo

        add_todo(items, "solo")
        add_todo(items, "another solo")

        calls = 0
        original = SqliteDependencyStore.load

        def counting(self: SqliteDependencyStore) -> DependencyGraph:
            nonlocal calls
            calls += 1
            return original(self)

        monkeypatch.setattr(SqliteDependencyStore, "load", counting)

        complete_todo(items, dependencies, 1)
        assert calls == 1

        calls = 0
        delete_todo(items, dependencies, 2)
        assert calls == 1

    def test_an_edit_that_cannot_unblock_anything_never_reads_it(
        self,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Only a completion can free a dependent, so retitling, moving to
        in-progress, or reopening pays nothing for the graph."""
        from todo.application.commands import edit_todo
        from todo.domain.status import Status

        add_todo(items, "task")

        calls = 0
        original = SqliteDependencyStore.load

        def counting(self: SqliteDependencyStore) -> DependencyGraph:
            nonlocal calls
            calls += 1
            return original(self)

        monkeypatch.setattr(SqliteDependencyStore, "load", counting)
        edit_todo(items, dependencies, 1, title="renamed")
        edit_todo(items, dependencies, 1, status=Status.IN_PROGRESS)
        assert calls == 0
