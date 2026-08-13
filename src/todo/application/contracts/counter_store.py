"""Where a running number is kept.

Identity is not storage's to invent — a store keeps what it is given and
hands it back. But the number that says which one is next has to survive
between two runs of the program, and surviving between runs is exactly
what a store is for. So the counter is kept here and read from here, and
what the number is taken to identify is decided above.
"""

from __future__ import annotations

from typing import Protocol


class CounterStore(Protocol):
    """One running number, taken one at a time."""

    def take(self) -> int:
        """The next number, and never that number again.

        Taking it is the whole operation: the increment and the read are
        one atomic step, so two callers cannot be handed the same number.
        """
        ...
