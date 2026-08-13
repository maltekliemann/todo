"""A todo item."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from todo.domain.body import Body
from todo.domain.deadline import Deadline
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.title import Title


@dataclass(frozen=True)
class TodoItem:
    """One item, and the facts derived from its own fields.

    Dependencies are not here. An edge belongs to neither item it joins,
    so what this waits on, what waits on it, and whether it is held up are
    answered by the graph — see application.dependencies.Dependencies.
    """

    id: ItemId
    title: Title
    body: Body
    priority: Priority
    status: Status
    created_at: datetime
    updated_at: datetime
    done_at: datetime | None
    deadline: Deadline | None
    tags: list[Tag]
    project: Project | None = None

    def __post_init__(self) -> None:
        # The rule ranges over one item's tags, and the item has them, so
        # this is where it belongs. Whatever builds a TodoItem dedupes on
        # the way in — the same contract as Title: normalized, or not
        # built at all.
        seen: set[str] = set()
        for tag in self.tags:
            if tag in seen:
                raise ValueError(f"Tag '{tag}' is repeated.")
            seen.add(tag)

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
