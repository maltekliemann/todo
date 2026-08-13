"""Which project this is, and how it is referred to."""

from __future__ import annotations


class ProjectId(int):
    """A project's identity, and the `#3` form the listings show."""

    __slots__ = ()

    @property
    def label(self) -> str:
        return f"#{int(self)}"
