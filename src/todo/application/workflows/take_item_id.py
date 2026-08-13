"""Take the identity the next item will be created under.

A workflow, not a query: taking a number changes what is left. It is its
own step because the item is built before it is stored, and an item
cannot be built without knowing which one it is.
"""

from __future__ import annotations

from todo.application.contracts.counter_store import CounterStore
from todo.domain.item_id import ItemId


class TakeItemId:
    def __init__(self, counter: CounterStore) -> None:
        self._counter = counter

    def execute(self) -> ItemId:
        return ItemId(self._counter.take())
