"""The view's filter state: what is selected, how it cycles, how it reads.

Plain data plus pure transitions — exercisable without a terminal or a
database.
"""

from __future__ import annotations

from dataclasses import dataclass

from todo.domain.priority import Priority
from todo.domain.todo_item import TodoItem
from todo.tui.render import escape_markup


@dataclass
class Filters:
    """Search, tag and priority, as the list view holds them."""

    search: str = ""
    tag: str | None = None
    priority: Priority | None = None

    def any_active(self) -> bool:
        return bool(self.search or self.tag or self.priority)

    def clear(self) -> None:
        self.search = ""
        self.tag = None
        self.priority = None

    def apply_search(self, items: list[TodoItem]) -> list[TodoItem]:
        """Filter by the search query.

        This one stays out of SQL because it also matches tag names, which
        storage-level search (title/body) does not cover. casefold, matching
        the storage layer's SQL search semantics.
        """
        if not self.search:
            return items
        q = self.search.casefold()
        return [
            i
            for i in items
            if q in i.title.casefold()
            or q in i.body.casefold()
            or any(q in t.casefold() for t in i.tags)
        ]

    def cycle_tag(self, tags: list[str]) -> None:
        """No filter -> each known tag in turn -> no filter."""
        if not tags:
            return
        if self.tag is None:
            self.tag = tags[0]
            return
        try:
            idx = tags.index(self.tag)
        except ValueError:
            idx = -1
        self.tag = tags[idx + 1] if idx + 1 < len(tags) else None

    def toggle_priority(self, priority: Priority) -> None:
        """Pressing the same priority key again clears the filter."""
        self.priority = None if self.priority == priority else priority

    def status_parts(self) -> list[str]:
        """The active filters, as markup for the status line."""
        parts: list[str] = []
        if self.search:
            parts.append(f"[dim]Search:[/dim] [b]{escape_markup(self.search)}[/b]")
        if self.tag is not None:
            parts.append(f"[dim]Tag:[/dim] [b]{escape_markup(self.tag)}[/b]")
        if self.priority is not None:
            parts.append(f"[dim]Priority:[/dim] [b]{self.priority.value}[/b]")
        return parts
