"""Take the identity the next project will be created under."""

from __future__ import annotations

from todo.application.contracts.counter_store import CounterStore
from todo.domain.project_id import ProjectId


class TakeProjectId:
    def __init__(self, counter: CounterStore) -> None:
        self._counter = counter

    def execute(self) -> ProjectId:
        return ProjectId(self._counter.take())
