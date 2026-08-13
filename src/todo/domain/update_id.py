"""Which log entry this is."""

from __future__ import annotations


class UpdateId(int):
    """A project log entry's identity."""

    __slots__ = ()

    @property
    def label(self) -> str:
        return f"#{int(self)}"
