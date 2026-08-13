"""The SQLite schema and its versioned migrations.

Append-only: index i migrates a database at `PRAGMA user_version` i to
i+1, and a fresh database runs all of them, so fresh and upgraded
databases end up with the identical schema.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from todo.domain.tag import dedupe_tags, split_tags
from todo.domain.text import single_line

SCHEMA = """\
CREATE TABLE IF NOT EXISTS todos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL,
    body       TEXT    NOT NULL DEFAULT '',
    priority   TEXT    NOT NULL DEFAULT 'medium',
    status     TEXT    NOT NULL DEFAULT 'todo',
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL,
    done_at    TEXT,
    deadline   TEXT,
    tags       TEXT    NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS todo_dependencies (
    blocker_id INTEGER NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
    blocked_id INTEGER NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
    PRIMARY KEY (blocker_id, blocked_id)
);
"""


def migration_v3_normalize(conn: sqlite3.Connection) -> None:
    """Normalize rows written before single-line normalization existed.

    Uses the shared domain helper so migrated rows equal what the write
    path produces, and project-name collisions get a unique ' #id' suffix
    instead of blowing up the UNIQUE constraint and locking the user out
    of the database.
    """
    for item_id, title in conn.execute("SELECT id, title FROM todos").fetchall():
        normalized = single_line(title) or f"Untitled #{item_id}"
        if normalized != title:
            conn.execute(
                "UPDATE todos SET title = ? WHERE id = ?", (normalized, item_id)
            )

    projects = conn.execute("SELECT id, name FROM projects ORDER BY id").fetchall()
    taken = {name for _, name in projects if single_line(name) == name}
    for project_id, name in projects:
        normalized = single_line(name) or f"project #{project_id}"
        if normalized == name:
            continue
        while normalized in taken:
            normalized = f"{normalized} #{project_id}"
        conn.execute(
            "UPDATE projects SET name = ? WHERE id = ?", (normalized, project_id)
        )
        taken.add(normalized)


def normalize_tag_string(raw: str) -> str:
    """The stored form every read path derives its display from.

    Must produce exactly what the write path produces (single_line per
    segment, empties dropped, duplicates removed, order preserved) — a
    migration that stops at strip() leaves legacy rows that can never be
    matched by the same string a new row is created with.
    """
    return ",".join(dedupe_tags(single_line(t) for t in split_tags(raw)))


def migration_v4_normalize_tags(conn: sqlite3.Connection) -> None:
    """Normalize tags written before tag normalization existed.

    Legacy rows store tags verbatim (padding, empty segments, duplicates)
    while every read path strips segments for display — so the tag a user
    sees could never match the SQL tag filter, which compares against the
    raw column. Rewriting to the displayed form makes filters work again.
    """
    for item_id, raw in conn.execute("SELECT id, tags FROM todos").fetchall():
        normalized = normalize_tag_string(raw)
        if normalized != raw:
            conn.execute(
                "UPDATE todos SET tags = ? WHERE id = ?", (normalized, item_id)
            )


# Versioned migrations, gated by PRAGMA user_version. Index i migrates a
# database at user_version i to i+1. A fresh database runs all of them, so
# fresh and upgraded databases end up with the identical schema. SQL entries
# are split on ';' — statements must not contain literal semicolons; use a
# callable for anything data-dependent.
MIGRATIONS: list[str | Callable[[sqlite3.Connection], None]] = [
    """\
CREATE TABLE projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    description TEXT    NOT NULL DEFAULT '',
    status      TEXT    NOT NULL DEFAULT 'active',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
ALTER TABLE todos ADD COLUMN project_id INTEGER
    REFERENCES projects(id) ON DELETE SET NULL;
""",
    """\
CREATE TABLE project_updates (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    body       TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);
""",
    migration_v3_normalize,
    migration_v4_normalize_tags,
]
