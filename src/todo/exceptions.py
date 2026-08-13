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


class ProjectNotFoundError(TodoError):
    def __init__(self, ref: int | str) -> None:
        label = f"#{ref}" if isinstance(ref, int) else f"'{ref}'"
        super().__init__(f"Project {label} not found")
        self.ref = ref


class DuplicateProjectError(TodoError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Project '{name}' already exists")
        self.name = name


class UpdateNotFoundError(TodoError):
    """Raised when a project log entry is not found."""

    def __init__(self, update_id: int) -> None:
        super().__init__(f"Log entry #{update_id} not found")
        self.update_id = update_id
