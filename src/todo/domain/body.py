"""The long text of an item."""

from __future__ import annotations


class Body(str):
    """An item's description: prose, and the only field that is not one line.

    It has no rule, and that is the point of naming it. Titles, tags,
    project names and log entries all collapse their whitespace; the body
    is where newlines and indentation are content — pasted code, a list of
    steps — and a type says so where a bare `str` invited someone to
    normalize it like everything else.
    """

    __slots__ = ()
