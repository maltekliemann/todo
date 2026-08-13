"""A named grouping of items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from todo.domain.project_status import ProjectStatus


@dataclass(frozen=True)
class Project:
    id: int
    name: str
    description: str
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime

    @property
    def is_archived(self) -> bool:
        return self.status == ProjectStatus.ARCHIVED
