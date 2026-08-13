from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult

from todo.adapters.sqlite_counter_store import SqliteCounterStore
from todo.adapters.sqlite_dependency_store import SqliteDependencyStore
from todo.adapters.sqlite_item_store import SqliteItemStore
from todo.application.contracts.counter_store import CounterStore
from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemStore
from todo.config import get_db_path
from todo.tui.list_view import TodoListView


class TodoApp(App[None]):
    """Where the TUI is wired: the adapters are chosen here and nowhere
    else, and what is handed down is what each screen needs."""

    CSS_PATH = "styles.tcss"
    TITLE = "Todo"

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        items: ItemStore | None = None,
        dependencies: DependencyStore | None = None,
        item_ids: CounterStore | None = None,
    ) -> None:
        """SQLite by default; any of them may be handed in instead,
        which is the whole point of them being contracts."""
        super().__init__()
        path = db_path or get_db_path()
        self._items = items or SqliteItemStore(path)
        self._dependencies = dependencies or SqliteDependencyStore(path)
        self._item_ids = item_ids or SqliteCounterStore(path, "items")

    def compose(self) -> ComposeResult:
        yield TodoListView(self._items, self._dependencies, self._item_ids)
