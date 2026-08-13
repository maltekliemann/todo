"""Every tag that exists, with how many items use it."""

from __future__ import annotations

from dataclasses import dataclass

from todo.application.contracts.item_store import ItemStore
from todo.domain.tag import Tag


@dataclass(frozen=True)
class TagCount:
    """A tag, and how many items carry it."""

    tag: Tag
    count: int


class ListTags:
    def __init__(self, items: ItemStore) -> None:
        self._items = items

    def execute(self) -> list[TagCount]:
        """Most used first, then alphabetically. Done items count: a tag
        does not stop existing because the work under it is finished."""
        counts: dict[Tag, int] = {}
        for tags in self._items.tags_of_every_item():
            for tag in tags:
                counts[tag] = counts.get(tag, 0) + 1
        return [
            TagCount(tag=tag, count=count)
            for tag, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
