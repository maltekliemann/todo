"""A label on an item."""

from __future__ import annotations


class Tag(str):
    """A single-line, non-empty label.

    Whitespace runs collapse to single spaces, so a tag is the same tag
    however it was typed. That is the whole of it: what a tag may contain
    is not a question anything outside the domain gets a say in.
    """

    __slots__ = ()

    def __new__(cls, value: str) -> Tag:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Tag cannot be empty.")
        return super().__new__(cls, normalized)
