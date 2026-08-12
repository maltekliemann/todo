"""User-controlled text must never be parsed as Rich/Textual markup.

Hostile strings like "[/]" crash Rich markup parsing; "[bold" and "]]"
probe unbalanced-tag handling. Every render sink that receives titles,
bodies, tags, project names/descriptions, or log bodies is exercised here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from textual.widgets import DataTable, Label, Static

from todo.adapters.output import RichOutput
from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import add_todo, block_todo
from todo.application.queries import ProjectDetail, ProjectSummary, show_project
from todo.domain.enums import Priority, ProjectStatus, Status
from todo.domain.models import Project, ProjectUpdate, TodoItem
from todo.tui.app import TodoApp

HOSTILE = "Fix [/] thing"
HOSTILE_VARIANTS = ["Fix [/] thing", "open [bold tag", "double ]] close", "[/b]"]

_NOW = datetime.now(tz=timezone.utc)


def _item(**overrides: object) -> TodoItem:
    defaults: dict[str, object] = {
        "id": 1,
        "title": HOSTILE,
        "body": "body with [/] markup",
        "priority": Priority.MEDIUM,
        "status": Status.TODO,
        "created_at": _NOW,
        "updated_at": _NOW,
        "done_at": None,
        "deadline": None,
        "tags": ["[/]", "ok"],
    }
    defaults.update(overrides)
    return TodoItem(**defaults)  # type: ignore[arg-type]


def _project(**overrides: object) -> Project:
    defaults: dict[str, object] = {
        "id": 1,
        "name": "proj [/] name",
        "description": "desc [/] here",
        "status": ProjectStatus.ACTIVE,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    defaults.update(overrides)
    return Project(**defaults)  # type: ignore[arg-type]


@pytest.fixture()
def rich_out(monkeypatch: pytest.MonkeyPatch) -> RichOutput:
    monkeypatch.setenv("COLUMNS", "140")
    return RichOutput()


class TestRichOutputMarkupSafety:
    @pytest.mark.parametrize("title", HOSTILE_VARIANTS)
    def test_print_list_hostile_titles(
        self, rich_out: RichOutput, capsys, title: str
    ) -> None:
        rich_out.print_list([_item(title=title)])
        assert title in capsys.readouterr().out

    def test_print_list_hostile_blocked_title(
        self, rich_out: RichOutput, capsys
    ) -> None:
        rich_out.print_list([_item(is_blocked=True, blocked_by=[2])])
        assert HOSTILE in capsys.readouterr().out

    def test_print_item_hostile(self, rich_out: RichOutput, capsys) -> None:
        rich_out.print_item(_item())
        out = capsys.readouterr().out
        assert "[/]" in out

    def test_print_summary_hostile_title(self, rich_out: RichOutput, capsys) -> None:
        done = _item(status=Status.DONE, done_at=_NOW)
        rich_out.print_summary(_NOW, [done])
        assert HOSTILE in capsys.readouterr().out

    def test_print_tags_hostile_tag(self, rich_out: RichOutput, capsys) -> None:
        rich_out.print_tags([("[/]", 2)])
        assert "[/]" in capsys.readouterr().out

    def test_print_projects_hostile_name_and_description(
        self, rich_out: RichOutput, capsys
    ) -> None:
        summaries = [
            ProjectSummary(project=_project(), open_count=1, done_count=0),
            ProjectSummary(
                project=_project(id=2, name="arch [/]", status=ProjectStatus.ARCHIVED),
                open_count=0,
                done_count=0,
            ),
        ]
        rich_out.print_projects(summaries)
        out = capsys.readouterr().out
        assert "proj [/] name" in out
        assert "arch [/]" in out

    def test_print_project_hostile_description_and_log(
        self, rich_out: RichOutput, capsys
    ) -> None:
        detail = ProjectDetail(
            project=_project(),
            items=[_item()],
            updates=[
                ProjectUpdate(id=1, project_id=1, body="log [/] body", created_at=_NOW)
            ],
        )
        rich_out.print_project(detail)
        out = capsys.readouterr().out
        assert "desc [/] here" in out
        assert "log [/] body" in out


class TestTuiMarkupSafety:
    @pytest.fixture()
    def hostile_storage(self, db_path: Path) -> SqliteStorage:
        storage = SqliteStorage(db_path)
        project = storage.add_project("proj [/] name", description="desc [/] here")
        add_todo(
            storage,
            HOSTILE,
            body="body with [/] markup",
            tags=["[/]"],
            project_id=project.id,
        )
        add_todo(storage, "Blocker [bold title")
        block_todo(storage, 1, 2)
        return storage

    async def test_tui_launches_with_hostile_items(
        self, hostile_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=hostile_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert table.row_count > 0
            # Detail pane rendered the hostile title/body/tags without crashing.
            meta = str(app.query_one("#detail-meta", Static).render())
            assert "[/]" in meta

    async def test_inspect_dialog_hostile(self, hostile_storage: SqliteStorage) -> None:
        app = TodoApp(storage=hostile_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            from todo.tui.dialogs import InspectDialog

            assert isinstance(app.screen, InspectDialog)
            await pilot.press("escape")
            await pilot.pause()

    async def test_search_status_hostile_query(
        self, hostile_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=hostile_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash")
            await pilot.pause()
            for ch in "[/]":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()
            status = str(app.query_one("#search-status", Static).render())
            assert "[/]" in status

    async def test_filter_status_hostile_tag_and_project(
        self, hostile_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=hostile_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t")  # tag filter: "[/]"
            await pilot.press("p")  # project filter: "proj [/] name"
            await pilot.pause()
            status = str(app.query_one("#search-status", Static).render())
            assert "[/]" in status

    async def test_unblock_notification_hostile_title(
        self, hostile_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=hostile_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Cursor is on #1 (hostile title, blocked by #2). Move to #2 and
            # complete it -> notify() fires with #1's hostile title.
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()

    async def test_block_dialog_hostile_input(
        self, hostile_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=hostile_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            for ch in "[/]":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()
            from todo.tui.dialogs import BlockDialog

            # Dialog stays open showing the (safe) error, no crash.
            assert isinstance(app.screen, BlockDialog)
            error = str(app.screen.query_one("#block-error", Label).render())
            assert error != ""


class TestShowProjectHostileEndToEnd:
    def test_cli_pipeline_survives_hostile_text(self, storage: SqliteStorage) -> None:
        project = storage.add_project("p [/] q", description="d [/] e")
        add_todo(storage, HOSTILE, project_id=project.id)
        storage.add_project_update(project.id, "u [/] v")
        detail = show_project(storage, "p [/] q")
        assert detail.updates[0].body == "u [/] v"


class TestTextualMarkupEscaping:
    """rich.markup.escape only escapes lowercase-initial tags, but Textual
    also parses [WIP], [Red] and [$VAR] — user text must survive all of
    them intact in every markup-rendering sink."""

    def test_escaper_covers_textual_tag_shapes(self) -> None:
        from textual.content import Content

        from todo.tui.render import escape_markup

        for hostile in ("[WIP] refactor", "[Red]x", "[$VAR] y", "[/] z", "[b]lower"):
            assert Content.from_markup(escape_markup(hostile)).plain == hostile

    async def test_detail_pane_keeps_bracketed_title(self, db_path: Path) -> None:
        from todo.adapters.sqlite_storage import SqliteStorage
        from todo.application.commands import add_todo
        from todo.tui.app import TodoApp

        storage = SqliteStorage(db_path)
        add_todo(storage, "[WIP] refactor auth", tags=["[Red]tag"])
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            title = str(app.query_one("#detail-title", Static).render())
            meta = str(app.query_one("#detail-meta", Static).render())
            assert "[WIP] refactor auth" in title
            assert "[Red]tag" in meta

    async def test_inspect_modal_keeps_bracketed_title(self, db_path: Path) -> None:
        from todo.adapters.sqlite_storage import SqliteStorage
        from todo.application.commands import add_todo
        from todo.tui.app import TodoApp

        storage = SqliteStorage(db_path)
        add_todo(storage, "[WIP] refactor auth")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            title = str(app.screen.query_one("#inspect-title", Static).render())
            assert "[WIP] refactor auth" in title

    async def test_filter_bar_keeps_bracketed_search(self, db_path: Path) -> None:
        from todo.adapters.sqlite_storage import SqliteStorage
        from todo.application.commands import add_todo
        from todo.tui.app import TodoApp
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "plain")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            view._filters.search = "[WIP]"
            view._refresh_list()
            await pilot.pause()
            status = str(app.query_one("#search-status", Static).render())
            assert "[WIP]" in status


class TestBackslashAndLiteralHints:
    def test_escaper_round_trips_backslashes(self) -> None:
        """Textual's Content.from_markup does not collapse '\\\\' back to
        '\\', so doubling backslashes corrupts every sink."""
        from textual.content import Content

        from todo.tui.render import escape_markup

        for hostile in (r"C:\Users\alice", r"a\[b] c", "back\\\\slash", r"\needle"):
            assert Content.from_markup(escape_markup(hostile)).plain == hostile

    async def test_windows_path_title_renders_once(self, db_path: Path) -> None:
        from todo.adapters.sqlite_storage import SqliteStorage
        from todo.application.commands import add_todo
        from todo.tui.app import TodoApp

        storage = SqliteStorage(db_path)
        add_todo(storage, r"Sync C:\Users\alice\notes", tags=[r"win\path"])
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            title = str(app.query_one("#detail-title", Static).render())
            meta = str(app.query_one("#detail-meta", Static).render())
            assert r"Sync C:\Users\alice\notes" in title
            assert r"\\Users" not in title
            assert r"win\path" in meta

    async def test_confirm_dialog_shows_key_hints(self, db_path: Path) -> None:
        """The app's own literal '[y] Yes   [n] No' hint was being eaten as
        markup, so the user saw no key labels at all."""
        from todo.adapters.sqlite_storage import SqliteStorage
        from todo.application.commands import add_todo
        from todo.tui.app import TodoApp

        storage = SqliteStorage(db_path)
        add_todo(storage, "item")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            hint = str(app.screen.query_one("#confirm-hint", Label).render())
            assert "[y]" in hint
            assert "[n]" in hint
