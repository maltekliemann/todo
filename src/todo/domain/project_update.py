"""One entry in a project's append-only log."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ProjectUpdate:
    id: int
    project_id: int
    body: str
    created_at: datetime
