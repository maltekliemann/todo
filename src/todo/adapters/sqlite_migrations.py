"""The SQLite schema and its versioned migrations.

Append-only: index i migrates a database at `PRAGMA user_version` i to
i+1, and a fresh database runs all of them, so fresh and upgraded
databases end up with the identical schema.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from todo.adapters.tag_column import decode_tags, encode_tags
from todo.domain.project_name import ProjectName
from todo.domain.tag import Tag
from todo.domain.title import Title

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

    Builds the same value objects the write path builds, so a migrated row
    equals what a new row would be, and project-name collisions get a
    unique ' #id' suffix
    instead of blowing up the UNIQUE constraint and locking the user out
    of the database.
    """
    for item_id, title in conn.execute("SELECT id, title FROM todos").fetchall():
        try:
            normalized = str(Title(title))
        except ValueError:
            normalized = f"Untitled #{item_id}"
        if normalized != title:
            conn.execute(
                "UPDATE todos SET title = ? WHERE id = ?", (normalized, item_id)
            )

    projects = conn.execute("SELECT id, name FROM projects ORDER BY id").fetchall()
    taken = {name for _, name in projects if _clean_name(name, 0) == name}
    for project_id, name in projects:
        normalized = _clean_name(name, project_id)
        if normalized == name:
            continue
        while normalized in taken:
            normalized = f"{normalized} #{project_id}"
        conn.execute(
            "UPDATE projects SET name = ? WHERE id = ?", (normalized, project_id)
        )
        taken.add(normalized)


def _clean_name(name: str, project_id: int) -> str:
    """A legacy project name as ProjectName would have it, or a stand-in.

    Migrations run on rows written before the rules existed, so an
    unbuildable name gets a placeholder rather than stopping the upgrade.
    """
    try:
        return str(ProjectName(name))
    except ValueError:
        return f"project #{project_id}"


def normalize_tag_string(raw: str) -> str:
    """The stored form every read path derives its display from.

    Must produce exactly what the write path produces (each segment a
    Tag, empties dropped, duplicates removed, order preserved) — a
    migration that stops at strip() leaves legacy rows that can never be
    matched by the same string a new row is created with.
    """
    unique: list[Tag] = []
    for tag in decode_tags(raw):
        # Legacy rows predate the no-repeats rule TodoItem now enforces;
        # repairing them here is what lets those rows load at all.
        if tag not in unique:
            unique.append(tag)
    return encode_tags(unique)


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
    # v5: re-run v4. The tag-normalizing migration shipped one commit
    # before the write path started deduping, so a database already at v4
    # could take duplicate tags afterwards and never be repaired — and
    # TodoItem now refuses to load a row with them. Idempotent for
    # everyone else.
    migration_v4_normalize_tags,
]
