"""The dependency graph, kept in SQLite."""

from __future__ import annotations

from pathlib import Path

from todo.adapters.sqlite_connection import connect, reading, writing
from todo.domain.dependency_graph import DependencyGraph
from todo.domain.item_id import ItemId

_DDL = """\
CREATE TABLE IF NOT EXISTS todo_dependencies (
    blocker_id INTEGER NOT NULL,
    blocked_id INTEGER NOT NULL,
    PRIMARY KEY (blocker_id, blocked_id)
);
"""


class SqliteDependencyStore:
    """Implements DependencyStore.

    The whole edge set goes out and comes back, because that is the size
    of the thing the domain validates. Replacing it is one write: the row
    for an edge is not worth less than the set it belongs to.
    """

    def __init__(self, path: Path) -> None:
        self._conn = connect(path, _DDL)

    def close(self) -> None:
        self._conn.close()

    def load(self) -> DependencyGraph:
        with reading(self._conn, "read dependencies") as conn:
            rows = conn.execute(
                "SELECT blocker_id, blocked_id FROM todo_dependencies"
            ).fetchall()
            # Constructing the graph is the read-side check: a cycle in the
            # file is caught here rather than acted on.
            return DependencyGraph(
                frozenset(
                    (ItemId(r["blocker_id"]), ItemId(r["blocked_id"])) for r in rows
                )
            )

    def save(self, graph: DependencyGraph) -> None:
        with writing(self._conn, "save dependencies") as conn:
            conn.execute("DELETE FROM todo_dependencies")
            conn.executemany(
                "INSERT INTO todo_dependencies (blocker_id, blocked_id) VALUES (?, ?)",
                sorted(graph.edges),
            )
