from __future__ import annotations

from enum import Enum


class Priority(Enum):
    URGENT = "urgent"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def from_string(cls, value: str) -> Priority:
        try:
            return cls(value.lower())
        except ValueError:
            valid = ", ".join(p.value for p in cls)
            raise ValueError(f"Invalid priority '{value}'. Must be one of: {valid}")


class ProjectStatus(Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"

    @classmethod
    def from_string(cls, value: str) -> ProjectStatus:
        try:
            return cls(value.lower())
        except ValueError:
            valid = ", ".join(s.value for s in cls)
            raise ValueError(
                f"Invalid project status '{value}'. Must be one of: {valid}"
            )


_STATUS_ORDER: list[str] = ["backlog", "todo", "in-progress", "done"]


class Status(Enum):
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

    @classmethod
    def active_statuses(cls) -> list[Status]:
        return [cls.BACKLOG, cls.TODO, cls.IN_PROGRESS]

    def next(self) -> Status | None:
        order = [Status.BACKLOG, Status.TODO, Status.IN_PROGRESS, Status.DONE]
        idx = order.index(self)
        if idx < len(order) - 1:
            return order[idx + 1]
        return None

    def prev(self) -> Status | None:
        order = [Status.BACKLOG, Status.TODO, Status.IN_PROGRESS, Status.DONE]
        idx = order.index(self)
        if idx > 0:
            return order[idx - 1]
        return None
