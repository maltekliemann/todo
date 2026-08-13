"""A todo item."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from todo.domain.deadline import Deadline
from todo.domain.priority import Priority
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.title import Title


@dataclass(frozen=True)
class TodoItem:
    """One item, and the facts derived from its own fields.

    `blocked_by`, `blocking` and `is_blocked` are read projections of the
    DependencyGraph, filled in on read. They are not state: nothing writes
    through them, because a dependency is not a property of either item it
    joins. Change one through the graph.
    """

    id: int
    title: Title
    body: str
    priority: Priority
    status: Status
    created_at: datetime
    updated_at: datetime
    done_at: datetime | None
    deadline: Deadline | None
    tags: list[Tag]
    blocked_by: list[int] = field(default_factory=list)
    blocking: list[int] = field(default_factory=list)
    is_blocked: bool = False
    project_id: int | None = None
    project_name: str | None = None

    @property
    def is_done(self) -> bool:
        return self.status == Status.DONE

    @property
    def is_overdue(self) -> bool:
        # The date knows whether it has passed; only the item knows whether
        # that still matters.
        if self.deadline is None or self.is_done:
            return False
        return self.deadline.has_passed

    @property
    def days_until_deadline(self) -> int | None:
        if self.deadline is None:
            return None
        return self.deadline.days_until

    @property
    def deadline_urgent(self) -> bool:
        days = self.days_until_deadline
        if days is None or self.is_done:
            return False
        return days <= 3
