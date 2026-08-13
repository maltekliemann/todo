"""One entry in a project's log."""

from __future__ import annotations

from datetime import datetime

from todo.domain.project_id import ProjectId
from todo.domain.update_body import UpdateBody
from todo.domain.update_id import UpdateId


class ProjectUpdate:
    """A thing that was written down at a time.

    State is private and readable, and there is nothing to set: a log
    entry records what was true when it was written. Changing one would
    make it a different entry, which is what writing another is for.
    """

    __slots__ = ("_id", "_project_id", "_body", "_created_at")

    def __init__(
        self,
        *,
        id: UpdateId,
        project_id: ProjectId,
        body: UpdateBody,
        created_at: datetime,
    ) -> None:
        self._id = id
        self._project_id = project_id
        self._body = body
        self._created_at = created_at

    @property
    def id(self) -> UpdateId:
        return self._id

    @property
    def project_id(self) -> ProjectId:
        return self._project_id

    @property
    def body(self) -> UpdateBody:
        return self._body

    @property
    def created_at(self) -> datetime:
        return self._created_at

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ProjectUpdate) and other._id == self._id

    def __hash__(self) -> int:
        return hash(self._id)

    def __repr__(self) -> str:
        return f"ProjectUpdate({self._id.label} {self._body!r})"
