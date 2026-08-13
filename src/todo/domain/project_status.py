"""Whether a project is still being worked on."""

from __future__ import annotations

from enum import Enum


class ProjectStatus(Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
