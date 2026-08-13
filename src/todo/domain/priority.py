"""How urgent an item is."""

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
