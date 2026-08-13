"""A label on an item."""

from __future__ import annotations


class Tag(str):
    """A single-line, non-empty, comma-free label.

    The comma rule is not taste: tags are stored comma-joined, so a tag
    containing one cannot round-trip — it would come back as two phantom
    tags. Rejecting it is the only way to keep the stored form and the
    parsed form the same.
    """

    __slots__ = ()

    def __new__(cls, value: str) -> Tag:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Tag cannot be empty.")
        if "," in normalized:
            raise ValueError(f"Tag '{normalized}' contains a comma; use separate tags.")
        return super().__new__(cls, normalized)
