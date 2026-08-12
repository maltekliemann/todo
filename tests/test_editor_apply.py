"""The $EDITOR round-trip: parsing/applying edits and surviving editor failure."""

from __future__ import annotations

from pathlib import Path

import pytest

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import add_todo, block_todo
from todo.domain.enums import Priority, Status
from todo.tui.app import TodoApp
from todo.tui.editor import apply_editor_edit, item_to_editor_text


def _edited(storage: SqliteStorage, item_id: int, **replacements: str) -> str:
    """The editor buffer for an item with whole lines replaced by field name."""
    text = item_to_editor_text(storage.get(item_id))
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
    def test_missing_body_marker_rejects_edit(self, storage: SqliteStorage) -> None:
        """Deleting the '# Body' marker errors (round-10: previously it
        silently kept the body while discarding the user's body edits)."""
        add_todo(storage, "Task", body="important body text")
        text = "\n".join(
            line
            for line in item_to_editor_text(storage.get(1)).split("\n")
            if not line.startswith("# Body")
        )
        with pytest.raises(ValueError, match="[Bb]ody"):
            apply_editor_edit(storage, 1, text)
        assert storage.get(1).body == "important body text"

    def test_emptying_body_below_marker_clears_it(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task", body="old body")
        text = item_to_editor_text(storage.get(1))
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


class TestEditorCommand:
    def test_editor_value_with_arguments_is_split(self) -> None:
        from todo.tui.editor import editor_command

        assert editor_command("code --wait", "/tmp/x") == [
            "code",
            "--wait",
            "/tmp/x",
        ]

    def test_plain_editor_value(self) -> None:
        from todo.tui.editor import editor_command

        assert editor_command("vi", "/tmp/x") == ["vi", "/tmp/x"]

    def test_quoted_editor_path(self) -> None:
        from todo.tui.editor import editor_command

        assert editor_command("'/opt/My Editor/ed' -f", "/tmp/x") == [
            "/opt/My Editor/ed",
            "-f",
            "/tmp/x",
        ]


class TestApplyEditedBuffer:
    """The post-$EDITOR half of action_edit, testable without suspend()."""

    async def test_rejected_edit_keeps_buffer_file(
        self, db_path: Path, tmp_path: Path
    ) -> None:
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "Task", body="keep me")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            original = item_to_editor_text(storage.get(1))
            edited = original.replace("deadline: ", "deadline: 2026/01/01")
            buf = tmp_path / "buffer.todo.txt"
            buf.write_text(edited)

            view._apply_edited_buffer(1, original, edited, str(buf))
            await pilot.pause()

            assert app.is_running
            assert storage.get(1).body == "keep me"  # nothing applied
            assert buf.exists()  # user's work is recoverable

    async def test_missing_item_is_reported_not_crash(
        self, db_path: Path, tmp_path: Path
    ) -> None:
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "Task")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            original = item_to_editor_text(storage.get(1))
            edited = original.replace("title: Task", "title: Renamed")
            buf = tmp_path / "buffer.todo.txt"
            buf.write_text(edited)

            storage.delete(1)  # deleted while "the editor was open"
            view._apply_edited_buffer(1, original, edited, str(buf))
            await pilot.pause()
            assert app.is_running

    async def test_successful_edit_removes_buffer(
        self, db_path: Path, tmp_path: Path
    ) -> None:
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "Task")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            original = item_to_editor_text(storage.get(1))
            edited = original.replace("title: Task", "title: Renamed")
            buf = tmp_path / "buffer.todo.txt"
            buf.write_text(edited)

            view._apply_edited_buffer(1, original, edited, str(buf))
            await pilot.pause()
            assert storage.get(1).title == "Renamed"
            assert not buf.exists()


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


class TestEditorCommandValidation:
    def test_empty_editor_value_raises(self) -> None:
        from todo.tui.editor import editor_command

        with pytest.raises(ValueError, match="EDITOR"):
            editor_command("", "/tmp/x")

    def test_unbalanced_quote_raises_value_error(self) -> None:
        from todo.tui.editor import editor_command

        with pytest.raises(ValueError):
            editor_command('code "', "/tmp/x")


class TestEditorEmptyTitle:
    def test_blanked_title_line_rejects_whole_edit(
        self, storage: SqliteStorage
    ) -> None:
        """'title:' blanked must error, not partially apply the edit."""
        add_todo(storage, "Keep me")
        buffer = _edited(storage, 1, title="", status="in-progress")
        with pytest.raises(ValueError, match="[Tt]itle"):
            apply_editor_edit(storage, 1, buffer)
        # Nothing applied: status unchanged too.
        assert storage.get(1).status.value == "todo"
        assert storage.get(1).title == "Keep me"


class TestEditorBodyWhitespacePreserved:
    def test_title_only_edit_keeps_body_bytes(self, storage: SqliteStorage) -> None:
        """Editing another field must not silently mutate an untouched body
        (indentation and trailing newline included — think pasted code)."""
        body = "    indented line\n\n  second\n"
        add_todo(storage, "Task", body=body)
        result = apply_editor_edit(storage, 1, _edited(storage, 1, title="Renamed"))
        assert result.item.title == "Renamed"
        assert result.item.body == body

    def test_editor_added_trailing_newline_is_not_a_body_change(
        self, storage: SqliteStorage
    ) -> None:
        body = "plain body"
        add_todo(storage, "Task", body=body)
        # POSIX editors terminate the file with a newline on save.
        edited = _edited(storage, 1, title="Renamed") + "\n"
        result = apply_editor_edit(storage, 1, edited)
        assert result.item.body == body

    def test_edited_body_preserves_indentation(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task", body="old")
        text = item_to_editor_text(storage.get(1))
        edited = text.replace("\nold", "\n    def f():\n        pass") + "\n"
        result = apply_editor_edit(storage, 1, edited)
        assert result.item.body == "    def f():\n        pass"


class TestEditorPathWithSpaces:
    def test_unquoted_spaced_path_falls_back_to_verbatim(self, tmp_path: Path) -> None:
        """An unquoted $EDITOR path containing spaces (common on macOS)
        worked before shlex-splitting existed and must keep working."""
        from todo.tui.editor import editor_command

        editor = tmp_path / "My Editor"
        editor.write_text("#!/bin/sh\nexit 0\n")
        editor.chmod(0o755)
        assert editor_command(str(editor), "/tmp/x") == [str(editor), "/tmp/x"]


class TestWhitespaceOnlyBodyEdit:
    async def test_trailing_blank_line_edit_is_applied(
        self, db_path: Path, tmp_path: Path
    ) -> None:
        """The no-op guard must be exact: a whitespace-only body edit is an
        edit ('whitespace is content'), not an unchanged buffer."""
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "Task", body="print(x)")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            original = item_to_editor_text(storage.get(1))
            edited = original + "\n\n"  # append a trailing blank line to the body
            buf = tmp_path / "buffer.todo.txt"
            buf.write_text(edited)

            view._apply_edited_buffer(1, original, edited, str(buf))
            await pilot.pause()
            assert storage.get(1).body == "print(x)\n"

    async def test_editor_final_newline_alone_is_still_a_noop(
        self, db_path: Path, tmp_path: Path
    ) -> None:
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "Task", body="print(x)")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            item_before = storage.get(1)
            original = item_to_editor_text(item_before)
            edited = original + "\n"  # only the editor's final newline
            buf = tmp_path / "buffer.todo.txt"
            buf.write_text(edited)

            view._apply_edited_buffer(1, original, edited, str(buf))
            await pilot.pause()
            after = storage.get(1)
            assert after.body == "print(x)"
            assert after.updated_at == item_before.updated_at  # true no-op
            assert not buf.exists()


class TestMissingBodyMarkerErrors:
    def test_deleted_marker_rejects_edit_instead_of_silent_drop(
        self, storage: SqliteStorage
    ) -> None:
        """Deleting the '# Body' marker must error (buffer kept upstream),
        never report success while the user's body edits are discarded."""
        add_todo(storage, "Task", body="draft the outline")
        text = "\n".join(
            line
            for line in item_to_editor_text(storage.get(1)).split("\n")
            if not line.startswith("# Body")
        )
        text += "\nsend to Alice"  # the body edit that silently vanished
        with pytest.raises(ValueError, match="[Bb]ody"):
            apply_editor_edit(storage, 1, text)
        assert storage.get(1).body == "draft the outline"  # nothing applied

    async def test_marker_less_buffer_keeps_file_and_notifies(
        self, db_path: Path, tmp_path: Path
    ) -> None:
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "Task", body="keep me")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            original = item_to_editor_text(storage.get(1))
            edited = "\n".join(
                line for line in original.split("\n") if not line.startswith("# Body")
            )
            buf = tmp_path / "buffer.todo.txt"
            buf.write_text(edited)
            view._apply_edited_buffer(1, original, edited, str(buf))
            await pilot.pause()
            assert app.is_running
            assert storage.get(1).body == "keep me"
            assert buf.exists()  # user's work recoverable

    def test_body_lines_cannot_inject_fields(self, storage: SqliteStorage) -> None:
        """With the marker required, 'status: done' inside the body region
        is body text, never a field override."""
        add_todo(storage, "Task")
        text = item_to_editor_text(storage.get(1)) + "status: done"
        result = apply_editor_edit(storage, 1, text)
        assert result.item.status.value == "todo"
        assert "status: done" in result.item.body


class TestEditorNonzeroExitKeepsBuffer:
    async def test_called_process_error_keeps_saved_buffer(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A nonzero editor exit can happen AFTER the user saved; the
        buffer must be kept and its path reported, not unlinked."""
        import contextlib
        import re
        import subprocess as sp

        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "Task", body="typed work")
        monkeypatch.setenv("EDITOR", "vi")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            monkeypatch.setattr(
                type(app), "suspend", lambda self: contextlib.nullcontext()
            )

            def failing_run(*args: object, **kwargs: object) -> None:
                raise sp.CalledProcessError(1, "vi")

            monkeypatch.setattr(sp, "run", failing_run)
            notices: list[str] = []
            monkeypatch.setattr(
                view, "notify", lambda msg, **kw: notices.append(str(msg))
            )
            view.action_edit()
            await pilot.pause()
            assert notices and "kept at" in notices[0]
            match = re.search(r"kept at (\S+)", notices[0])
            assert match is not None
            assert Path(match.group(1)).exists()


class TestEditorEncodingRobustness:
    async def test_non_utf8_buffer_reports_instead_of_crashing(
        self, db_path: Path, tmp_path: Path
    ) -> None:
        """An editor that saves in latin-1 must not kill the session, and
        must be told where its buffer is (UnicodeDecodeError is a
        ValueError, so an OSError-only handler misses it)."""
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "Task")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            buf = tmp_path / "latin1.todo.txt"
            buf.write_bytes("title: caf\xe9".encode("latin-1"))
            notices: list[str] = []
            view.notify = lambda msg, **kw: notices.append(str(msg))  # type: ignore[method-assign]

            content = view._read_edited_buffer(str(buf))

            assert app.is_running
            assert content is None
            assert notices and str(buf) in notices[0]

    async def test_unencodable_item_text_does_not_crash(self, db_path: Path) -> None:
        """Buffer writing must use an explicit encoding, so item text is
        never at the mercy of the locale."""
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "Ünïcode ✅ täsk", body="emoji 🎉 body")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            path = view._write_editor_buffer(item_to_editor_text(storage.get(1)))
            try:
                assert "Ünïcode ✅ täsk" in Path(path).read_text(encoding="utf-8")
                assert view._read_edited_buffer(path) is not None
            finally:
                Path(path).unlink(missing_ok=True)


class TestBlankEnumFieldsError:
    """A blanked priority/status line is bad input, not an absent field:
    the title branch errors and the deadline branch clears, so silently
    ignoring these two (and deleting the buffer) is the odd one out."""

    def test_blank_priority_line_rejects_edit(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task")
        with pytest.raises(ValueError, match="[Pp]riority"):
            apply_editor_edit(storage, 1, _edited(storage, 1, priority=""))
        assert storage.get(1).priority.value == "medium"

    def test_blank_status_line_rejects_edit(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task")
        with pytest.raises(ValueError, match="[Ss]tatus"):
            apply_editor_edit(storage, 1, _edited(storage, 1, status=""))
        assert storage.get(1).status.value == "todo"

    def test_blank_status_does_not_partially_apply(
        self, storage: SqliteStorage
    ) -> None:
        add_todo(storage, "Task")
        buffer = _edited(storage, 1, status="", title="Renamed")
        with pytest.raises(ValueError):
            apply_editor_edit(storage, 1, buffer)
        assert storage.get(1).title == "Task"

    def test_deleted_priority_line_still_leaves_field_unchanged(
        self, storage: SqliteStorage
    ) -> None:
        add_todo(storage, "Task", priority=Priority.HIGH)
        text = "\n".join(
            line
            for line in item_to_editor_text(storage.get(1)).split("\n")
            if not line.startswith("priority:")
        )
        assert apply_editor_edit(storage, 1, text).item.priority == Priority.HIGH
