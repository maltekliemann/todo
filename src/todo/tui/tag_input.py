"""Reading tags out of a text field.

The TUI offers one box and splits it on commas; the CLI takes repeated
--tag flags and splits nothing. That makes this a convention of this
interface, not a rule about tags.
"""

from __future__ import annotations

from todo.domain.tag import Tag


def parse_tag_input(value: str) -> list[Tag]:
    """Comma-separated field text into tags, blanks dropped."""
    return [Tag(piece) for piece in value.split(",") if piece.strip()]
