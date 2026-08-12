"""The $EDITOR protocol: rendering an item to a text buffer, parsing an
edited buffer back, and applying it.

Pure text handling plus one application call — no widgets, so it is
testable without a terminal.
"""

from __future__ import annotations

import shlex
import shutil
from datetime import date

from todo.application.commands import CompletionResult, edit_todo
from todo.application.contracts.storage import UNSET, StorageProtocol, Unset
from todo.domain.enums import Priority, Status
from todo.domain.models import TodoItem
from todo.domain.tags import split_tags


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


def item_to_editor_text(item: TodoItem) -> str:
    return (
        f"title: {item.title}\n"
        f"priority: {item.priority.value}\n"
        f"status: {item.status.value}\n"
        f"deadline: {item.deadline.isoformat() if item.deadline else ''}\n"
        f"tags: {', '.join(item.tags)}\n"
        f"\n"
        f"# Body (everything below this line is the body):\n"
        f"{item.body}"
    )


def apply_editor_edit(
    storage: StorageProtocol, item_id: int, edited: str
) -> CompletionResult:
    """Parse an edited $EDITOR buffer and apply it to the item.

    A field line that is present but empty clears that field (deadline,
    tags); a field line the user deleted entirely leaves the field
    unchanged. The '# Body' marker is required (ValueError otherwise).
    """
    fields = parse_editor_text(edited)

    deadline_val: date | None | Unset = UNSET
    if "deadline" in fields:
        dl_str = fields["deadline"]
        if dl_str == "":
            deadline_val = None
        else:
            try:
                deadline_val = date.fromisoformat(dl_str)
            except ValueError:
                # Same contract as the CLI: bad input errors, never a
                # silent no-op.
                raise ValueError(
                    f"Invalid deadline '{dl_str}'. Use YYYY-MM-DD."
                ) from None

    tags: list[str] | None = None
    if "tags" in fields:
        tags = split_tags(fields["tags"])

    if "title" in fields and not fields["title"].strip():
        # Same contract as deadline: bad input errors, never a partial apply.
        raise ValueError("Title cannot be empty.")

    # A blanked enum line is bad input, not an absent field. Deleting the
    # whole line still means "leave unchanged"; blanking the value used to
    # be a silent no-op that deleted the user's buffer.
    for name in ("priority", "status"):
        if name in fields and not fields[name].strip():
            raise ValueError(
                f"{name.capitalize()} cannot be empty — delete the whole "
                f"'{name}:' line to leave it unchanged."
            )

    # The body is compared against the stored one so an untouched body is
    # never rewritten (editors append a final newline on save; that alone
    # is not an edit). Only a genuinely edited body drops the single
    # trailing newline the editor's save added.
    body: str | None = None
    parsed_body = fields["body"]
    current_body = storage.get(item_id).body
    if parsed_body not in (current_body, current_body + "\n"):
        body = parsed_body.removesuffix("\n")

    return edit_todo(
        storage,
        item_id,
        title=fields.get("title") or None,
        body=body,
        priority=(
            Priority.from_string(fields["priority"]) if fields.get("priority") else None
        ),
        status=(Status.from_string(fields["status"]) if fields.get("status") else None),
        deadline=deadline_val,
        tags=tags,
    )


def parse_editor_text(text: str) -> dict[str, str]:
    lines = text.split("\n")
    fields: dict[str, str] = {}
    body_lines: list[str] = []
    in_body = False
    for line in lines:
        if in_body:
            body_lines.append(line)
            continue
        if line.startswith("# Body"):
            in_body = True
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip().lower()
            if key in ("title", "priority", "status", "deadline", "tags"):
                fields[key] = value.strip()
    # The marker is required. Without it there is no way to tell fields
    # from body text: the user's body edits would be silently discarded
    # and body lines like 'status: done' would override real fields.
    # Bad input errors (buffer kept upstream) — never a silent no-op.
    if not in_body:
        raise ValueError(
            "The '# Body' marker line is missing — restore it so your "
            "body edits can be applied."
        )
    # The body is kept verbatim — whitespace is content (pasted code).
    fields["body"] = "\n".join(body_lines)
    return fields
