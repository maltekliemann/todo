"""Whether anything changed.

A live view has to know when what it is showing has gone stale — someone
else's `todo done 3` in another terminal. It does not need to know what
changed or how the store noticed.
"""

from __future__ import annotations

from typing import Protocol


class ChangeFeed(Protocol):
    def revision(self) -> int:
        """A number that differs from the last one when someone else has
        written. Compare it with the one you saw; nothing else about it
        means anything."""
        ...
