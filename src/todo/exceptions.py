from __future__ import annotations


class TodoError(Exception):
    """Base exception for the todo application."""


class StorageError(TodoError):
    """Raised when a storage operation fails."""


class NotFoundError(TodoError):
    """Raised when a todo item is not found."""

    def __init__(self, item_id: int) -> None:
        super().__init__(f"Todo item #{item_id} not found")
        self.item_id = item_id


class DependencyError(TodoError):
    """Raised for invalid blocking relations (self-block, cycle)."""
