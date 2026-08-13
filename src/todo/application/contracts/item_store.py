"""Where items are kept.

What the application needs of an item store, said in the domain's own
words. Nothing here knows that the other side is a database, a file, or
a service: no transactions, no connections, no column names.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from todo.domain.item_filter import ItemFilter
from todo.domain.item_id import ItemId
from todo.domain.moment import Moment
from todo.domain.project_id import ProjectId
from todo.domain.tag import Tag
from todo.domain.todo_item import TodoItem


@dataclass(frozen=True)
class ItemCounts:
    """How many items, split by whether they are finished."""

    open: int
    done: int


class ItemStore(Protocol):
    """Items go in and come out whole. Every call is atomic in itself.

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

    def create(self, item: TodoItem) -> None:
        """Keep an item that was not there before, identity included."""
        ...

    def get(self, item_id: ItemId) -> TodoItem:
        """The item, or NotFoundError."""
        ...

    def exists(self, item_id: ItemId) -> bool:
        """Whether there is such an item — for callers that only need to
        know, and should not pay for the whole thing to find out."""
        ...

    def save(self, item: TodoItem) -> TodoItem:
        """Keep the item as it now stands, and hand back what was kept.

        No field list and no clearing sentinel: the caller changed the
        item through its own methods, so what is stored is what it holds.
        """
        ...

    def delete(self, item_id: ItemId) -> None:
        """Forget the item. Only the item: the dependencies that named it
        are the graph's, and go when the graph is next saved."""
        ...

    def find(self, item_filter: ItemFilter) -> list[TodoItem]:
        """Every item the filter describes, in the order items are shown."""
        ...

    def done_since(self, moment: Moment) -> list[TodoItem]:
        """Items finished since then, most recently finished first."""
        ...

    def done_ids(self) -> frozenset[ItemId]:
        """Which items are finished — half of what decides blocked-ness,
        and far less than loading them all to ask."""
        ...

    def tags_of_every_item(self) -> list[frozenset[Tag]]:
        """One tag set per item, for counting tags across all of them."""
        ...

    def unassign_project(self, project_id: ProjectId) -> None:
        """File every item under that project under nothing instead.

        Deleting a project does not delete its items, but no item may go
        on naming a project that is gone.
        """
        ...

    def counts_by_project(self) -> dict[ProjectId, ItemCounts]:
        """How many items each project has. Items are counted here
        because they are items, whoever wants the number."""
        ...
