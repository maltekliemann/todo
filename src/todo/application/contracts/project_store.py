"""Where projects are kept."""

from __future__ import annotations

from typing import Protocol

from todo.domain.description import Description
from todo.domain.project import Project
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName


class ProjectStore(Protocol):
    """Projects go in and come out whole. Every call is atomic in itself.

    Reading and writing are not serialized against each other. A caller
    reads, changes what it read, and writes it back, and nothing stops a
    second writer landing between those two calls — there is no version
    to check and no lock to hold, because holding one would mean the
    application asking for a transaction, which is not a word it has.

    So a second writer inside that window wins outright: the fields it
    never read are overwritten with what it read a moment ago, and
    neither caller is told. This is a decision, not an oversight. Every
    command re-reads immediately before it writes, so the window is one
    call wide — microseconds, in a program run one invocation at a time
    by one person. Versioning every aggregate and retrying every write is
    a great deal of machinery to point at that.

    It stops being a decision the moment anything writes concurrently on
    purpose: a daemon, a sync process, a second user. Then the aggregates
    need versions and the writes need to refuse a stale one.
    """

    def create(self, name: ProjectName, description: Description) -> Project:
        """Give a project an identity and keep it. The store decides the
        id, and refuses a name another project already has."""
        ...

    def get(self, project_id: ProjectId) -> Project:
        """The project, or ProjectNotFoundError."""
        ...

    def get_by_name(self, name: ProjectName) -> Project:
        """The project with that exact name, or ProjectNotFoundError."""
        ...

    def save(self, project: Project) -> Project:
        """Keep the project as it now stands, and hand back what was kept."""
        ...

    def delete(self, project_id: ProjectId) -> None:
        """Forget the project. Only the project: what its disappearance
        means for items and for its log is decided above, not here."""
        ...

    def find_all(self, *, include_ended: bool = False) -> list[Project]:
        """Every project by name; the cancelled and the done only if asked."""
        ...
