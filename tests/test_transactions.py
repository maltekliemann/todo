"""Storage transactions: dependency-graph mutations are atomic units."""

from __future__ import annotations

import pytest

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import add_todo, block_todo, complete_todo


class TestTransactionPrimitive:
    def test_commit_on_success(self, storage: SqliteStorage) -> None:
        with storage.transaction():
            add_todo(storage, "inside")
        assert storage.get(1).title == "inside"

    def test_rollback_on_error(self, storage: SqliteStorage) -> None:
        with pytest.raises(RuntimeError):
            with storage.transaction():
                add_todo(storage, "doomed")
                raise RuntimeError("boom")
        assert storage.list(include_done=True) == []

    def test_reentrant_joins_outer(self, storage: SqliteStorage) -> None:
        with pytest.raises(RuntimeError):
            with storage.transaction():
                add_todo(storage, "outer")
                with storage.transaction():
                    add_todo(storage, "inner")
                raise RuntimeError("boom")
        assert storage.list(include_done=True) == []

    def test_writes_after_transaction_still_commit(
        self, storage: SqliteStorage
    ) -> None:
        with storage.transaction():
            add_todo(storage, "first")
        add_todo(storage, "second")
        assert len(storage.list(include_done=True)) == 2


class _DepVanishesStorage(SqliteStorage):
    """Simulates a concurrent 'todo rm' of a dependent between the
    completing UPDATE and the unblock-reporting reads."""

    def __init__(self, *a: object, **k: object) -> None:
        super().__init__(*a, **k)  # type: ignore[arg-type]
        self.vanish_id: int | None = None

    def update(self, item_id: int, **kwargs: object):  # type: ignore[override]
        result = super().update(item_id, **kwargs)  # type: ignore[arg-type]
        if self.vanish_id is not None:
            victim, self.vanish_id = self.vanish_id, None
            super().delete(victim)
        return result


class TestCompletionInvariant:
    def test_vanished_dependent_does_not_fail_completion(self, db_path) -> None:
        """Completing an item must not report failure after mutating just
        because a dependent disappeared concurrently."""
        storage = _DepVanishesStorage(db_path)
        add_todo(storage, "Blocker")
        add_todo(storage, "Waiting")
        block_todo(storage, 2, 1)

        storage.vanish_id = 2  # rm the dependent right after the UPDATE
        result = complete_todo(storage, 1)
        assert result.item.is_done
        assert result.unblocked == []  # vanished dep simply omitted
