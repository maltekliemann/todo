"""The $EDITOR protocol: what goes into the buffer and what comes back.

The buffer is the body and nothing else. Every other field is edited in
the item menu, so there is no format here to get wrong: whatever you save
is the body.

Pure text handling plus one application call — no widgets, so it is
testable without a terminal.
"""

from __future__ import annotations

import shlex
import shutil

from todo.application.commands import CompletionResult, edit_todo
from todo.application.contracts.storage import StorageProtocol


def editor_command(editor_value: str, path: str) -> list[str]:
    """Split $EDITOR like git does, so values such as 'code --wait' work.

    An unquoted path containing spaces (common on macOS) is not a command
    plus arguments: when the split head doesn't resolve to an executable
    but the verbatim value does, the verbatim value wins — that form
    worked before splitting existed and must keep working.

    Raises ValueError for an empty value or unbalanced quoting rather than
    letting subprocess execute something nonsensical.
    """
    parts = shlex.split(editor_value)  # raises ValueError on bad quoting
    if not parts:
        raise ValueError("EDITOR is empty.")
    if (
        len(parts) > 1
        and shutil.which(parts[0]) is None
        and shutil.which(editor_value) is not None
    ):
        return [editor_value, path]
    return [*parts, path]


def apply_body_edit(
    storage: StorageProtocol, item_id: int, edited: str
) -> CompletionResult:
    """Store an edited buffer as the item's body.

    The single trailing newline an editor adds on save is dropped; deeper
    whitespace is content (pasted code) and is kept verbatim. A buffer
    saved empty clears the body, which is the only way to say so.
    """
    return edit_todo(storage, item_id, body=edited.removesuffix("\n"))
