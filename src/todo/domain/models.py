from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from todo.domain.enums import Priority, Status


@dataclass(frozen=True)
class TodoItem:
    id: int
    title: str
    body: str
    priority: Priority
    status: Status
    created_at: datetime
    updated_at: datetime
    done_at: datetime | None
    deadline: date | None
    tags: list[str]
    blocked_by: list[int] = field(default_factory=list)
    blocking: list[int] = field(default_factory=list)
    is_blocked: bool = False

    @property
    def is_done(self) -> bool:
        return self.status == Status.DONE

    @property
    def is_overdue(self) -> bool:
        if self.deadline is None or self.is_done:
            return False
        return date.today() > self.deadline

    @property
    def days_until_deadline(self) -> int | None:
        if self.deadline is None:
            return None
        return (self.deadline - date.today()).days

    @property
    def deadline_urgent(self) -> bool:
        days = self.days_until_deadline
        if days is None or self.is_done:
            return False
        return days <= 3
