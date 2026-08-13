"""Which item this is, and how it is referred to."""

from __future__ import annotations


class ItemId(int):
    """An item's identity.

    An int subclass, so it indexes, compares and binds to SQL exactly as
    the row key it is. What it adds is the reference people read and type
    — `#3` — which was written out as an f-string in a dozen places, none
    of which owned it.

    Identity and reference are the same value here because the row key is
    what the CLI accepts and the table shows. If they ever need to differ
    — a key that survives a rebuild, say — this is the one place that
    changes.
    """

    __slots__ = ()

    def __new__(cls, value: int) -> ItemId:
        if value < 1:
            raise ValueError(f"Item id must be positive, not {value}.")
        return super().__new__(cls, value)

    @property
    def label(self) -> str:
        """How the item is named on screen and on the command line."""
        return f"#{int(self)}"
