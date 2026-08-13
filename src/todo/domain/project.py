"""A named grouping of items."""

from __future__ import annotations

from datetime import datetime, timezone

from todo.domain.description import Description
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName
from todo.domain.project_status import ProjectStatus


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class Project:
    """A project, and everything that may be done to it.

    Same shape as TodoItem: state is private and readable, changes go
    through methods, and `updated_at` has no setter because it moves when
    something else does.

    A project has a life of its own — not started, in progress, cancelled,
    done — which is not the same question as whether its items are
    finished.
    """

    __slots__ = (
        "_id",
        "_name",
        "_description",
        "_status",
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
        status: ProjectStatus = ProjectStatus.NOT_STARTED,
    ) -> None:
        self._id = id
        self._name = name
        self._description = description
        self._status = status
        if updated_at < created_at:
            raise ValueError(
                f"An project cannot have been updated before it existed: "
                f"{updated_at.isoformat()} < {created_at.isoformat()}."
            )
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
    def status(self) -> ProjectStatus:
        return self._status

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

    def set_status(self, status: ProjectStatus) -> None:
        self._status = status
        self._touch()

    def _touch(self) -> None:
        # Never backwards: a clock that jumps must not make this look
        # older than the change that already happened to it.
        self._updated_at = max(_now(), self._updated_at)

    @property
    def ended(self) -> bool:
        """Cancelled or done — the two that stop it being current."""
        return self._status.ended

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Project) and other._id == self._id

    def __hash__(self) -> int:
        return hash(self._id)

    def __repr__(self) -> str:
        return f"Project({self._id.label} {self._name!r})"
