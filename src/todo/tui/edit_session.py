"""Running $EDITOR on an item's body: the temp buffer, the suspend, the
apply.

What the buffer holds lives in `editor`; this is the part that touches the
terminal and the filesystem. Every failure path reports where the user's
buffer was left — the flow must never strand their work silently.
"""

from __future__ import annotations

import os
import subprocess
import tempfile

from textual.app import SuspendNotSupported
from textual.widget import Widget

from todo.application.contracts.item_store import ItemStore
from todo.domain.item_id import ItemId
from todo.domain.todo_item import TodoItem
from todo.exceptions import TodoError
from todo.tui.editor import apply_body_edit, editor_command
from todo.tui.render import escape_markup


class EditorSession:
    """One $EDITOR round trip, driven by the widget that owns the screen."""

    def __init__(self, view: Widget, items: ItemStore) -> None:
        self._view = view
        self._items = items

    def run(self, item: TodoItem) -> TodoItem | None:
        """Edit an item's body in $EDITOR. Returns the result of a real
        edit, or None if nothing was applied (cancelled, unchanged, or
        failed)."""
        text = item.body
        try:
            tmp_path = self.write_buffer(text)
        except OSError as exc:
            self._error(f"Editor failed: {escape_markup(str(exc))}")
            return None

        if not self._run_editor(tmp_path):
            return None

        edited = self.read_buffer(tmp_path)
        if edited is None:
            return None

        return self.apply(item.id, text, edited, tmp_path)

    def _error(self, message: str, *, timeout: float | None = None) -> None:
        self._view.notify(message, severity="error", timeout=timeout)

    def _run_editor(self, tmp_path: str) -> bool:
        editor = os.environ.get("EDITOR", "vi")
        try:
            with self._view.app.suspend():
                subprocess.run(editor_command(editor, tmp_path), check=True)
        except subprocess.CalledProcessError as exc:
            # The editor RAN and exited nonzero — the user may already have
            # saved their work into the buffer. Keep it and say where.
            self._error(
                f"Editor failed: {escape_markup(str(exc))} — "
                f"your buffer is kept at {escape_markup(tmp_path)}",
                timeout=12,
            )
            return False
        except (
            ValueError,  # empty/misquoted $EDITOR
            OSError,  # missing binary, permission denied, ...
            SuspendNotSupported,
        ) as exc:
            # The editor never ran; the buffer holds nothing of the user's.
            self._error(f"Editor failed: {escape_markup(str(exc))}")
            os.unlink(tmp_path)
            return False
        return True

    def write_buffer(self, text: str) -> str:
        """Write the buffer for $EDITOR, always as UTF-8.

        Explicit encoding, not the locale's: item text is arbitrary Unicode
        and a non-UTF-8 locale would fail to encode it.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".todo.txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(text)
            return f.name

    def read_buffer(self, tmp_path: str) -> str | None:
        """Read the buffer back after the editor ran; on failure, report
        where the (possibly recoverable) buffer lives.

        UnicodeDecodeError (an editor that saved as latin-1/cp1252) is a
        ValueError, not an OSError, and would otherwise kill the session.
        """
        try:
            with open(tmp_path, encoding="utf-8") as f:
                return f.read()
        except (OSError, ValueError) as exc:
            self._error(
                f"Editor failed: {escape_markup(str(exc))} — "
                f"your buffer is kept at {escape_markup(tmp_path)}",
                timeout=12,
            )
            return None

    def apply(
        self, item_id: ItemId, original: str, edited: str, tmp_path: str
    ) -> TodoItem | None:
        """Apply an edited buffer. On rejection the buffer file is kept and
        its path reported, so a failed write never destroys the user's work."""
        # Exact no-op check (plus the editor's final newline): anything
        # else — including whitespace-only body edits — is a real edit.
        if edited in (original, original + "\n"):
            os.unlink(tmp_path)
            return None

        try:
            result = apply_body_edit(self._items, item_id, edited)
        except (ValueError, TodoError) as exc:
            self._error(
                f"Edit rejected: {escape_markup(str(exc))} — "
                f"your buffer is kept at {escape_markup(tmp_path)}",
                timeout=12,
            )
            return None
        os.unlink(tmp_path)
        return result
