"""Schema migration tests: fresh and upgraded databases must be identical."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from todo.adapters.sqlite_storage import SqliteStorage

_LEGACY_SCHEMA = """\
CREATE TABLE todos (
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
CREATE TABLE todo_dependencies (
    blocker_id INTEGER NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
    blocked_id INTEGER NOT NULL REFERENCES todos(id) ON DELETE CASCADE,
    PRIMARY KEY (blocker_id, blocked_id)
);
"""


def _make_legacy_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(_LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO todos (title, body, created_at, updated_at, tags) "
        "VALUES ('Old item', 'kept', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 'legacy')"
    )
    conn.commit()
    conn.close()


def _schema_snapshot(path: Path) -> dict[str, list[str]]:
    """Table -> ordered column names, for every user table."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    tables = [
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    snapshot = {
        t: [r["name"] for r in conn.execute(f"PRAGMA table_info({t})")] for t in tables
    }
    conn.close()
    return snapshot


def _user_version(path: Path) -> int:
    conn = sqlite3.connect(str(path))
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    conn.close()
    return version


class TestMigration:
    def test_fresh_and_migrated_schemas_match(self, tmp_path: Path) -> None:
        fresh = tmp_path / "fresh.db"
        legacy = tmp_path / "legacy.db"
        SqliteStorage(fresh).close()
        _make_legacy_db(legacy)
        SqliteStorage(legacy).close()

        assert _schema_snapshot(fresh) == _schema_snapshot(legacy)
        assert _user_version(fresh) == _user_version(legacy)

    def test_migration_preserves_data(self, tmp_path: Path) -> None:
        legacy = tmp_path / "legacy.db"
        _make_legacy_db(legacy)

        storage = SqliteStorage(legacy)
        item = storage.get(1)
        assert item.title == "Old item"
        assert item.body == "kept"
        assert item.tags == ["legacy"]
        assert item.project_id is None
        storage.close()

    def test_migration_is_idempotent(self, tmp_path: Path) -> None:
        db = tmp_path / "db.db"
        _make_legacy_db(db)
        SqliteStorage(db).close()
        before = _schema_snapshot(db)
        # Re-opening must not attempt to re-apply migrations.
        SqliteStorage(db).close()
        assert _schema_snapshot(db) == before

    def test_failed_migration_leaves_no_partial_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A migration that dies partway must roll back entirely.

        Each migration and its user_version bump run in one transaction, so
        a crash can never strand the database in a half-applied state that
        breaks every subsequent open.
        """
        import todo.adapters.sqlite_storage as storage_mod

        db = tmp_path / "db.db"
        _make_legacy_db(db)

        # First statement succeeds, second fails (todos already exists).
        bad_migration = (
            "CREATE TABLE mig_probe (id INTEGER);\nCREATE TABLE todos (id INTEGER);\n"
        )
        monkeypatch.setattr(storage_mod, "_MIGRATIONS", [bad_migration])
        with pytest.raises(sqlite3.OperationalError):
            SqliteStorage(db)

        conn = sqlite3.connect(str(db))
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        conn.close()
        # No partial state: probe table rolled back, version untouched.
        assert "mig_probe" not in tables
        assert version == 0

        # With the real migrations restored, the same database opens fine.
        monkeypatch.undo()
        storage = SqliteStorage(db)
        assert storage.get(1).title == "Old item"
        storage.close()

    def test_losing_a_migration_race_is_not_an_error(self, tmp_path: Path) -> None:
        """If another process applies the migration between our version
        check and our attempt, the failure is recognized as success."""
        from todo.adapters.sqlite_storage import _MIGRATIONS

        db = tmp_path / "db.db"
        storage = SqliteStorage(db)  # fully migrated: user_version == 2
        # Re-applying migration 1 fails ('projects' exists), but since
        # user_version >= 1 the loser treats it as already done.
        storage._apply_migration(1, _MIGRATIONS[0])
        assert storage.get_project_by_name  # still usable
        storage.close()

    def test_genuinely_failed_migration_still_raises(self, tmp_path: Path) -> None:
        db = tmp_path / "db.db"
        storage = SqliteStorage(db)  # user_version == 2
        with pytest.raises(sqlite3.OperationalError):
            storage._apply_migration(3, "CREATE TABLE projects (x INTEGER);\n")
        storage.close()

    def test_migrated_db_supports_projects(self, tmp_path: Path) -> None:
        legacy = tmp_path / "legacy.db"
        _make_legacy_db(legacy)

        storage = SqliteStorage(legacy)
        project = storage.add_project("infra", description="Infra work")
        storage.update(1, project_id=project.id)
        assert storage.get(1).project_name == "infra"
        storage.close()
