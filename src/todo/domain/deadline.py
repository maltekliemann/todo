"""The date an item is due."""

from __future__ import annotations

from datetime import date


class Deadline(date):
    """A due date, which knows about itself and nothing else.

    Whether it has passed is a property of the date. Whether the item is
    *overdue* is not — that also depends on whether the item is done, which
    is the item's business. See TodoItem.is_overdue.
    """

    __slots__ = ()

    @classmethod
    def from_date(cls, value: date) -> Deadline:
        """A plain date becomes a Deadline. Date arithmetic returns `date`,
        so this is the way back."""
        return cls(value.year, value.month, value.day)

    @property
    def has_passed(self) -> bool:
        return date.today() > self

    @property
    def days_until(self) -> int:
        # Ordinals rather than a timedelta: subtracting two dates where one
        # is a subclass confuses the type checker for no gain.
        return self.toordinal() - date.today().toordinal()
