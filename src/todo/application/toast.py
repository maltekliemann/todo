"""Something that happened, worth telling the person about.

A toast carries facts, not words. "#2 and #5 are no longer blocked" is
the fact; whether that becomes a popup in the corner of the TUI or a
line on stderr is the frontend's business, and so is the wording.

Defined here because a workflow returns it, and the application cannot
depend on a presenter.
"""

from __future__ import annotations

from dataclasses import dataclass

from todo.domain.item_id import ItemId


@dataclass(frozen=True)
class Unblocked:
    """Items that became unblocked: every one of their blockers is done."""

    items: list[ItemId]


Toast = Unblocked
