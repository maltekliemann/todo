"""User-controlled text must never be parsed as Rich/Textual markup.

Hostile strings like "[/]" crash Rich markup parsing; "[bold" and "]]"
probe unbalanced-tag handling. Every render sink that receives titles,
bodies, tags, project names/descriptions, or log bodies is exercised here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType

import pytest
from textual.widgets import DataTable, Label, Static

from tests.factory import (
    NewItem,
    add_blocker,
    add_project,
    add_todo,
    log_project_update,
    show_project,
)
from todo.adapters.sqlite_dependency_store import SqliteDependencyStore
from todo.adapters.sqlite_item_store import SqliteItemStore
from todo.adapters.sqlite_project_log_store import SqliteProjectLogStore
from todo.adapters.sqlite_project_store import SqliteProjectStore
from todo.application.queries.list_projects import ProjectSummary
from todo.application.queries.list_tags import TagCount
from todo.application.queries.project_names import ProjectNames
from todo.application.queries.show_project import ProjectDetail
from todo.domain.dependency_graph import DependencyGraph
from todo.domain.description import Description
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName
from todo.domain.project_status import ProjectStatus
from todo.domain.project_update import ProjectUpdate
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.todo_item import TodoItem
from todo.domain.update_body import UpdateBody
from todo.domain.update_id import UpdateId
from todo.infra.cli.output import RichOutput
from todo.tui.app import TodoApp

HOSTILE = "Fix [/] thing"
HOSTILE_VARIANTS = ["Fix [/] thing", "open [bold tag", "double ]] close", "[/b]"]

_NOW = datetime.now(tz=timezone.utc)


# No project is filed under anything in these renders.
NO_NAMES = ProjectNames(MappingProxyType({}))


def _graph(*edges: tuple[int, int]) -> DependencyGraph:
    return DependencyGraph(frozenset((ItemId(a), ItemId(b)) for a, b in edges))


def _done(*ids: int) -> frozenset[ItemId]:
    return frozenset(ItemId(i) for i in ids)


def _item(**overrides: object) -> TodoItem:
    defaults: dict[str, object] = {
        "id": ItemId(1),
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
        "id": ProjectId(1),
        "name": ProjectName("proj [/] name"),
        "description": Description("desc [/] here"),
        "status": ProjectStatus.IN_PROGRESS,
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
        rich_out.print_list([_item(title=title)], _graph(), _done())
        assert title in capsys.readouterr().out

    def test_print_list_hostile_blocked_title(
        self, rich_out: RichOutput, capsys
    ) -> None:
        rich_out.print_list([_item()], _graph((2, 1)), _done())
        assert HOSTILE in capsys.readouterr().out

    def test_print_item_hostile(self, rich_out: RichOutput, capsys) -> None:
        rich_out.print_item(_item(), _graph(), _done(), NO_NAMES)
        out = capsys.readouterr().out
        assert "[/]" in out

    def test_print_summary_hostile_title(self, rich_out: RichOutput, capsys) -> None:
        done = _item(status=Status.DONE, done_at=_NOW)
        rich_out.print_summary(_NOW, [done], _graph(), _done())
        assert HOSTILE in capsys.readouterr().out

    def test_print_tags_hostile_tag(self, rich_out: RichOutput, capsys) -> None:
        rich_out.print_tags([TagCount(tag=Tag("[/]"), count=2)])
        assert "[/]" in capsys.readouterr().out

    def test_print_projects_hostile_name_and_description(
        self, rich_out: RichOutput, capsys
    ) -> None:
        summaries = [
            ProjectSummary(project=_project(), open_count=1, done_count=0),
            ProjectSummary(
                project=_project(
                    id=ProjectId(2),
                    name=ProjectName("arch [/]"),
                    status=ProjectStatus.DONE,
                ),
                open_count=0,
                done_count=0,
            ),
        ]
        rich_out.print_projects(summaries)
        out = capsys.readouterr().out
        assert "proj [/] name" in out
        assert "arch [/]" in out

    def test_print_project_hostile_description_and_log(
        self, log: SqliteProjectLogStore, rich_out: RichOutput, capsys
    ) -> None:
        detail = ProjectDetail(
            project=_project(),
            items=[_item()],
            updates=[
                ProjectUpdate(
                    id=UpdateId(1),
                    project_id=ProjectId(1),
                    body=UpdateBody("log [/] body"),
                    created_at=_NOW,
                )
            ],
        )
        rich_out.print_project(detail, _graph(), _done(), NO_NAMES)
        out = capsys.readouterr().out
        assert "desc [/] here" in out
        assert "log [/] body" in out


class TestTuiMarkupSafety:
    @pytest.fixture()
    def hostile_storage(
        self,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
        projects: SqliteProjectStore,
        db_path: Path,
    ) -> Path:
        project = add_project(projects, "proj [/] name", description="desc [/] here")
        add_todo(
            items,
            NewItem(
                title=HOSTILE,
                body="body with [/] markup",
                tags=["[/]"],
                project_id=project.id,
            ),
        )
        add_todo(items, NewItem(title="Blocker [bold title"))
        add_blocker(items, dependencies, 1, [2])
        return db_path

    async def test_tui_launches_with_hostile_items(self, hostile_storage: Path) -> None:
        app = TodoApp(hostile_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert table.row_count > 0
            # Detail pane rendered the hostile title/body/tags without crashing.
            meta = str(app.query_one("#detail-meta", Static).render())
            assert "[/]" in meta

    async def test_item_screen_hostile(self, hostile_storage: Path) -> None:
        app = TodoApp(hostile_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            from todo.tui.item_screen import ItemScreen

            assert isinstance(app.screen, ItemScreen)
            await pilot.press("escape")
            await pilot.pause()

    async def test_search_status_hostile_query(self, hostile_storage: Path) -> None:
        app = TodoApp(hostile_storage)
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
        self, hostile_storage: Path
    ) -> None:
        app = TodoApp(hostile_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("t")  # tag filter: "[/]"
            await pilot.press("p")  # project filter: "proj [/] name"
            await pilot.pause()
            status = str(app.query_one("#search-status", Static).render())
            assert "[/]" in status

    async def test_unblock_notification_hostile_title(
        self, hostile_storage: Path
    ) -> None:
        app = TodoApp(hostile_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Cursor is on #1 (hostile title, blocked by #2). Move to #2 and
            # complete it -> notify() fires with #1's hostile title.
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()

    async def test_block_dialog_hostile_input(self, hostile_storage: Path) -> None:
        """The dialog is a search box over a list of user-written titles:
        hostile text must survive both as a query and as a rendered
        candidate, verbatim and without crashing."""
        from textual.widgets import OptionList

        from todo.tui.blockers import BlockDialog

        app = TodoApp(hostile_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()

            options = app.screen.query_one("#block-options", OptionList)
            rendered = [str(o.prompt) for o in options._options]
            assert any("Blocker [bold title" in r for r in rendered), rendered

            for ch in "[/]":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            # No crash, and nothing chosen from an empty result.
            assert app.is_running
            assert isinstance(app.screen, BlockDialog)


class TestShowProjectHostileEndToEnd:
    def test_cli_pipeline_survives_hostile_text(
        self,
        items: SqliteItemStore,
        projects: SqliteProjectStore,
        log: SqliteProjectLogStore,
    ) -> None:
        project = add_project(projects, "p [/] q", description="d [/] e")
        add_todo(items, NewItem(title=HOSTILE, project_id=project.id))
        log_project_update(projects, log, project.id, "u [/] v")
        detail = show_project(projects, items, log, "p [/] q")
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

    async def test_detail_pane_keeps_bracketed_title(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        from tests.factory import NewItem, add_todo
        from todo.tui.app import TodoApp

        add_todo(items, NewItem(title="[WIP] refactor auth", tags=["[Red]tag"]))
        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            title = str(app.query_one("#detail-title", Static).render())
            meta = str(app.query_one("#detail-meta", Static).render())
            assert "[WIP] refactor auth" in title
            assert "[Red]tag" in meta

    async def test_item_screen_keeps_bracketed_title(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        from rich.text import Text
        from textual.widgets import OptionList

        from tests.factory import NewItem, add_todo
        from todo.tui.app import TodoApp

        add_todo(items, NewItem(title="[WIP] refactor auth"))
        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            row = app.screen.query_one("#item-fields", OptionList).get_option_at_index(
                0
            )
            # A Text prompt is never parsed as markup, so "[WIP]" survives.
            assert isinstance(row.prompt, Text)
            assert "[WIP] refactor auth" in str(row.prompt)

    async def test_filter_bar_keeps_bracketed_search(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        from tests.factory import NewItem, add_todo
        from todo.tui.app import TodoApp
        from todo.tui.list_view import TodoListView

        add_todo(items, NewItem(title="plain"))
        app = TodoApp(db_path)
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

    async def test_windows_path_title_renders_once(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        from tests.factory import NewItem, add_todo
        from todo.tui.app import TodoApp

        add_todo(items, NewItem(title=r"Sync C:\Users\alice\notes", tags=[r"win\path"]))
        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            title = str(app.query_one("#detail-title", Static).render())
            meta = str(app.query_one("#detail-meta", Static).render())
            assert r"Sync C:\Users\alice\notes" in title
            assert r"\\Users" not in title
            assert r"win\path" in meta

    async def test_confirm_dialog_shows_key_hints(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        """The app's own literal '[y] Yes   [n] No' hint was being eaten as
        markup, so the user saw no key labels at all."""
        from tests.factory import NewItem, add_todo
        from todo.tui.app import TodoApp

        add_todo(items, NewItem(title="item"))
        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            hint = str(app.screen.query_one("#confirm-hint", Label).render())
            assert "[y]" in hint
            assert "[n]" in hint
