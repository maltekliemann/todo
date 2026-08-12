"""The view's filter state: what is selected, how it cycles, how it reads.

Plain data plus pure transitions — exercisable without a terminal or a
database.
"""

from __future__ import annotations

from dataclasses import dataclass

from todo.domain.enums import Priority
from todo.domain.models import Project, TodoItem
from todo.tui.render import escape_markup


@dataclass
class Filters:
    """Search, tag, project and priority, as the list view holds them.

    The project filter is keyed on the stable id, not the mutable name —
    an external rename must not blank the filtered list. The name is
    remembered alongside it so a deleted project can still be named in the
    status bar instead of degrading to '?'.
    """

    search: str = ""
    tag: str | None = None
    project_id: int | None = None
    project_name: str | None = None
    priority: Priority | None = None

    def any_active(self) -> bool:
        return bool(self.search or self.tag or self.project_id or self.priority)

    def clear(self) -> None:
        self.search = ""
        self.tag = None
        self.project_id = None
        self.project_name = None
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

    def cycle_project(self, projects: list[Project]) -> None:
        """No filter -> each project in turn -> no filter."""
        if not projects:
            return
        ids = [p.id for p in projects]
        if self.project_id is None:
            idx = 0
        else:
            try:
                current = ids.index(self.project_id)
            except ValueError:
                current = -1
            idx = current + 1
        if idx < len(ids):
            self.project_id = ids[idx]
            self.project_name = projects[idx].name
        else:
            self.project_id = None
            self.project_name = None

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
        if self.project_id is not None:
            label = escape_markup(self.project_name or "?")
            parts.append(f"[dim]Project:[/dim] [b]{label}[/b]")
        if self.priority is not None:
            parts.append(f"[dim]Priority:[/dim] [b]{self.priority.value}[/b]")
        return parts
