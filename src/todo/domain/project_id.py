"""Which project this is, and how it is referred to."""

from __future__ import annotations


class ProjectId(int):
    """A project's identity, and the `#3` form the listings show."""

    __slots__ = ()

    def __new__(cls, value: int) -> ProjectId:
        if value < 1:
            raise ValueError(f"Project id must be positive, not {value}.")
        return super().__new__(cls, value)

    @property
    def label(self) -> str:
        return f"#{int(self)}"
