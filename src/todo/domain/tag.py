"""A label on an item, and the rules for a comma-joined set of them."""

from __future__ import annotations

from collections.abc import Iterable

from todo.domain.text import single_line


class Tag(str):
    """A single-line, non-empty, comma-free label.

    The comma rule is not taste: tags are stored comma-joined, so a tag
    containing one cannot round-trip — it would come back as two phantom
    tags. Rejecting it is the only way to keep the stored form and the
    parsed form the same.
    """

    __slots__ = ()

    def __new__(cls, value: str) -> Tag:
        normalized = single_line(value)
        if not normalized:
            raise ValueError("Tag cannot be empty.")
        if "," in normalized:
            raise ValueError(f"Tag '{normalized}' contains a comma; use separate tags.")
        return super().__new__(cls, normalized)


def split_tags(raw: str) -> list[str]:
    """Comma-separated string -> stripped, non-empty pieces (order kept).

    Returns plain strings: this is parsing, and the caller decides whether
    the pieces are being read back from storage or accepted as input.
    """
    return [tag for tag in (segment.strip() for segment in raw.split(",")) if tag]


def dedupe_tags(tags: Iterable[str]) -> list[str]:
    """Drop duplicates, preserving first-seen order."""
    seen: list[str] = []
    for tag in tags:
        if tag not in seen:
            seen.append(tag)
    return seen
