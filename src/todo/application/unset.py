"""Saying nothing, as opposed to saying "nothing".

Two of an item's fields can be cleared, so for those "leave it alone" and
"set it to none" are different instructions and None cannot mean both.
"""

from __future__ import annotations

from enum import Enum, auto


class Unset(Enum):
    UNSET = auto()


UNSET = Unset.UNSET
