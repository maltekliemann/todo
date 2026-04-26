from __future__ import annotations

from textual.app import App, ComposeResult

from todo.adapters.sqlite_storage import SqliteStorage
from todo.config import get_db_path
from todo.tui.list_view import TodoListView


class TodoApp(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "Todo"

    def __init__(self, storage: SqliteStorage | None = None) -> None:
        super().__init__()
        self._storage = storage or SqliteStorage(get_db_path())

    def compose(self) -> ComposeResult:
        yield TodoListView(self._storage)
