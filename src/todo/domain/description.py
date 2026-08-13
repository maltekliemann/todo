"""What a project is for, in one line."""

from __future__ import annotations


class Description(str):
    """A single-line project description; empty is allowed.

    It renders inside the one-row-per-project listing, which is the whole
    of the rule: no newlines. Having none to show is not a problem.
    """

    __slots__ = ()

    def __new__(cls, value: str) -> Description:
        return super().__new__(cls, " ".join(value.split()))
