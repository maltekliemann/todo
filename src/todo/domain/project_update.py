"""One entry in a project's append-only log."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from todo.domain.project_id import ProjectId


@dataclass(frozen=True)
class ProjectUpdate:
    id: int
    project_id: ProjectId
    body: str
    created_at: datetime
