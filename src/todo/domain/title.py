"""The name of an item: one line, never empty."""

from __future__ import annotations


class Title(str):
    """A single-line, non-empty title.

    A str subclass, so everything that formats, compares or slices a title
    keeps working unchanged; what the type adds is that an invalid one
    cannot be constructed, and therefore cannot be stored.

    Whitespace is collapsed rather than rejected — every storage and render
    format (table rows, plain output, the item menu) relies on a title
    being one line, and a pasted two-line title is a formatting accident,
    not something to refuse.
    """

    __slots__ = ()

    def __new__(cls, value: str) -> Title:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Title cannot be empty.")
        return super().__new__(cls, normalized)
