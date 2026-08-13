"""A named grouping of items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from todo.domain.description import Description
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName
from todo.domain.project_status import ProjectStatus


@dataclass(frozen=True)
class Project:
    id: ProjectId
    name: ProjectName
    description: Description
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime

    @property
    def is_archived(self) -> bool:
        return self.status == ProjectStatus.ARCHIVED
