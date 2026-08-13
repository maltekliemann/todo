"""A todo item."""

from __future__ import annotations

from datetime import datetime, timezone

from todo.domain.body import Body
from todo.domain.deadline import Deadline
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.title import Title


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class TodoItem:
    """One item, and everything that may be done to it.

    State is private and readable, never assignable. Where a change is
    only a change, the setter says so; where it carries a rule, the method
    is named for the act — move_to decides the completion stamp. There is
    no setter for `updated_at` at all: it moves because something else
    did, which is the only thing it means.

    Dependencies are not here. An edge belongs to neither item it joins,
    so what this waits on, what waits on it, and whether it is held up are
    the graph's — see application.dependencies.Dependencies.
    """

    __slots__ = (
        "_id",
        "_title",
        "_body",
        "_priority",
        "_status",
        "_created_at",
        "_updated_at",
        "_done_at",
        "_deadline",
        "_tags",
        "_project",
    )

    def __init__(
        self,
        *,
        id: ItemId,
        title: Title,
        body: Body,
        priority: Priority,
        status: Status,
        created_at: datetime,
        updated_at: datetime,
        done_at: datetime | None = None,
        deadline: Deadline | None = None,
        tags: frozenset[Tag] = frozenset(),
        project: Project | None = None,
    ) -> None:
        self._id = id
        self._title = title
        self._body = body
        self._priority = priority
        self._status = status
        self._created_at = created_at
        self._updated_at = updated_at
        self._done_at = done_at
        self._deadline = deadline
        self._tags = frozenset(tags)
        self._project = project

    # --- what it is -----------------------------------------------------

    @property
    def id(self) -> ItemId:
        return self._id

    @property
    def title(self) -> Title:
        return self._title

    @property
    def body(self) -> Body:
        return self._body

    @property
    def priority(self) -> Priority:
        return self._priority

    @property
    def status(self) -> Status:
        return self._status

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @property
    def done_at(self) -> datetime | None:
        return self._done_at

    @property
    def deadline(self) -> Deadline | None:
        return self._deadline

    @property
    def tags(self) -> frozenset[Tag]:
        """A set, because a tag is either on an item or it is not."""
        return self._tags

    @property
    def project(self) -> Project | None:
        return self._project

    # --- what may be done to it -----------------------------------------

    def set_title(self, title: Title) -> None:
        self._title = title
        self._touch()

    def set_body(self, body: Body) -> None:
        self._body = body
        self._touch()

    def set_priority(self, priority: Priority) -> None:
        self._priority = priority
        self._touch()

    def move_to(self, status: Status) -> None:
        """Move through the workflow, with the stamp the move implies.

        Finishing records when; taking it back out of done withdraws the
        claim that it was ever finished. Arriving at done a second time
        keeps the first stamp, because the second move finished nothing.
        """
        if status is Status.DONE:
            self._done_at = self._done_at if self.is_done and self._done_at else _now()
        else:
            self._done_at = None
        self._status = status
        self._touch()

    def set_deadline(self, deadline: Deadline | None) -> None:
        """Give it a due date, or None for none.

        A date in the past is allowed: recording that something was due
        last week is a thing people do.
        """
        self._deadline = deadline
        self._touch()

    def add_tag(self, tag: Tag) -> None:
        """Idempotent: a tag is on the item or it is not."""
        self._tags = self._tags | {tag}
        self._touch()

    def remove_tag(self, tag: Tag) -> None:
        """Idempotent in the other direction: removing an absent tag is
        not an error, it is already the case."""
        self._tags = self._tags - {tag}
        self._touch()

    def set_project(self, project: Project | None) -> None:
        """File it under a project, or None for none."""
        self._project = project
        self._touch()

    def _touch(self) -> None:
        self._updated_at = _now()

    # --- what follows from it -------------------------------------------

    @property
    def is_done(self) -> bool:
        return self._status is Status.DONE

    @property
    def is_overdue(self) -> bool:
        # The date knows whether it has passed; only the item knows whether
        # that still matters.
        if self._deadline is None or self.is_done:
            return False
        return self._deadline.has_passed

    @property
    def days_until_deadline(self) -> int | None:
        if self._deadline is None:
            return None
        return self._deadline.days_until

    @property
    def deadline_urgent(self) -> bool:
        days = self.days_until_deadline
        if days is None or self.is_done:
            return False
        return days <= 3

    # --- identity --------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        """Two items are the same item if they have the same id. An entity
        is not its current field values."""
        return isinstance(other, TodoItem) and other._id == self._id

    def __hash__(self) -> int:
        return hash(self._id)

    def __repr__(self) -> str:
        return f"TodoItem({self._id.label} {self._title!r} {self._status.value})"
