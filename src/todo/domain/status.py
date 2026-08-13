"""Where an item is in the workflow, and what comes next."""

from __future__ import annotations

from enum import Enum


class Status(Enum):
    """The workflow, in order. Declaration order is that order: next and
    previous read it rather than repeating it."""

    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in-progress"
    DONE = "done"

    @classmethod
    def from_string(cls, value: str) -> Status:
        try:
            return cls(value.lower())
        except ValueError:
            valid = ", ".join(s.value for s in cls)
            raise ValueError(f"Invalid status '{value}'. Must be one of: {valid}")

    @property
    def done(self) -> bool:
        return self is Status.DONE

    @property
    def active(self) -> bool:
        """Still being worked on — everything that is not finished."""
        return not self.done

    def next(self) -> Status | None:
        """The step forward, or None at the end of the workflow."""
        order = list(Status)
        index = order.index(self) + 1
        return order[index] if index < len(order) else None

    def prev(self) -> Status | None:
        """The step back, or None at the start of the workflow."""
        index = list(Status).index(self) - 1
        return list(Status)[index] if index >= 0 else None
