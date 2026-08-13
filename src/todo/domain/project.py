"""A named grouping of items."""

from __future__ import annotations

from datetime import datetime, timezone

from todo.domain.description import Description
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class Project:
    """A project, and everything that may be done to it.

    Same shape as TodoItem: state is private and readable, changes go
    through methods, and `updated_at` has no setter because it moves when
    something else does.

    Archived is a flag, not a status: there is no third thing a project
    can be, and nothing branches on it except "show this one or not".
    """

    __slots__ = (
        "_id",
        "_name",
        "_description",
        "_archived",
        "_created_at",
        "_updated_at",
    )

    def __init__(
        self,
        *,
        id: ProjectId,
        name: ProjectName,
        description: Description,
        created_at: datetime,
        updated_at: datetime,
        archived: bool = False,
    ) -> None:
        self._id = id
        self._name = name
        self._description = description
        self._archived = archived
        self._created_at = created_at
        self._updated_at = updated_at

    @property
    def id(self) -> ProjectId:
        return self._id

    @property
    def name(self) -> ProjectName:
        return self._name

    @property
    def description(self) -> Description:
        return self._description

    @property
    def archived(self) -> bool:
        return self._archived

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    def set_name(self, name: ProjectName) -> None:
        self._name = name
        self._touch()

    def set_description(self, description: Description) -> None:
        self._description = description
        self._touch()

    def archive(self) -> None:
        """Idempotent: an archived project is already archived."""
        self._archived = True
        self._touch()

    def unarchive(self) -> None:
        self._archived = False
        self._touch()

    def _touch(self) -> None:
        self._updated_at = _now()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Project) and other._id == self._id

    def __hash__(self) -> int:
        return hash(self._id)

    def __repr__(self) -> str:
        return f"Project({self._id.label} {self._name!r})"
