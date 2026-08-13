"""A point in time the domain is willing to compare."""

from __future__ import annotations

from datetime import datetime


class Moment(datetime):
    """A timezone-aware instant.

    A datetime subclass, so it formats, compares and binds exactly as the
    stamp it is. What it adds is the one rule that matters: a naive
    datetime is not a moment. Comparing one against a stored, aware stamp
    raises at the point of comparison — deep inside a store, on a value
    that came from a frontend — and refusing it here means that cannot
    happen.
    """

    __slots__ = ()

    def __new__(cls, *args: object, **kwargs: object) -> Moment:
        moment = super().__new__(cls, *args, **kwargs)  # type: ignore[arg-type]
        if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
            raise ValueError("A moment must say which timezone it is in.")
        return moment

    @classmethod
    def from_datetime(cls, value: datetime) -> Moment:
        """A plain datetime becomes a Moment. Arithmetic on one returns
        `datetime`, so this is the way back."""
        return cls(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            value.tzinfo,
        )
