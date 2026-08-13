"""Take the identity the next log entry will be written under."""

from __future__ import annotations

from todo.application.contracts.counter_store import CounterStore
from todo.domain.update_id import UpdateId


class TakeUpdateId:
    def __init__(self, counter: CounterStore) -> None:
        self._counter = counter

    def execute(self) -> UpdateId:
        return UpdateId(self._counter.take())
