"""One line of a project's log."""

from __future__ import annotations


class UpdateBody(str):
    """A single-line, non-empty log entry.

    Entries render as one timestamped row, and an empty one leaves a
    dangling timestamp with nothing to say and no way to remove it.

    Guards what is written, not what is read: rows predating the rule
    (3f6395d) may hold an empty body, and refusing to load them would lock
    someone out of their own log.
    """

    __slots__ = ()

    def __new__(cls, value: str) -> UpdateBody:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Update body cannot be empty.")
        return super().__new__(cls, normalized)
