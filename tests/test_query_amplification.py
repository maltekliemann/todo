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
