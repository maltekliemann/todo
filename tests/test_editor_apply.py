"""The $EDITOR round-trip: parsing/applying edits and surviving editor failure."""

from __future__ import annotations

from pathlib import Path

import pytest

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import add_todo, block_todo
from todo.domain.enums import Priority, Status
from todo.tui.app import TodoApp
from todo.tui.list_view import _item_to_editor_text, apply_editor_edit


def _edited(storage: SqliteStorage, item_id: int, **replacements: str) -> str:
    """The editor buffer for an item with whole lines replaced by field name."""
    text = _item_to_editor_text(storage.get(item_id))
    lines = []
    for line in text.split("\n"):
        key = line.partition(":")[0].strip().lower()
        if key in replacements:
            lines.append(f"{key}: {replacements[key]}")
        else:
            lines.append(line)
    return "\n".join(lines)


class TestApplyEditorEdit:
    def test_clearing_tags_line_clears_tags(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task", tags=["a", "b"])
        result = apply_editor_edit(storage, 1, _edited(storage, 1, tags=""))
        assert result.item.tags == []

    def test_absent_tags_line_keeps_tags(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task", tags=["a", "b"])
        text = "\n".join(
            line
            for line in _edited(storage, 1).split("\n")
            if not line.startswith("tags:")
        )
        result = apply_editor_edit(storage, 1, text)
        assert result.item.tags == ["a", "b"]

    def test_replacing_tags(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task", tags=["a"])
        result = apply_editor_edit(storage, 1, _edited(storage, 1, tags="x, y"))
        assert result.item.tags == ["x", "y"]

    def test_status_done_reports_unblocked(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Blocker")
        add_todo(storage, "Waiting")
        block_todo(storage, 2, 1)
        result = apply_editor_edit(storage, 1, _edited(storage, 1, status="done"))
        assert result.item.status == Status.DONE
        assert [dep.id for dep in result.unblocked] == [2]

    def test_clearing_deadline_still_works(self, storage: SqliteStorage) -> None:
        from datetime import date

        add_todo(storage, "Task", deadline=date(2099, 1, 1))
        result = apply_editor_edit(storage, 1, _edited(storage, 1, deadline=""))
        assert result.item.deadline is None

    def test_absent_deadline_line_keeps_deadline(self, storage: SqliteStorage) -> None:
        from datetime import date

        add_todo(storage, "Task", deadline=date(2099, 1, 1))
        text = "\n".join(
            line
            for line in _edited(storage, 1).split("\n")
            if not line.startswith("deadline:")
        )
        result = apply_editor_edit(storage, 1, text)
        assert result.item.deadline == date(2099, 1, 1)

    def test_priority_change(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task")
        result = apply_editor_edit(storage, 1, _edited(storage, 1, priority="urgent"))
        assert result.item.priority == Priority.URGENT


class TestEditorBodyContract:
    def test_missing_body_marker_keeps_body(self, storage: SqliteStorage) -> None:
        """Deleting the '# Body' marker line must not erase the body."""
        add_todo(storage, "Task", body="important body text")
        text = "\n".join(
            line
            for line in _item_to_editor_text(storage.get(1)).split("\n")
            if not line.startswith("# Body")
        )
        result = apply_editor_edit(storage, 1, text)
        assert result.item.body == "important body text"

    def test_emptying_body_below_marker_clears_it(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task", body="old body")
        text = _item_to_editor_text(storage.get(1))
        marker_idx = text.index("# Body")
        result = apply_editor_edit(
            storage, 1, text[: marker_idx + text[marker_idx:].index("\n") + 1]
        )
        assert result.item.body == ""


class TestEditorInvalidFields:
    def test_invalid_priority_raises_clean_error(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task")
        with pytest.raises(ValueError, match="Invalid priority"):
            apply_editor_edit(storage, 1, _edited(storage, 1, priority="hgih"))
        # Nothing changed.
        assert storage.get(1).priority.value == "medium"

    def test_invalid_status_raises_clean_error(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task")
        with pytest.raises(ValueError, match="Invalid status"):
            apply_editor_edit(storage, 1, _edited(storage, 1, status="doen"))
        assert storage.get(1).status.value == "todo"

    def test_invalid_deadline_raises_like_cli(self, storage: SqliteStorage) -> None:
        """CLI rejects bad deadlines; the editor path must too, not silently
        ignore them (mutation-path parity)."""
        add_todo(storage, "Task")
        with pytest.raises(ValueError, match="[Dd]eadline"):
            apply_editor_edit(storage, 1, _edited(storage, 1, deadline="garbage"))


class TestEditorFailureHandling:
    async def test_broken_editor_does_not_crash_tui(
        self, db_path: Path, monkeypatch
    ) -> None:
        """A missing/broken $EDITOR shows an error instead of tearing down."""
        storage = SqliteStorage(db_path)
        add_todo(storage, "Task")
        monkeypatch.setenv("EDITOR", "/nonexistent/editor-binary")

        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert app.is_running
            # Item unchanged.
            assert storage.get(1).title == "Task"
