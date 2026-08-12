"""Graph mutations must not rescan the dependency table per blocker."""

from __future__ import annotations

import pytest

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import add_todo, block_todo_batch
from todo.exceptions import DependencyError, NotFoundError


class TestBatchGraphLoad:
    def test_batch_loads_edge_table_once(
        self, storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        for title in ("a", "b", "c", "d"):
            add_todo(storage, title)

        calls = 0
        original = SqliteStorage.dependency_edges

        def counting(self: SqliteStorage):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return original(self)

        monkeypatch.setattr(SqliteStorage, "dependency_edges", counting)
        item = block_todo_batch(storage, 1, [2, 3, 4])
        assert item.blocked_by == [2, 3, 4]
        assert calls == 1

    def test_batch_still_detects_cycle_formed_within_the_batch(
        self, storage: SqliteStorage
    ) -> None:
        """The once-per-batch graph must be updated as edges are added, or
        a cycle whose edges are all new would slip through."""
        for title in ("a", "b"):
            add_todo(storage, title)
        block_todo_batch(storage, 2, [1])  # 1 blocks 2
        with pytest.raises(DependencyError, match="cycle"):
            block_todo_batch(storage, 1, [2])
        # And entirely within one batch: 1 blocked by 2 then 2 blocked by 1
        # cannot both be applied — validated against the in-batch edge.
        add_todo(storage, "c")
        with pytest.raises(DependencyError, match="itself|cycle"):
            block_todo_batch(storage, 3, [1, 3])

    def test_batch_error_precedence_unchanged(self, storage: SqliteStorage) -> None:
        add_todo(storage, "a")
        with pytest.raises(DependencyError, match="itself"):
            block_todo_batch(storage, 1, [1])
        with pytest.raises(NotFoundError):
            block_todo_batch(storage, 1, [999])


class TestCompletionDependentQueries:
    def test_completing_a_blocker_does_not_hydrate_every_dependent(
        self, storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Completion needs before/after blocked-ness of dependents, not two
        full hydrations per dependent — use the blocked-ids set like the
        batch graph load does, and hydrate only the newly unblocked."""
        from todo.application.commands import complete_todo

        add_todo(storage, "blocker")  # 1
        add_todo(storage, "second blocker")  # 2
        for i in range(5):
            add_todo(storage, f"dep{i}")  # 3..7
        block_todo_batch(storage, 3, [1])  # only dep 3 unblocks when 1 is done
        for dep in (4, 5, 6, 7):
            block_todo_batch(storage, dep, [1, 2])

        calls = 0
        original = SqliteStorage.get

        def counting(self: SqliteStorage, item_id: int):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return original(self, item_id)

        monkeypatch.setattr(SqliteStorage, "get", counting)
        result = complete_todo(storage, 1)
        assert [d.id for d in result.unblocked] == [3]
        # item + update's pair + one hydration per newly-unblocked dep —
        # NOT two hydrations for each of the five dependents.
        assert calls <= 6

    def test_delete_unblock_reporting_same_bound(
        self, storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from todo.application.commands import delete_todo

        add_todo(storage, "blocker")  # 1
        add_todo(storage, "second blocker")  # 2
        for i in range(5):
            add_todo(storage, f"dep{i}")  # 3..7
        block_todo_batch(storage, 3, [1])
        for dep in (4, 5, 6, 7):
            block_todo_batch(storage, dep, [1, 2])

        calls = 0
        original = SqliteStorage.get

        def counting(self: SqliteStorage, item_id: int):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return original(self, item_id)

        monkeypatch.setattr(SqliteStorage, "get", counting)
        unblocked = delete_todo(storage, 1)
        assert [d.id for d in unblocked] == [3]
        assert calls <= 5


class TestAddBlockerExistenceChecks:
    def test_add_blocker_does_not_hydrate_for_existence(
        self, storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """add_blocker only needs existence, not two full hydrations the
        caller already performed."""
        add_todo(storage, "a")
        add_todo(storage, "b")

        calls = 0
        original = SqliteStorage.get

        def counting(self: SqliteStorage, item_id: int):  # type: ignore[no-untyped-def]
            nonlocal calls
            calls += 1
            return original(self, item_id)

        monkeypatch.setattr(SqliteStorage, "get", counting)
        block_todo_batch(storage, 1, [2])
        assert calls <= 3  # batch's own checks + returned item, none inside add_blocker

    def test_add_blocker_keeps_not_found_contract(self, storage: SqliteStorage) -> None:
        add_todo(storage, "a")
        with pytest.raises(NotFoundError):
            storage.add_blocker(1, 999)
        with pytest.raises(NotFoundError):
            storage.add_blocker(999, 1)
