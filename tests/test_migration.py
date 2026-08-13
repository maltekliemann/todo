"""Schema migration tests: fresh and upgraded databases must be identical."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from todo.adapters.sqlite_storage import SqliteStorage
from todo.domain.description import Description
from todo.domain.item_id import ItemId
from todo.domain.project_name import ProjectName
from todo.domain.tag import Tag
from todo.domain.title import Title

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
        assert item.tags == frozenset({"legacy"})
        assert item.project is None
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
        monkeypatch.setattr(storage_mod, "MIGRATIONS", [bad_migration])
        # Wrapped like every other init-time database failure.
        from todo.exceptions import StorageError

        with pytest.raises(StorageError):
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
        from todo.adapters.sqlite_migrations import MIGRATIONS

        db = tmp_path / "db.db"
        storage = SqliteStorage(db)  # fully migrated: user_version == 2
        # Re-applying migration 1 fails ('projects' exists), but since
        # user_version >= 1 the loser treats it as already done.
        storage._apply_migration(1, MIGRATIONS[0])
        assert storage.get_project_by_name  # still usable
        storage.close()

    def test_genuinely_failed_migration_still_raises(self, tmp_path: Path) -> None:
        from todo.adapters.sqlite_migrations import MIGRATIONS

        db = tmp_path / "db.db"
        storage = SqliteStorage(db)  # fully migrated
        future = len(MIGRATIONS) + 1  # a version nobody has applied
        with pytest.raises(sqlite3.OperationalError):
            storage._apply_migration(future, "CREATE TABLE projects (x INTEGER);\n")
        storage.close()

    def test_migrated_db_supports_projects(self, tmp_path: Path) -> None:
        legacy = tmp_path / "legacy.db"
        _make_legacy_db(legacy)

        storage = SqliteStorage(legacy)
        project = storage.add_project(
            ProjectName("infra"), description=Description("Infra work")
        )
        item = storage.get(ItemId(1))
        item.file_under(project)
        storage.save(item)
        filed = storage.get(1)
        assert filed.project is not None and filed.project.name == "infra"
        storage.close()


class TestLegacyDataNormalization:
    def test_multiline_titles_normalized_by_migration(self, tmp_path: Path) -> None:
        """Rows written before title normalization existed must be cleaned
        up in place, or the editor round-trip silently truncates them."""
        db = tmp_path / "db.db"
        _make_legacy_db(db)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO todos (title, body, created_at, updated_at, tags) "
            "VALUES ('part one' || char(10) || 'part two', '', "
            "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', '')"
        )
        conn.commit()
        conn.close()

        storage = SqliteStorage(db)
        titles = [i.title for i in storage.list(include_done=True)]
        assert "part one part two" in titles
        assert all("\n" not in t for t in titles)
        storage.close()


def _make_v2_db_with_projects(path: Path, names: list[str]) -> None:
    """A database exactly as v2 code left it: projects exist, no v3 cleanup."""
    from todo.adapters.sqlite_migrations import MIGRATIONS

    _make_legacy_db(path)
    conn = sqlite3.connect(str(path))
    for script in MIGRATIONS[:2]:
        conn.executescript(script)
    for name in names:
        conn.execute(
            "INSERT INTO projects (name, description, status, created_at, "
            "updated_at) VALUES (?, '', 'active', '2026-01-01T00:00:00+00:00', "
            "'2026-01-01T00:00:00+00:00')",
            (name,),
        )
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()


class TestV4TagNormalization:
    def test_legacy_padded_tags_match_tag_filter_after_migration(
        self, tmp_path: Path
    ) -> None:
        """Tags stored padded by the legacy write path are displayed
        stripped, so the migration must strip them in place — otherwise the
        advertised tag can never match the SQL tag filter."""
        db = tmp_path / "db.db"
        _make_legacy_db(db)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO todos (title, body, created_at, updated_at, tags) "
            "VALUES ('padded', '', '2026-01-01T00:00:00+00:00', "
            "'2026-01-01T00:00:00+00:00', 'home ')"
        )
        conn.execute(
            "INSERT INTO todos (title, body, created_at, updated_at, tags) "
            "VALUES ('spaced pair', '', '2026-01-01T00:00:00+00:00', "
            "'2026-01-01T00:00:00+00:00', 'web, api')"
        )
        conn.commit()
        conn.close()

        storage = SqliteStorage(db)
        assert [i.title for i in storage.list(tags=frozenset({"home"}))] == ["padded"]
        assert [i.title for i in storage.list(tags=frozenset({"api"}))] == [
            "spaced pair"
        ]
        assert [i.title for i in storage.list(tags=frozenset({"web"}))] == [
            "spaced pair"
        ]
        storage.close()

    def test_legacy_duplicate_and_empty_tag_segments_cleaned(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "db.db"
        _make_legacy_db(db)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO todos (title, body, created_at, updated_at, tags) "
            "VALUES ('dupes', '', '2026-01-01T00:00:00+00:00', "
            "'2026-01-01T00:00:00+00:00', 'a, ,a,b')"
        )
        conn.commit()
        conn.close()

        storage = SqliteStorage(db)
        (item,) = [i for i in storage.list() if i.title == "dupes"]
        assert item.tags == frozenset({"a", "b"})
        storage.close()

        conn = sqlite3.connect(str(db))
        raw = conn.execute("SELECT tags FROM todos WHERE title = 'dupes'").fetchone()[0]
        conn.close()
        # Stored form now equals the displayed form.
        assert raw == "a,b"


class TestV3MigrationCollisions:
    def test_colliding_project_names_do_not_brick_the_db(self, tmp_path: Path) -> None:
        """Two legacy names normalizing to the same string must not blow up
        the UNIQUE constraint and lock the user out of their data."""
        db = tmp_path / "db.db"
        _make_v2_db_with_projects(db, ["alpha\nbeta", "alpha beta"])

        storage = SqliteStorage(db)  # must not raise
        names = [p.name for p in storage.list_projects(include_archived=True)]
        assert len(names) == len(set(names))  # unique
        assert all("\n" not in n for n in names)
        assert "alpha beta" in names
        storage.close()

    def test_whitespace_runs_fully_collapsed(self, tmp_path: Path) -> None:
        db = tmp_path / "db.db"
        _make_legacy_db(db)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO todos (title, body, created_at, updated_at, tags) "
            "VALUES ('part one' || char(10) || char(10) || char(10) || "
            "'part two', '', '2026-01-01T00:00:00+00:00', "
            "'2026-01-01T00:00:00+00:00', '')"
        )
        conn.commit()
        conn.close()

        storage = SqliteStorage(db)
        titles = [i.title for i in storage.list(include_done=True)]
        assert "part one part two" in titles  # no double spaces
        storage.close()


class TestV5DuplicateTagRepair:
    """v4 shipped one commit before the write path started deduping, so a
    database already at v4 could take duplicate tags and never be
    repaired. TodoItem now refuses to load such a row, which would lock
    someone out of their own items."""

    def test_a_v4_database_with_duplicate_tags_is_repaired(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "legacy.db"
        storage = SqliteStorage(db)
        storage.close()

        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO todos (title, created_at, updated_at, tags) "
            "VALUES ('task', '2026-01-01T00:00:00', '2026-01-01T00:00:00', "
            "'a, a ,,b')"
        )
        conn.execute("PRAGMA user_version = 4")
        conn.commit()
        conn.close()

        reopened = SqliteStorage(db)
        try:
            assert reopened.get(1).tags == frozenset({"a", "b"})
        finally:
            reopened.close()

    def test_repairing_twice_changes_nothing(self, tmp_path: Path) -> None:
        db = tmp_path / "clean.db"
        storage = SqliteStorage(db)
        storage.add(Title("task"), tags=frozenset({Tag("a"), Tag("b")}))
        storage.close()

        reopened = SqliteStorage(db)
        try:
            assert reopened.get(1).tags == frozenset({"a", "b"})
        finally:
            reopened.close()
