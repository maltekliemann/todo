"""The detail pane under the table: one item, rendered in full."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from todo.application.queries.project_names import ProjectNames
from todo.domain.dependency_graph import DependencyGraph
from todo.domain.todo_item import TodoItem
from todo.tui.render import escape_markup, meta_lines


class DetailPane(Vertical):
    """Title, metadata and body for the selected item."""

    def compose(self) -> ComposeResult:
        yield Static("", id="detail-title")
        yield Static("", id="detail-meta")
        yield Static("", id="detail-body")

    def show(
        self,
        item: TodoItem,
        graph: DependencyGraph,
        names: ProjectNames,
    ) -> None:
        self.query_one("#detail-title", Static).update(
            f"[b]#{item.id}  {escape_markup(item.title)}[/b]"
        )
        self.query_one("#detail-meta", Static).update(
            "\n".join(meta_lines(item, graph, names))
        )
        # Text, not markup: the body is user-controlled.
        self.query_one("#detail-body", Static).update(
            Text(item.body) if item.body else ""
        )

    def clear(self) -> None:
        for widget_id in ("#detail-title", "#detail-meta", "#detail-body"):
            self.query_one(widget_id, Static).update("")
