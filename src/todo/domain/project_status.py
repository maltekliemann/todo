"""Where a project is in its life."""

from __future__ import annotations

from enum import Enum


class ProjectStatus(Enum):
    """A project's own state, in order. Declaration order is that order.

    Cancelled and done are both endings — one abandoned, one finished —
    and they are the two that stop a project being current.
    """

    NOT_STARTED = "not-started"
    IN_PROGRESS = "in-progress"
    CANCELLED = "cancelled"
    DONE = "done"

    @classmethod
    def from_string(cls, value: str) -> ProjectStatus:
        try:
            return cls(value.lower())
        except ValueError:
            valid = ", ".join(s.value for s in cls)
            raise ValueError(
                f"Invalid project status '{value}'. Must be one of: {valid}"
            )

    @property
    def ended(self) -> bool:
        """Finished or abandoned: either way, nothing more happens here."""
        return self in (ProjectStatus.CANCELLED, ProjectStatus.DONE)

    @property
    def current(self) -> bool:
        return not self.ended
