"""The $EDITOR round-trip: storing an edited body and surviving failure."""

from __future__ import annotations

from pathlib import Path

import pytest

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import add_todo
from todo.tui.app import TodoApp
from todo.tui.edit_session import EditorSession
from todo.tui.editor import apply_body_edit


class TestApplyBodyEdit:
    """The buffer is the body and nothing else: there is no format to get
    wrong, and no field a body line can reach."""

    def test_edited_buffer_becomes_the_body(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task", body="old")
        result = apply_body_edit(storage, 1, "new body\n")
        assert result.item.body == "new body"

    def test_emptied_buffer_clears_the_body(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task", body="old body")
        assert apply_body_edit(storage, 1, "").item.body == ""

    def test_field_looking_lines_are_body_text(self, storage: SqliteStorage) -> None:
        """'status: done' in the body is prose, never a field override."""
        add_todo(storage, "Task")
        result = apply_body_edit(storage, 1, "status: done\ntitle: Renamed\n")
        assert result.item.status.value == "todo"
        assert result.item.title == "Task"
        assert result.item.body == "status: done\ntitle: Renamed"

    def test_indentation_is_preserved(self, storage: SqliteStorage) -> None:
        add_todo(storage, "Task", body="old")
        edited = "    def f():\n        pass\n"
        assert apply_body_edit(storage, 1, edited).item.body == (
            "    def f():\n        pass"
        )

    def test_only_the_editors_final_newline_is_dropped(
        self, storage: SqliteStorage
    ) -> None:
        add_todo(storage, "Task")
        assert apply_body_edit(storage, 1, "para\n\n\n").item.body == "para\n\n"


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


class TestEditorCommandValidation:
    def test_empty_editor_value_raises(self) -> None:
        from todo.tui.editor import editor_command

        with pytest.raises(ValueError, match="EDITOR"):
            editor_command("", "/tmp/x")

    def test_unbalanced_quote_raises_value_error(self) -> None:
        from todo.tui.editor import editor_command

        with pytest.raises(ValueError):
            editor_command('code "', "/tmp/x")


class TestEditorPathWithSpaces:
    def test_unquoted_spaced_path_falls_back_to_verbatim(self, tmp_path: Path) -> None:
        """An unquoted $EDITOR path containing spaces (common on macOS)
        worked before shlex-splitting existed and must keep working."""
        from todo.tui.editor import editor_command

        editor = tmp_path / "My Editor"
        editor.write_text("#!/bin/sh\nexit 0\n")
        editor.chmod(0o755)
        assert editor_command(str(editor), "/tmp/x") == [str(editor), "/tmp/x"]


class TestApplyEditedBuffer:
    """The post-$EDITOR half, testable without suspend()."""

    async def test_rejected_edit_keeps_buffer_file(
        self, db_path: Path, tmp_path: Path
    ) -> None:
        """The item was deleted while the editor was open: the write fails,
        so the user's typing must stay recoverable on disk."""
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "Task", body="keep me")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            original = storage.get(1).body
            edited = "hours of typing"
            buf = tmp_path / "buffer.todo.txt"
            buf.write_text(edited)

            storage.delete(1)
            EditorSession(view, storage).apply(1, original, edited, str(buf))
            await pilot.pause()

            assert app.is_running
            assert buf.exists()  # user's work is recoverable

    async def test_successful_edit_removes_buffer(
        self, db_path: Path, tmp_path: Path
    ) -> None:
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "Task", body="old")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            original = storage.get(1).body
            edited = "rewritten"
            buf = tmp_path / "buffer.todo.txt"
            buf.write_text(edited)

            EditorSession(view, storage).apply(1, original, edited, str(buf))
            await pilot.pause()
            assert storage.get(1).body == "rewritten"
            assert not buf.exists()


class TestEditorFailureHandling:
    async def test_broken_editor_does_not_crash_tui(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing/broken $EDITOR shows an error instead of tearing down."""
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "Task", body="untouched")
        monkeypatch.setenv("EDITOR", "/nonexistent/editor-binary")

        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            assert EditorSession(view, storage).run(storage.get(1)) is None
            await pilot.pause()
            assert app.is_running
            assert storage.get(1).body == "untouched"


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
            original = storage.get(1).body
            edited = original + "\n\n"  # append a trailing blank line
            buf = tmp_path / "buffer.todo.txt"
            buf.write_text(edited)

            EditorSession(view, storage).apply(1, original, edited, str(buf))
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
            original = item_before.body
            edited = original + "\n"  # only the editor's final newline
            buf = tmp_path / "buffer.todo.txt"
            buf.write_text(edited)

            EditorSession(view, storage).apply(1, original, edited, str(buf))
            await pilot.pause()
            after = storage.get(1)
            assert after.body == "print(x)"
            assert after.updated_at == item_before.updated_at  # true no-op
            assert not buf.exists()


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
            EditorSession(view, storage).run(storage.get(1))
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
            buf.write_bytes("caf\xe9".encode("latin-1"))
            notices: list[str] = []
            view.notify = lambda msg, **kw: notices.append(str(msg))  # type: ignore[method-assign]

            content = EditorSession(view, storage).read_buffer(str(buf))

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
            path = EditorSession(view, storage).write_buffer(storage.get(1).body)
            try:
                assert "emoji 🎉 body" in Path(path).read_text(encoding="utf-8")
                assert EditorSession(view, storage).read_buffer(path) is not None
            finally:
                Path(path).unlink(missing_ok=True)
