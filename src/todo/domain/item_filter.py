"""Which items are being asked for.

Every field is a domain value, and a field left alone means "any". One
value rather than a handful of arguments, so asking for items does not
grow a parameter every time there is a new way to narrow them.
"""

from __future__ import annotations

from dataclasses import dataclass

from todo.domain.priority import Priority
from todo.domain.project_id import ProjectId
from todo.domain.status import Status
from todo.domain.tag import Tag


@dataclass(frozen=True)
class ItemFilter:
    status: Status | None = None
    priority: Priority | None = None
    tags: frozenset[Tag] = frozenset()
    text: str | None = None
    project_id: ProjectId | None = None
    include_done: bool = False
