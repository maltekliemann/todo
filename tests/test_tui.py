from __future__ import annotations

import contextlib
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from rich.text import Text
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Input, Label, OptionList, Static

from tests.factory import NewItem, add_blocker, add_todo
from todo.adapters.sqlite_dependency_store import SqliteDependencyStore
from todo.adapters.sqlite_item_store import SqliteItemStore
from todo.adapters.sqlite_project_store import SqliteProjectStore
from todo.domain.deadline import Deadline
from todo.domain.dependency_graph import DependencyGraph
from todo.domain.item_filter import ItemFilter
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.todo_item import TodoItem
from todo.exceptions import StorageError
from todo.tui.app import TodoApp
from todo.tui.edit_session import EditorSession
from todo.tui.list_view import TodoListView
from todo.tui.table import COLUMNS, is_separator


def _item_rows(table: DataTable) -> int:
    """Count rows in a TodoTable that represent actual items (skip separators)."""
    return sum(1 for row_key in table.rows if not is_separator(row_key.value))


@pytest.fixture()
def seeded(db_path: Path, items: SqliteItemStore) -> Path:
    add_todo(items, NewItem(title="Urgent task", priority=Priority.URGENT))
    add_todo(items, NewItem(title="High task", priority=Priority.HIGH))
    add_todo(items, NewItem(title="Backlog thing", status=Status.BACKLOG))
    return db_path


class TestBasics:
    async def test_app_launches(self, seeded: Path, items: SqliteItemStore) -> None:
        app = TodoApp(seeded)
        async with app.run_test():
            assert app.is_running
            table = app.query_one("#item-list", DataTable)
            # 3 seeded items (separators in table not counted)
            assert _item_rows(table) == 3

    async def test_quit_with_q(self, seeded: Path, items: SqliteItemStore) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.press("q")
            await pilot.pause()
        assert not app.is_running


class TestStatusNavigation:
    async def test_greater_than_advances_status(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Cursor starts on first row (Urgent task)
            await pilot.press("greater_than_sign")
            await pilot.pause()

            # Item #1 should now be in-progress
            item = items.get(1)
            assert item.status == Status.IN_PROGRESS

    async def test_less_than_moves_back(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            # First item is "todo" — move back to backlog
            await pilot.press("less_than_sign")
            await pilot.pause()

            item = items.get(1)
            assert item.status == Status.BACKLOG

    async def test_advance_to_done(self, seeded: Path, items: SqliteItemStore) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            # todo -> in-progress -> done
            await pilot.press("greater_than_sign")
            await pilot.pause()
            await pilot.press("greater_than_sign")
            await pilot.pause()

            item = items.get(1)
            assert item.status == Status.DONE
            assert item.done_at is not None


class TestPrdKeyBindings:
    """The PRD's key table: arrows and hjkl, alongside the < > pair."""

    @pytest.mark.parametrize("key", ["l", "right"])
    async def test_advances_status(
        self, seeded: Path, items: SqliteItemStore, key: str
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()
            assert items.get(1).status == Status.IN_PROGRESS

    @pytest.mark.parametrize("key", ["h", "left"])
    async def test_reverses_status(
        self, seeded: Path, items: SqliteItemStore, key: str
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()
            assert items.get(1).status == Status.BACKLOG

    async def test_j_and_k_move_the_selection(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            start = table.cursor_row
            await pilot.press("j")
            await pilot.pause()
            assert table.cursor_row > start
            await pilot.press("k")
            await pilot.pause()
            assert table.cursor_row == start

    async def test_shift_arrows_still_scroll_a_too_wide_table(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        """Binding the plain arrows to status took over DataTable's
        incremental horizontal scroll. A title wider than the terminal must
        still be readable from the keyboard, and scrolling must not mutate
        the item."""
        add_todo(items, NewItem(title="X" * 200))
        app = TodoApp(db_path)
        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert table.max_scroll_x > 0, "table is not actually scrollable"

            await pilot.press("shift+right")
            await pilot.pause()
            assert table.scroll_x > 0
            assert items.get(1).status == Status.TODO

            scrolled = table.scroll_x
            await pilot.press("shift+left")
            await pilot.pause()
            assert table.scroll_x < scrolled
            assert items.get(1).status == Status.TODO

    async def test_j_skips_separator_rows(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        """j must behave exactly like down, separators included."""
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            for _ in range(table.row_count):
                await pilot.press("j")
                await pilot.pause()
                key = table.coordinate_to_cell_key(
                    Coordinate(table.cursor_row, 0)
                ).row_key.value
                assert not is_separator(key)


class TestBlockerPicker:
    """Choosing a blocker must not require remembering an id: the dialog
    lists the candidates and the search box narrows them."""

    @pytest.fixture()
    def several(self, items: SqliteItemStore, db_path: Path) -> Path:
        add_todo(items, NewItem(title="Write the migration"))
        add_todo(items, NewItem(title="Deploy the gateway"))
        add_todo(items, NewItem(title="Rotate the certificates"))
        add_todo(items, NewItem(title="Deploy the frontend"))
        return db_path

    @staticmethod
    def _options(app) -> list[str]:
        from textual.widgets import OptionList

        option_list = app.screen.query_one("#block-options", OptionList)
        return [str(option.prompt) for option in option_list._options]

    async def test_lists_every_other_item(self, several: Path) -> None:
        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            options = self._options(app)
            assert len(options) == 3
            assert all("Write the migration" not in o for o in options), options
            assert any("Deploy the gateway" in o for o in options)

    async def test_search_narrows_the_list(self, several: Path) -> None:
        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            for ch in "deploy":
                await pilot.press(ch)
            await pilot.pause()
            options = self._options(app)
            assert len(options) == 2
            assert all("Deploy" in o for o in options), options

    async def test_search_also_matches_the_id(self, several: Path) -> None:
        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            options = self._options(app)
            assert len(options) == 1
            assert "Rotate the certificates" in options[0]

    async def test_enter_on_the_highlighted_candidate_blocks(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, several: Path
    ) -> None:
        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            for ch in "gateway":
                await pilot.press(ch)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert dependencies.load().blockers_of(1) == [2]

    async def test_down_moves_the_highlight_before_choosing(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, several: Path
    ) -> None:
        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            for ch in "deploy":
                await pilot.press(ch)
            await pilot.pause()
            await pilot.press("down")
            await pilot.press("enter")
            await pilot.pause()
            assert dependencies.load().blockers_of(1) == [4]

    async def test_choosing_an_existing_blocker_removes_it(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, several: Path
    ) -> None:
        add_blocker(items, dependencies, 1, [2])
        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            options = self._options(app)
            assert options[0].startswith("✓"), options
            await pilot.press("enter")
            await pilot.pause()
            assert dependencies.load().blockers_of(1) == []

    async def test_current_blockers_sort_first(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, several: Path
    ) -> None:
        add_blocker(items, dependencies, 1, [4])
        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            options = self._options(app)
            assert "Deploy the frontend" in options[0]
            assert options[0].startswith("✓")
            assert not any(o.startswith("✓") for o in options[1:])

    async def test_the_list_has_focus_and_a_highlighted_row(
        self, several: Path
    ) -> None:
        """It is a menu: it opens on the list, with a row under the cursor.
        Searching is a filter, never the way in."""
        from textual.widgets import OptionList

        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            options = app.screen.query_one("#block-options", OptionList)
            assert app.focused is options
            assert options.highlighted == 0

    async def test_the_search_box_never_takes_focus(self, several: Path) -> None:
        from textual.widgets import OptionList

        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            for ch in "deploy":
                await pilot.press(ch)
            await pilot.pause()
            assert app.focused is app.screen.query_one("#block-options", OptionList)
            assert app.screen.query_one("#block-search", Input).value == "deploy"

    async def test_arrows_walk_the_menu_without_typing(self, several: Path) -> None:
        from textual.widgets import OptionList

        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            options = app.screen.query_one("#block-options", OptionList)
            await pilot.press("down")
            await pilot.pause()
            assert options.highlighted == 1
            await pilot.press("up")
            await pilot.pause()
            assert options.highlighted == 0

    async def test_enter_chooses_the_highlighted_row_with_no_typing(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, several: Path
    ) -> None:
        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert dependencies.load().blockers_of(1) == [2]

    async def test_backspace_widens_the_filter(self, several: Path) -> None:
        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            for ch in "deploy":
                await pilot.press(ch)
            await pilot.pause()
            assert len(self._options(app)) == 2
            for _ in range(6):
                await pilot.press("backspace")
            await pilot.pause()
            assert len(self._options(app)) == 3
            assert app.screen.query_one("#block-search", Input).value == ""

    async def test_an_exactly_typed_id_wins_over_a_title_match(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, db_path: Path
    ) -> None:
        """The dialog this replaced acted on the id you typed. Typing an id
        must still designate that item, not a title that happens to contain
        the digit."""
        add_todo(items, NewItem(title="Ship the release"))
        add_todo(items, NewItem(title="Fix bug 3 in parser"))
        add_todo(items, NewItem(title="Rotate certificates"))
        app = TodoApp(db_path)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            assert self._options(app)[0].endswith("Rotate certificates")
            await pilot.press("enter")
            await pilot.pause()
            assert dependencies.load().blockers_of(1) == [3]

    async def test_a_dash_query_is_a_search_not_a_removal(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Main"))
        add_todo(items, NewItem(title="Ship v1"))
        add_todo(items, NewItem(title="Fix bug-2 crash"))
        add_blocker(items, dependencies, 1, [2])
        app = TodoApp(db_path)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("minus", "2")
            await pilot.pause()
            assert self._options(app) == ["  #3  Fix bug-2 crash"]
            await pilot.press("enter")
            await pilot.pause()
            # The #2 relation is untouched and #3 was added.
            assert dependencies.load().blockers_of(1) == [2, 3]

    async def test_a_non_decimal_digit_does_not_crash(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        """'²'.isdigit() is True but int('²') raises; a German keyboard
        produces it with AltGr+2."""
        add_todo(items, NewItem(title="Main"))
        add_todo(items, NewItem(title="Other"))
        app = TodoApp(db_path)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            app.screen.query_one("#block-search", Input).value = "-²"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.is_running

    async def test_clicking_a_candidate_chooses_it(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, several: Path
    ) -> None:
        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            await pilot.click("#block-options", offset=(2, 0))
            await pilot.pause()
            assert dependencies.load().blockers_of(1) == [2]

    async def test_a_new_search_clears_the_previous_error(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, several: Path
    ) -> None:
        add_blocker(items, dependencies, 2, [1])  # a cycle awaits anyone choosing #2
        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            for ch in "gateway":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()
            assert str(app.screen.query_one("#block-error", Label).render())

            app.screen.query_one("#block-search", Input).value = "certificates"
            await pilot.pause()
            assert str(app.screen.query_one("#block-error", Label).render()) == ""

    @pytest.mark.parametrize("size", [(80, 20), (80, 24), (100, 40)])
    async def test_the_dialog_fits_the_terminal(
        self, several: Path, size: tuple[int, int]
    ) -> None:
        """The inline error is the dialog's whole error strategy; if the
        box overflows a short terminal, a rejected choice looks like a
        keypress that did nothing."""
        app = TodoApp(several)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            height = size[1]
            for widget_id in ("#block-search", "#block-options", "#block-error"):
                region = app.screen.query_one(widget_id).region
                assert region.bottom <= height, f"{widget_id} at {region}"

    async def test_a_cycle_reports_inline_and_stays_open(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, several: Path
    ) -> None:
        from todo.tui.blockers import BlockDialog

        add_blocker(items, dependencies, 2, [1])  # #2 already waits on #1
        app = TodoApp(several)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            await pilot.press("b")  # blockers of #1
            await pilot.pause()
            for ch in "gateway":
                await pilot.press(ch)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, BlockDialog)
            error = str(app.screen.query_one("#block-error", Label).render())
            assert error
            assert dependencies.load().blockers_of(1) == []


class TestDepsColumn:
    """Dependencies belong on the row, not only in the detail pane: '←' is
    what this item waits on, '→' is how many wait on it."""

    @pytest.fixture()
    def linked(
        self, dependencies: SqliteDependencyStore, items: SqliteItemStore, db_path: Path
    ) -> Path:
        for n in range(1, 7):
            add_todo(items, NewItem(title=f"Task {n}"))
        add_blocker(items, dependencies, 1, [2])  # 1 waits on 2
        add_blocker(items, dependencies, 1, [3])  # 1 waits on 3
        add_blocker(items, dependencies, 4, [2])  # 4 waits on 2
        add_blocker(items, dependencies, 5, [2])  # 5 waits on 2
        return db_path

    @staticmethod
    def _deps_cell(table: DataTable, title: str) -> str:
        column = COLUMNS.index("Deps")
        for row in range(table.row_count):
            cells = table.get_row_at(row)
            if any(title == str(c) for c in cells):
                return str(cells[column])
        raise AssertionError(f"no row titled {title!r}")

    async def test_shows_blocker_ids_and_blocked_count(self, linked: Path) -> None:
        app = TodoApp(linked)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert self._deps_cell(table, "\U0001f6ab Task 1") == "←#2,#3"
            assert self._deps_cell(table, "Task 2") == "→3"
            assert self._deps_cell(table, "Task 3") == "→1"
            assert self._deps_cell(table, "Task 6") == ""

    async def test_a_done_blocker_is_not_something_you_wait_on(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, linked: Path
    ) -> None:
        """The row drops its 🚫 marker the moment its last blocker is done;
        the Deps cell must agree instead of still claiming a wait."""
        from tests.factory import set_status

        set_status(items, dependencies, 2, Status.DONE)
        set_status(items, dependencies, 3, Status.DONE)
        app = TodoApp(linked)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert dependencies.load().is_blocked(1, items.done_ids()) is False
            assert self._deps_cell(table, "Task 1") == ""

    async def test_shows_both_directions_at_once(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, linked: Path
    ) -> None:
        # #3 already blocks #1; make it wait on #6 too, so its cell has to
        # carry both halves.
        add_blocker(items, dependencies, 3, [6])
        app = TodoApp(linked)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert self._deps_cell(table, "\U0001f6ab Task 3") == "←#6 →1"
            assert self._deps_cell(table, "\U0001f6ab Task 4") == "←#2"

    async def test_long_blocker_lists_are_capped(
        self, dependencies: SqliteDependencyStore, items: SqliteItemStore, db_path: Path
    ) -> None:
        for n in range(1, 7):
            add_todo(items, NewItem(title=f"Task {n}"))
        for blocker in (2, 3, 4, 5, 6):
            add_blocker(items, dependencies, 1, [blocker])
        app = TodoApp(db_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            cell = self._deps_cell(table, "\U0001f6ab Task 1")
            assert cell == "←#2,#3+3", cell


class TestTagsColumn:
    """Tags belong on the row: they are how a list is scanned, and the
    detail pane only shows them for the one item under the cursor."""

    @staticmethod
    def _tags_cell(table: DataTable, title: str) -> str:
        column = COLUMNS.index("Tags")
        for row in range(table.row_count):
            cells = table.get_row_at(row)
            if any(title == str(c) for c in cells):
                return str(cells[column])
        raise AssertionError(f"no row titled {title!r}")

    async def test_shows_tags_sorted_and_nothing_when_bare(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Tagged", tags=frozenset({"web", "auth"})))
        add_todo(items, NewItem(title="Bare"))
        app = TodoApp(db_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert self._tags_cell(table, "Tagged") == "auth, web"
            assert self._tags_cell(table, "Bare") == ""

    async def test_the_cap_is_width_not_count(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        """Five short tags fit where two long ones do not: what squeezes
        the title is columns, so columns are what the cap measures."""
        add_todo(
            items,
            NewItem(title="Task", tags=frozenset({"api", "cli", "db", "ui", "web"})),
        )
        add_todo(
            items,
            NewItem(
                title="Wide",
                tags=frozenset({"backend-infrastructure", "frontend"}),
            ),
        )
        app = TodoApp(db_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert self._tags_cell(table, "Task") == "api, cli, db, ui, web"
            assert self._tags_cell(table, "Wide") == "backend-infrastructure +1"

    async def test_a_tag_wider_than_the_budget_is_cut_visibly(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        """A bare '+n' would name no tag at all, so the overwide tag shows
        as much of itself as the budget allows, ellipsis marking the cut."""
        add_todo(
            items,
            NewItem(
                title="Task",
                tags=frozenset({"a-single-tag-longer-than-the-budget", "tiny"}),
            ),
        )
        app = TodoApp(db_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert self._tags_cell(table, "Task") == "a-single-tag-longer-tha… +1"


class TestStayCursorMode:
    """Stay mode exists so a run of items can be moved without chasing the
    cursor. Holding a visual row index is not enough: a status step re-sorts
    the moved item to the top of its new group, which is often the row the
    cursor is still sitting on."""

    @pytest.fixture()
    def five_items(self, items: SqliteItemStore, db_path: Path) -> Path:
        for n in range(1, 6):
            add_todo(items, NewItem(title=f"Task {n}"))
        return db_path

    async def test_the_mode_is_named_for_what_it_does(self, five_items: Path) -> None:
        """It advances to the next item; calling it "stay on row" described
        the behaviour it replaced."""
        app = TodoApp(five_items)
        notices: list[str] = []
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            view.notify = lambda msg, **kw: notices.append(str(msg))  # type: ignore[method-assign]
            await pilot.press("full_stop")
            await pilot.pause()
            assert notices and "advance" in notices[0].lower()
            assert "stay" not in notices[0].lower()

            status = str(app.query_one("#search-status", Static).render())
            assert "advance" in status.lower()

    async def test_status_steps_walk_down_the_list(
        self, items: SqliteItemStore, five_items: Path
    ) -> None:
        app = TodoApp(five_items)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("full_stop")  # stay on row
            await pilot.pause()
            for _ in range(3):
                await pilot.press("greater_than_sign")
                await pilot.pause()

            moved = [i.id for i in items.find(ItemFilter(include_done=True))]
            in_progress = sorted(
                i.id
                for i in items.find(ItemFilter(include_done=True))
                if i.status == Status.IN_PROGRESS
            )
            assert in_progress == [1, 2, 3], moved

    async def test_done_walks_down_the_list(
        self, items: SqliteItemStore, five_items: Path
    ) -> None:
        app = TodoApp(five_items)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("full_stop")
            await pilot.pause()
            for _ in range(3):
                await pilot.press("d")
                await pilot.pause()

            done = sorted(
                i.id
                for i in items.find(ItemFilter(include_done=True))
                if i.status == Status.DONE
            )
            assert done == [1, 2, 3]

    async def test_follow_mode_keeps_the_cursor_on_the_moved_item(
        self, items: SqliteItemStore, five_items: Path
    ) -> None:
        """The default mode must be untouched: the cursor tracks the item."""
        app = TodoApp(five_items)
        async with app.run_test() as pilot:
            await pilot.pause()
            for _ in range(3):
                await pilot.press("greater_than_sign")
                await pilot.pause()

            item = items.get(1)
            assert item.status == Status.DONE  # todo -> in-progress -> done
            assert all(
                i.status == Status.TODO
                for i in items.find(ItemFilter(include_done=True))
                if i.id != 1
            )


class TestFooterFits:
    """The footer is one row and does not wrap: anything past the right
    edge is invisible, and the tail is where the least-known keys live."""

    @pytest.mark.parametrize("width", [80, 100, 120])
    async def test_footer_fits_the_terminal(
        self, seeded: Path, items: SqliteItemStore, width: int
    ) -> None:
        from textual.widgets import Footer

        app = TodoApp(seeded)
        async with app.run_test(size=(width, 24)) as pilot:
            await pilot.pause()
            footer = app.query_one(Footer)
            assert footer.virtual_size.width <= width, (
                f"{footer.virtual_size.width} columns of footer in {width}"
            )

    async def test_special_keys_show_their_symbol(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        """'greater_than_sign' is a key name, not something to show a user."""
        from textual.widgets._footer import FooterKey

        app = TodoApp(seeded)
        async with app.run_test(size=(120, 24)) as pilot:
            await pilot.pause()
            displays = {k.key: k.key_display for k in app.query(FooterKey)}
            assert displays.get("greater_than_sign") == ">"
            assert displays.get("less_than_sign") == "<"
            assert displays.get("full_stop") == "."
            assert displays.get("slash") == "/"


class TestPriorityAndDeadlineStyling:
    """PRD § Priority Color Coding and § Deadline Warnings: the TUI table
    must flag priority and deadline proximity, not render everything flat."""

    @pytest.fixture()
    def styled_storage(self, items: SqliteItemStore, db_path: Path) -> Path:
        from datetime import date, timedelta

        add_todo(items, NewItem(title="Urgent one", priority=Priority.URGENT))
        add_todo(items, NewItem(title="High one", priority=Priority.HIGH))
        add_todo(items, NewItem(title="Medium one", priority=Priority.MEDIUM))
        add_todo(items, NewItem(title="Low one", priority=Priority.LOW))
        add_todo(
            items, NewItem(title="Overdue", deadline=date.today() - timedelta(days=3))
        )
        add_todo(
            items, NewItem(title="Soon", deadline=date.today() + timedelta(days=1))
        )
        add_todo(
            items, NewItem(title="Later", deadline=date.today() + timedelta(days=90))
        )
        return db_path

    @staticmethod
    def _cells(table: DataTable, title: str) -> list[Text]:
        for row in range(table.row_count):
            cells = table.get_row_at(row)
            if any(str(c) == title for c in cells):
                return [c for c in cells if isinstance(c, Text)]
        raise AssertionError(f"no row titled {title!r}")

    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Urgent one", "bold red"),
            ("High one", "dark_orange"),
            ("Medium one", ""),
            ("Low one", "dim"),
        ],
    )
    async def test_priority_cell_is_coloured(
        self, styled_storage: Path, title: str, expected: str
    ) -> None:
        app = TodoApp(styled_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            pri_cell = self._cells(table, title)[COLUMNS.index("Pri")]
            assert str(pri_cell.style) == expected

    @pytest.mark.parametrize(
        ("title", "expected"),
        [("Overdue", "bold red"), ("Soon", "yellow"), ("Later", "dim")],
    )
    async def test_deadline_cell_is_coloured(
        self, styled_storage: Path, title: str, expected: str
    ) -> None:
        app = TodoApp(styled_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            deadline_cell = self._cells(table, title)[COLUMNS.index("Deadline")]
            assert str(deadline_cell.style) == expected

    async def test_blocked_row_stays_dim_over_its_priority_colour(
        self,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
        styled_storage: Path,
    ) -> None:
        add_blocker(items, dependencies, 1, [2])  # #1 (urgent) blocked by #2
        app = TodoApp(styled_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            cells = self._cells(table, "\U0001f6ab Urgent one")
            assert all("dim" in str(c.style) for c in cells)
            assert "red" in str(cells[COLUMNS.index("Pri")].style)


class TestDoneAction:
    async def test_d_marks_done(self, seeded: Path, items: SqliteItemStore) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()

            item = items.get(1)
            assert item.status == Status.DONE


class TestDelete:
    async def test_x_opens_confirm_dialog(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            # Confirm dialog should be on screen
            from todo.tui.dialogs import ConfirmDialog

            assert isinstance(app.screen, ConfirmDialog)

    async def test_delete_y_confirms(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()

            # Item 1 should be gone
            from todo.exceptions import NotFoundError

            with pytest.raises(NotFoundError):
                items.get(1)

    async def test_delete_n_cancels(self, seeded: Path, items: SqliteItemStore) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            # Item 1 should still exist
            assert items.get(1).id == 1


class TestNewDialog:
    async def test_n_opens_new_dialog(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            from todo.tui.dialogs import NewItemDialog

            assert isinstance(app.screen, NewItemDialog)

    async def test_escape_cancels_new(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            # Back to list view, no new item
            count_before = len(items.find(ItemFilter(include_done=True)))
            assert count_before == 3

    async def test_a_new_item_lands_under_the_cursor(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        """The next action after creating is almost always about the new
        item, so the refresh that follows the dialog selects it."""
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            for ch in "Fresh":
                await pilot.press(ch)
            # Title → Priority → Deadline → Tags → Blocked by → Body →
            # Save, all defaults.
            for _ in range(6):
                await pilot.press("enter")
                await pilot.pause()

            new_item = next(
                i
                for i in items.find(ItemFilter(include_done=True))
                if i.title == "Fresh"
            )
            table = app.query_one("#item-list", DataTable)
            key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            assert key == str(new_item.id)

    async def test_body_and_blockers_can_be_set_at_creation(
        self,
        seeded: Path,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
    ) -> None:
        """Every field the item has is settable where the item is made —
        and blockers are picked from a menu, never typed as ids."""
        from todo.tui.blockers import BlockerPicker

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            for ch in "Born blocked":
                await pilot.press(ch)
            # Title → Priority → Deadline → Tags, all defaults.
            for _ in range(4):
                await pilot.press("enter")
                await pilot.pause()

            # Space opens the picker; an exactly typed id designates the
            # item, and Enter toggles its mark.
            await pilot.press("space")
            await pilot.pause()
            assert isinstance(app.screen, BlockerPicker)
            await pilot.press("1")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("backspace")
            await pilot.press("3")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            # Back on the form: Enter walks on to the body, where Space
            # opens $EDITOR — faked here — and Enter creates the item.
            await pilot.press("enter")
            await pilot.pause()

            class FakeSession:
                def __init__(self, view: object, items: object) -> None:
                    pass

                def run_text(self, text: str) -> str:
                    return "waits on setup"

            import todo.tui.dialogs as dialogs_module

            with monkeypatched(dialogs_module, "EditorSession", FakeSession):
                await pilot.press("space")
                await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            new_item = next(
                i
                for i in items.find(ItemFilter(include_done=True))
                if i.title == "Born blocked"
            )
            assert new_item.body == "waits on setup"
            assert dependencies.load().blockers_of(new_item.id) == [
                ItemId(1),
                ItemId(3),
            ]

    async def test_a_reopened_picker_starts_from_what_was_chosen(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        """The field remembers its selection: opening the picker again
        shows the mark, and toggling it off clears the choice."""
        from todo.tui.dialogs import BlockerField

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            for ch in "Fickle":
                await pilot.press(ch)
            for _ in range(4):
                await pilot.press("enter")
                await pilot.pause()

            # Pick #1, close.
            await pilot.press("space")
            await pilot.pause()
            await pilot.press("1")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.press("escape")
            await pilot.pause()
            field = app.screen.query_one("#new-blockers", BlockerField)
            assert field.value == [ItemId(1)]

            # Reopen: the marked row leads the menu; Enter un-marks it.
            await pilot.press("space")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.press("escape")
            await pilot.pause()
            assert field.value == []

    async def test_a_vanished_blocker_creates_nothing(
        self,
        seeded: Path,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
    ) -> None:
        """Picked from the list, deleted by another process before save:
        the whole form fails — no half-made item that exists but does not
        wait on what it was told to wait on."""
        from tests.factory import delete_todo

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            for ch in "Doomed":
                await pilot.press(ch)
            for _ in range(4):
                await pilot.press("enter")
                await pilot.pause()
            await pilot.press("space")
            await pilot.pause()
            await pilot.press("1")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.press("escape")
            await pilot.pause()

            delete_todo(items, dependencies, 1)

            await pilot.press("enter")  # blockers -> body
            await pilot.pause()
            await pilot.press("enter")  # body (skip) -> save attempt
            await pilot.pause()

            error = str(app.screen.query_one("#dialog-error", Label).render())
            assert "#1" in error
            assert not any(
                i.title == "Doomed" for i in items.find(ItemFilter(include_done=True))
            )

    async def test_enter_advances_through_fields_then_saves(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        """Step priority up with right arrow, then Enter through the rest to save."""
        from todo.tui.dialogs import AdvancingSelect

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            # Title -> Priority
            for ch in "From dialog":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            # Priority: medium -> high (right arrow), then Enter to advance
            await pilot.press("right")
            await pilot.pause()
            assert (
                app.screen.query_one("#new-priority", AdvancingSelect).value == "high"
            )
            await pilot.press("enter")
            await pilot.pause()

            # Deadline (skip) -> Tags
            await pilot.press("enter")
            await pilot.pause()

            # Tags -> Blocked by
            for ch in "demo":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            # Blocked by (skip) -> Body, Body (skip) -> Save
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            items = items.find(ItemFilter(include_done=True))
            new_item = next(i for i in items if i.title == "From dialog")
            assert new_item.priority == Priority.HIGH
            assert "demo" in new_item.tags
            assert new_item.deadline is None

    async def test_default_priority_when_kept(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        """Hitting Enter without changing the priority keeps the default 'medium'."""
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            for ch in "Default pri":
                await pilot.press(ch)
            # Title → Priority (default medium) → Deadline → Tags →
            # Blocked by → Body → Save
            for _ in range(6):
                await pilot.press("enter")
                await pilot.pause()

            new_item = next(
                i
                for i in items.find(ItemFilter(include_done=True))
                if i.title == "Default pri"
            )
            assert new_item.priority == Priority.MEDIUM

    async def test_priority_left_right_steps_clamped(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        """Right increases priority (toward urgent); Left decreases it (toward low).
        Both clamp at the ends — no wraparound."""
        from todo.tui.dialogs import AdvancingSelect

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            await pilot.press("X")
            await pilot.press("enter")
            await pilot.pause()

            select = app.screen.query_one("#new-priority", AdvancingSelect)
            assert select.value == "medium"

            # Step up to urgent
            await pilot.press("right")
            await pilot.pause()
            assert select.value == "high"
            await pilot.press("right")
            await pilot.pause()
            assert select.value == "urgent"
            await pilot.press("right")  # clamp
            await pilot.pause()
            assert select.value == "urgent"

            # Step down to low
            await pilot.press("left")
            await pilot.pause()
            assert select.value == "high"
            await pilot.press("left")
            await pilot.pause()
            assert select.value == "medium"
            await pilot.press("left")
            await pilot.pause()
            assert select.value == "low"
            await pilot.press("left")  # clamp
            await pilot.pause()
            assert select.value == "low"

    async def test_arrow_keys_navigate_all_fields(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        """Down advances and Up retreats on every field in the dialog."""
        from textual.widgets import Input

        from todo.tui.dialogs import AdvancingSelect, BlockerField, BodyField

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            # type a title so down can advance past validation
            for ch in "Nav":
                await pilot.press(ch)

            # Title -> Priority
            await pilot.press("down")
            await pilot.pause()
            assert app.screen.query_one("#new-priority", AdvancingSelect).has_focus

            # Priority -> Deadline
            await pilot.press("down")
            await pilot.pause()
            assert app.screen.query_one("#new-deadline", Input).has_focus

            # Deadline -> Tags
            await pilot.press("down")
            await pilot.pause()
            assert app.screen.query_one("#new-tags", Input).has_focus

            # Tags -> Blocked by
            await pilot.press("down")
            await pilot.pause()
            assert app.screen.query_one("#new-blockers", BlockerField).has_focus

            # Blocked by -> Body
            await pilot.press("down")
            await pilot.pause()
            assert app.screen.query_one("#new-body", BodyField).has_focus

            # Body <- Blocked by (up)
            await pilot.press("up")
            await pilot.pause()
            assert app.screen.query_one("#new-blockers", BlockerField).has_focus

            # Blocked by <- Tags
            await pilot.press("up")
            await pilot.pause()
            assert app.screen.query_one("#new-tags", Input).has_focus

            # Tags <- Deadline
            await pilot.press("up")
            await pilot.pause()
            assert app.screen.query_one("#new-deadline", Input).has_focus

            # Deadline <- Priority
            await pilot.press("up")
            await pilot.pause()
            assert app.screen.query_one("#new-priority", AdvancingSelect).has_focus

            # Priority <- Title
            await pilot.press("up")
            await pilot.pause()
            assert app.screen.query_one("#new-title", Input).has_focus

    async def test_priority_down_advances_to_deadline(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        """Down on the priority field advances to deadline (does not open dropdown)."""
        from textual.widgets import Input

        from todo.tui.dialogs import AdvancingSelect

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            await pilot.press("X")
            await pilot.press("enter")
            await pilot.pause()

            select = app.screen.query_one("#new-priority", AdvancingSelect)
            assert select.has_focus
            assert not select.expanded

            await pilot.press("down")
            await pilot.pause()

            assert app.screen.query_one("#new-deadline", Input).has_focus
            assert not select.expanded

    async def test_invalid_date_does_not_advance(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        """Bad date keeps focus on deadline; no bouncing to tags or save."""
        from textual.widgets import Input

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            for ch in "Bad date":
                await pilot.press(ch)
            await pilot.press("enter")  # title -> priority
            await pilot.pause()
            await pilot.press("enter")  # priority -> deadline
            await pilot.pause()

            # Type an invalid date
            for ch in "not-a-date":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            # Focus must stay on deadline
            assert app.screen.query_one("#new-deadline", Input).has_focus
            # No item was saved
            assert not any(
                i.title == "Bad date" for i in items.find(ItemFilter(include_done=True))
            )
            # An error message is shown
            error_label = app.screen.query_one("#dialog-error", Label)
            assert "date" in str(error_label.render()).lower()

    async def test_empty_title_does_not_advance(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        """Pressing Enter with no title keeps focus on the title field."""
        from textual.widgets import Input

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            await pilot.press("enter")  # empty title
            await pilot.pause()

            assert app.screen.query_one("#new-title", Input).has_focus
            error_label = app.screen.query_one("#dialog-error", Label)
            assert "title" in str(error_label.render()).lower()


class TestFilters:
    @pytest.fixture()
    def tagged_storage(self, items: SqliteItemStore, db_path: Path) -> Path:
        add_todo(
            items,
            NewItem(
                title="Backend work",
                priority=Priority.URGENT,
                tags=frozenset({"backend"}),
            ),
        )
        add_todo(items, NewItem(title="Frontend work", tags=frozenset({"frontend"})))
        add_todo(items, NewItem(title="Untagged", priority=Priority.URGENT))
        return db_path

    async def test_priority_filter_toggles(self, tagged_storage: Path) -> None:
        app = TodoApp(tagged_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert _item_rows(table) == 3

            await pilot.press("1")  # urgent only
            await pilot.pause()
            assert _item_rows(table) == 2

            await pilot.press("1")  # same key again clears
            await pilot.pause()
            assert _item_rows(table) == 3

    async def test_tag_filter_cycles(self, tagged_storage: Path) -> None:
        app = TodoApp(tagged_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)

            await pilot.press("t")  # first tag (alphabetical: backend)
            await pilot.pause()
            assert _item_rows(table) == 1

            await pilot.press("t")  # frontend
            await pilot.pause()
            assert _item_rows(table) == 1

            await pilot.press("t")  # cycles back to no filter
            await pilot.pause()
            assert _item_rows(table) == 3

    async def test_zero_clears_all_filters(self, tagged_storage: Path) -> None:
        app = TodoApp(tagged_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)

            await pilot.press("1")
            await pilot.press("t")
            await pilot.pause()
            assert _item_rows(table) == 1

            await pilot.press("0")
            await pilot.pause()
            assert _item_rows(table) == 3

    async def test_status_line_shows_filters(self, tagged_storage: Path) -> None:
        app = TodoApp(tagged_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("1")
            await pilot.press("t")
            await pilot.pause()
            status = str(app.query_one("#search-status", Static).render())
            assert "urgent" in status
            assert "backend" in status


class TestCursorMode:
    @pytest.fixture()
    def three_todos(self, items: SqliteItemStore, db_path: Path) -> Path:
        add_todo(items, NewItem(title="First"))
        add_todo(items, NewItem(title="Second"))
        add_todo(items, NewItem(title="Third"))
        return db_path

    def _selected_id(self, app: TodoApp) -> object:
        view = app.query_one(TodoListView)
        return view._selected_item_id()

    async def test_follow_mode_default_follows_item(self, three_todos: Path) -> None:
        app = TodoApp(three_todos)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert self._selected_id(app) == 1
            await pilot.press("d")  # complete #1; cursor follows into done group
            await pilot.pause()
            assert self._selected_id(app) == 1

    async def test_stay_mode_keeps_row_for_cleanup(self, three_todos: Path) -> None:
        app = TodoApp(three_todos)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("full_stop")  # switch to stay mode
            await pilot.pause()
            assert self._selected_id(app) == 1

            await pilot.press("d")  # #1 done; cursor stays -> now on #2
            await pilot.pause()
            assert self._selected_id(app) == 2

            await pilot.press("d")  # #2 done; now on #3
            await pilot.pause()
            assert self._selected_id(app) == 3

            await pilot.press("d")  # #3 done; only the done section remains
            await pilot.pause()
            # Rows now: [done separator, #1, #2, #3]. The cursor was on
            # visual row 1 (where #3 sat under the todo separator), so stay
            # mode keeps row 1 -> item #1, the first done item.
            assert self._selected_id(app) == 1

    async def test_toggle_back_restores_follow(self, three_todos: Path) -> None:
        app = TodoApp(three_todos)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("full_stop")
            await pilot.press("full_stop")  # back to follow
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            assert self._selected_id(app) == 1

    async def test_stay_mode_at_last_row(self, three_todos: Path) -> None:
        app = TodoApp(three_todos)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("full_stop")
            await pilot.press("down", "down")  # move to #3 (last item)
            await pilot.pause()
            assert self._selected_id(app) == 3
            await pilot.press("d")
            await pilot.pause()
            # Rows now: [todo sep, #1, #2, done sep, #3]. The cursor was on
            # visual row 3; that row is now the done separator, so the
            # separator-skip moves it down to #3 — the item just completed.
            assert self._selected_id(app) == 3


class TestSearch:
    async def test_slash_opens_search(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash")
            await pilot.pause()
            from todo.tui.dialogs import SearchDialog

            assert isinstance(app.screen, SearchDialog)

    async def test_search_filters_list(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash")
            await pilot.pause()
            # Type "urgent"
            for ch in "urgent":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            table = app.query_one("#item-list", DataTable)
            # Only the urgent task remains
            assert _item_rows(table) == 1

    async def test_escape_clears_search(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Apply a search
            await pilot.press("slash")
            await pilot.pause()
            for ch in "urgent":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()
            assert _item_rows(app.query_one("#item-list", DataTable)) == 1

            # Clear
            await pilot.press("escape")
            await pilot.pause()
            assert _item_rows(app.query_one("#item-list", DataTable)) == 3


class TestDetailPanel:
    async def test_shows_detail_for_selected_row(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            title = app.query_one("#detail-title", Static)
            assert "Urgent task" in str(title.render())

    async def test_arrow_down_updates_detail(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            title = app.query_one("#detail-title", Static)
            assert "High task" in str(title.render())

    async def test_the_pane_never_changes_size(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        """Fixed, never grown to content: a pane that swells under a long
        body squeezes the table until it covers the cursor row, and a
        preview that resizes on every cursor move is its own irritation."""
        add_todo(items, NewItem(title="Small"))
        add_todo(items, NewItem(title="Huge", body="line\n" * 40))
        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            pane = app.query_one("#detail-panel")
            table = app.query_one("#item-list", DataTable)
            pane_height, table_height = pane.region.height, table.region.height

            await pilot.press("down")
            await pilot.pause()
            assert "Huge" in str(app.query_one("#detail-title", Static).render())
            assert pane.region.height == pane_height == 13
            assert table.region.height == table_height


class TestOpenItem:
    """One screen for reading an item and for changing it."""

    async def test_i_opens_the_item_screen(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        from todo.tui.item_screen import ItemScreen

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            assert isinstance(app.screen, ItemScreen)

    async def test_e_opens_the_item_screen(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        """The key that used to drop straight into $EDITOR now opens the
        same screen as 'i': there is one way to open an item."""
        from todo.tui.item_screen import ItemScreen

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, ItemScreen)

    async def test_enter_opens_the_item_screen(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        from todo.tui.item_screen import ItemScreen

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, ItemScreen)

    async def test_the_whole_body_is_there_to_scroll(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        """The screen replaced a full-screen read-only view; a long body
        must still be reachable, not clipped away."""
        from todo.tui.item_screen import ItemScreen

        long_body = "\n".join(f"line {i}" for i in range(40))
        add_todo(items, NewItem(title="Has long body", body=long_body))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            assert isinstance(app.screen, ItemScreen)

            rendered = str(app.screen.query_one("#item-body", Static).render())
            assert "line 0" in rendered
            assert "line 39" in rendered

    async def test_escape_closes_it(self, seeded: Path, items: SqliteItemStore) -> None:
        from todo.tui.item_screen import ItemScreen

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            assert isinstance(app.screen, ItemScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ItemScreen)


class TestStatusGroups:
    async def test_separator_per_status(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        """A separator row appears for each non-empty status group."""
        add_todo(items, NewItem(title="todo 1"))  # default status: todo
        add_todo(items, NewItem(title="backlog 1", status=Status.BACKLOG))
        add_todo(items, NewItem(title="in-progress 1", status=Status.IN_PROGRESS))
        add_todo(items, NewItem(title="done 1", status=Status.DONE))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            separator_keys = [
                row_key.value for row_key in table.rows if is_separator(row_key.value)
            ]
            # One separator per status, in display order
            assert separator_keys == [
                "__sep_in-progress",
                "__sep_todo",
                "__sep_backlog",
                "__sep_done",
            ]

    async def test_arrow_down_skips_separators(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        """Pressing down on the last item of a group skips the next separator."""
        add_todo(items, NewItem(title="alpha"))  # todo
        add_todo(items, NewItem(title="bravo", status=Status.BACKLOG))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Cursor lands on the first item ("alpha").
            title = app.query_one("#detail-title", Static)
            assert "alpha" in str(title.render())
            # Pressing down should skip the backlog separator and land on "bravo".
            await pilot.press("down")
            await pilot.pause()
            assert "bravo" in str(title.render())


class TestExternalChangePolling:
    """The TUI should pick up changes made via the CLI (or any other process)."""


class TestBlocking:
    async def test_blocked_marker_appears_in_list(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, db_path: Path
    ) -> None:
        """An actively blocked item shows the crane marker in its title cell."""
        from tests.factory import add_blocker

        add_todo(items, NewItem(title="Blocked item"))  # id 1
        add_todo(items, NewItem(title="Blocker item"))  # id 2
        add_blocker(items, dependencies, 1, [2])  # #1 blocked by #2

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)

            def _title_cell(item_id: int) -> str:
                row_index = table.get_row_index(str(item_id))
                return str(table.get_row_at(row_index)[3])

            blocked_title = _title_cell(1)
            assert "\U0001f6ab" in blocked_title
            assert "Blocked item" in blocked_title
            # The blocker itself is not marked.
            blocker_title = _title_cell(2)
            assert "\U0001f6ab" not in blocker_title

    async def test_b_opens_block_dialog(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        from todo.tui.blockers import BlockDialog

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            assert isinstance(app.screen, BlockDialog)

    async def test_b_block_dialog_creates_relation(
        self, dependencies: SqliteDependencyStore, seeded: Path, items: SqliteItemStore
    ) -> None:
        """Submitting a blocker id via the 'b' dialog persists the relation."""
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Cursor starts on item #1; block it by #2.
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("2")
            await pilot.press("enter")
            await pilot.pause()

            graph = dependencies.load()
            done = items.done_ids()
            assert graph.blockers_of(1) == [2]
            assert graph.is_blocked(1, done) is True
            # Dialog dismissed back to the list view.
            from todo.tui.blockers import BlockDialog

            assert not isinstance(app.screen, BlockDialog)

    async def test_b_block_dialog_never_offers_the_item_itself(
        self, dependencies: SqliteDependencyStore, seeded: Path, items: SqliteItemStore
    ) -> None:
        """Self-blocking used to be typed, rejected, and reported inline.
        The picker cannot offer it at all — the domain rule still stands
        (tests/test_query_amplification.py), it is simply unreachable."""
        from textual.widgets import OptionList

        from todo.tui.blockers import BlockDialog

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Cursor on item #1; search for it by its own id.
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("1")
            await pilot.pause()

            assert isinstance(app.screen, BlockDialog)
            options = app.screen.query_one("#block-options", OptionList)
            assert [str(o.prompt) for o in options._options] == []

            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, BlockDialog)  # nothing to choose
            assert dependencies.load().blockers_of(1) == []

    async def test_b_block_dialog_removes_an_existing_blocker(
        self, dependencies: SqliteDependencyStore, seeded: Path, items: SqliteItemStore
    ) -> None:
        """Removal is choosing the marked candidate. The old "-2" shorthand
        is gone: it collided with the search box, where "-2" is a perfectly
        good query for a title containing "-2"."""
        from tests.factory import add_blocker

        add_blocker(items, dependencies, 1, [2])
        assert dependencies.load().is_blocked(1, items.done_ids()) is True

        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("enter")  # #2 is marked and sorted first
            await pilot.pause()

            graph = dependencies.load()
            done = items.done_ids()
            assert graph.blockers_of(1) == []
            assert graph.is_blocked(1, done) is False

    async def test_blocked_row_is_dimmed(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, db_path: Path
    ) -> None:
        from rich.text import Text

        from tests.factory import add_blocker

        add_todo(items, NewItem(title="Blocked item"))  # id 1
        add_todo(items, NewItem(title="Blocker item"))  # id 2
        add_blocker(items, dependencies, 1, [2])

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)

            blocked_cell = table.get_row_at(table.get_row_index("1"))[3]
            assert isinstance(blocked_cell, Text)
            assert blocked_cell.style == "dim"

            # All cells are Text (markup safety); only blocked rows are dim.
            blocker_cell = table.get_row_at(table.get_row_index("2"))[3]
            assert isinstance(blocker_cell, Text)
            assert blocker_cell.style == ""


class TestKeyBindingsDontHang:
    """Regression tests: ensure no key binding locks up the UI."""

    @pytest.mark.parametrize(
        "key",
        [
            "l",
            "h",
            "left",
            "right",
            "j",
            "k",
            "up",
            "down",
            "greater_than_sign",
            "less_than_sign",
        ],
    )
    async def test_single_key_doesnt_hang(
        self, seeded: Path, items: SqliteItemStore, key: str
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()
            # If we got here without hanging, we're good
            assert app.is_running


class TestConcurrentDeletionGuards:
    async def test_done_on_vanished_item_does_not_crash(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            items.delete(1)  # vanishes between poll refreshes
            await pilot.press("d")
            await pilot.pause()
            assert app.is_running

    async def test_confirmed_delete_of_vanished_item_does_not_crash(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            items.delete(1)  # deleted while the dialog was open
            await pilot.press("y")
            await pilot.pause()
            assert app.is_running

    async def test_status_move_on_vanished_item_does_not_crash(
        self, seeded: Path, items: SqliteItemStore
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            items.delete(1)
            await pilot.press("greater_than_sign")
            await pilot.pause()
            assert app.is_running


class _LockedItemStore(SqliteItemStore):
    """Simulates a database whose write lock another process holds."""

    def create(self, item: TodoItem) -> None:
        raise StorageError("Failed to create todo: database is locked")


class _LockedDependencyStore(SqliteDependencyStore):
    def save(self, graph: DependencyGraph) -> None:
        raise StorageError("Failed to save dependencies: database is locked")


class TestLockedDatabaseDialogs:
    async def test_block_dialog_shows_storage_error_inline(
        self, dependencies: SqliteDependencyStore, db_path: Path
    ) -> None:
        # Seed through a working store; the locked one only refuses writes.
        plain = SqliteItemStore(db_path)
        add_todo(plain, NewItem(title="One"))
        add_todo(plain, NewItem(title="Two"))
        plain.close()

        app = TodoApp(db_path, dependencies=_LockedDependencyStore(db_path))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("2")
            await pilot.press("enter")
            await pilot.pause()
            from todo.tui.blockers import BlockDialog

            assert app.is_running
            assert isinstance(app.screen, BlockDialog)  # stays open with error

    async def test_new_item_save_shows_storage_error(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        plain = SqliteItemStore(db_path)
        add_todo(plain, NewItem(title="Existing"))
        plain.close()

        app = TodoApp(db_path, items=_LockedItemStore(db_path))
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            for ch in "New":
                await pilot.press(ch)
            for _ in range(4):
                await pilot.press("enter")
                await pilot.pause()
            assert app.is_running


class TestDetailPaneCache:
    async def test_row_highlight_does_not_requery_storage(
        self, seeded: Path, items: SqliteItemStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_refresh_list already holds fully hydrated items; moving the
        cursor must render the detail pane from them, not re-run four SQL
        queries per keystroke."""
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()

            calls = 0
            original_get = SqliteItemStore.get

            def counting_get(self: Path, item_id: int):  # type: ignore[no-untyped-def]
                nonlocal calls
                calls += 1
                return original_get(self, item_id)

            monkeypatch.setattr(SqliteItemStore, "get", counting_get)
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            assert calls == 0

            # The pane did render from the cache.
            meta = str(app.query_one("#detail-meta", Static).render())
            assert "Priority:" in meta


class TestSharedMetaPresenter:
    def test_inspect_and_detail_share_one_meta_source(self) -> None:
        """The metadata block was written out three times and had already
        drifted; a single presenter is the class fix."""
        from datetime import datetime, timezone

        from todo.domain.todo_item import TodoItem
        from todo.tui.render import meta_lines

        item = TodoItem(
            id=7,
            title="t",
            body="",
            priority=Priority.HIGH,
            status=Status.TODO,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            done_at=None,
            deadline=Deadline(2099, 1, 1),
            tags=frozenset({Tag("a[red]b")}),
        )
        lines = meta_lines(
            item,
            DependencyGraph(
                frozenset(
                    {
                        (ItemId(1), ItemId(7)),
                        (ItemId(7), ItemId(2)),
                        (ItemId(7), ItemId(3)),
                    }
                )
            ),
        )
        joined = "\n".join(lines)
        assert "Priority: high" in joined
        assert "Deadline:" in joined
        assert "Blocked by: #1" in joined
        assert "Blocking: #2, #3" in joined
        # User text is escaped for markup-parsing widgets.
        assert "a[red]b" not in joined
        # The fixed pane crops from the bottom, so the lines the table
        # cannot show come before the ones that repeat its columns.
        assert joined.index("Tags:") < joined.index("Priority: high")
        assert joined.index("Blocked by: #1") < joined.index("Priority: high")
        assert joined.index("Priority: high") < joined.index("Created:")


class TestStorageFailureDoesNotCrashTui:
    """A database-level read failure must degrade to a notification on
    every keypress path, like the CLI's one-line 'Database error'."""

    @staticmethod
    def _boom(*args: object, **kwargs: object) -> object:
        from todo.exceptions import StorageError

        raise StorageError("database disk image is malformed")

    async def test_cycle_tag_survives_read_failure(
        self, seeded: Path, items: SqliteItemStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            monkeypatch.setattr(SqliteItemStore, "tags_of_every_item", self._boom)
            await pilot.press("t")
            await pilot.pause()
            assert app.is_running

    async def test_cycle_project_survives_read_failure(
        self, seeded: Path, items: SqliteItemStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            monkeypatch.setattr(SqliteProjectStore, "find", self._boom)
            await pilot.press("p")
            await pilot.pause()
            assert app.is_running

    async def test_refresh_after_action_survives_read_failure(
        self, seeded: Path, items: SqliteItemStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """action_done's own error handler calls _refresh_list; a failure
        there must not escape the handler and kill the session."""
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            monkeypatch.setattr(SqliteItemStore, "find", self._boom)
            await pilot.press("d")
            await pilot.pause()
            assert app.is_running

    async def test_edit_and_inspect_survive_read_failure(
        self, seeded: Path, items: SqliteItemStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            monkeypatch.setattr(SqliteItemStore, "get", self._boom)
            await pilot.press("e")
            await pilot.pause()
            assert app.is_running
            await pilot.press("i")
            await pilot.pause()
            assert app.is_running
            await pilot.press("greater_than_sign")
            await pilot.pause()
            assert app.is_running


class TestRefreshRobustness:
    async def test_transient_read_failure_keeps_last_good_rows(
        self, seeded: Path, items: SqliteItemStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A degraded (notified) refresh must not wipe the table — query
        first, clear only on success."""
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert _item_rows(table) == 3

            from todo.exceptions import StorageError

            original = SqliteItemStore.find
            fail_once = {"armed": True}

            def flaky(self: SqliteItemStore, item_filter: ItemFilter) -> list[TodoItem]:
                if fail_once["armed"]:
                    fail_once["armed"] = False
                    raise StorageError("database disk image is malformed")
                return original(self, item_filter)

            monkeypatch.setattr(SqliteItemStore, "find", flaky)
            await pilot.press("d")
            await pilot.pause()
            assert app.is_running
            # Stale but visible beats blank and dead.
            assert _item_rows(table) == 3

    async def test_emptied_table_clears_detail_pane(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        """Deleting the last item must not leave it rendered in the detail
        pane forever."""
        add_todo(items, NewItem(title="only item", body="ghost body"))
        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            title = str(app.query_one("#detail-title", Static).render())
            body = str(app.query_one("#detail-body", Static).render())
            assert "only item" not in title
            assert "ghost body" not in body


class TestEditorBufferReadFailure:
    async def test_unreadable_buffer_reports_path_and_keeps_file(
        self,
        dependencies: SqliteDependencyStore,
        seeded: Path,
        items: SqliteItemStore,
        tmp_path: Path,
    ) -> None:
        """An unreadable buffer after a successful editor run must tell the
        user where their (possibly recoverable) buffer lives — never strand
        it silently."""
        app = TodoApp(seeded)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            missing = tmp_path / "vanished.todo.txt"
            notices: list[str] = []
            view.notify = lambda msg, **kw: notices.append(str(msg))  # type: ignore[method-assign]
            content = EditorSession(view, items).read_buffer(str(missing))
            assert content is None
            assert notices
            assert str(missing) in notices[0]


@contextlib.contextmanager
def monkeypatched(module: object, name: str, value: object) -> Iterator[None]:
    original = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, original)


class TestItemMenu:
    """Opening an item gives a menu of its fields; Enter on a row changes
    that field. Nothing is typed as 'key: value' and nothing is remembered
    by number."""

    async def _open(self, pilot: object) -> object:
        from todo.tui.item_screen import ItemScreen

        app = pilot.app  # type: ignore[attr-defined]
        await pilot.press("i")  # type: ignore[attr-defined]
        await pilot.pause()  # type: ignore[attr-defined]
        assert isinstance(app.screen, ItemScreen)
        return app.screen

    async def _row(self, pilot: object, key: str) -> None:
        """Walk the menu to a field the way a user does, then choose it.

        From the top every time: the menu keeps the cursor on the row you
        last edited, and it wraps at the ends.
        """
        from todo.tui.item_screen import FIELDS

        index = [k for k, _ in FIELDS].index(key)
        await pilot.press("home")  # type: ignore[attr-defined]
        for _ in range(index):
            await pilot.press("down")  # type: ignore[attr-defined]
        await pilot.press("enter")  # type: ignore[attr-defined]
        await pilot.pause()  # type: ignore[attr-defined]

    def _rows(self, screen: object) -> list[str]:
        options = screen.query_one("#item-fields", OptionList)  # type: ignore[attr-defined]
        return [
            str(options.get_option_at_index(i).prompt)
            for i in range(options.option_count)
        ]

    async def test_every_field_is_listed_with_its_value(
        self,
        items: SqliteItemStore,
        dependencies: SqliteDependencyStore,
        db_path: Path,
    ) -> None:
        add_todo(
            items,
            NewItem(
                title="Main",
                priority=Priority.HIGH,
                deadline=date(2099, 3, 4),
                tags=frozenset({"auth", "web"}),
            ),
        )
        add_todo(items, NewItem(title="Blocker"))
        add_todo(items, NewItem(title="Dependent"))
        add_blocker(items, dependencies, 1, [2])
        add_blocker(items, dependencies, 3, [1])

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open(pilot)
            rows = "\n".join(self._rows(screen))
            assert "Title       Main" in rows
            assert "Priority    high" in rows
            assert "Status      todo" in rows
            assert "Deadline    2099-03-04" in rows
            assert "Tags        auth, web" in rows
            assert "Blocked by  #2" in rows
            assert "Blocking    #3" in rows
            assert "Body        empty" in rows

    async def test_renaming_from_the_menu(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Old name"))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open(pilot)
            await self._row(pilot, "title")
            field = app.screen.query_one("#prompt-input", Input)
            assert field.value == "Old name"  # pre-filled, not blank
            field.value = "New name"
            await pilot.press("enter")
            await pilot.pause()

            assert items.get(1).title == "New name"
            assert "Title       New name" in "\n".join(self._rows(app.screen))

    async def test_an_empty_title_is_refused_and_the_screen_stays(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Keep me"))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open(pilot)
            await self._row(pilot, "title")
            app.screen.query_one("#prompt-input", Input).value = "   "
            await pilot.press("enter")
            await pilot.pause()

            assert app.screen is screen  # not closed on the user's work
            assert "empty" in str(screen.query_one("#item-error", Label).render())
            assert items.get(1).title == "Keep me"

    async def test_priority_is_chosen_from_its_values(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Task", priority=Priority.MEDIUM))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open(pilot)
            await self._row(pilot, "priority")
            options = app.screen.query_one("#prompt-options", OptionList)
            # Starts on the current value, so Enter alone changes nothing.
            assert str(options.get_option_at_index(options.highlighted).prompt) == (
                "medium"
            )
            await pilot.press("up")  # medium -> high
            await pilot.press("enter")
            await pilot.pause()

            assert items.get(1).priority is Priority.HIGH
            assert "Priority    high" in "\n".join(self._rows(app.screen))

    async def test_status_change_reports_what_it_unblocked(
        self, dependencies: SqliteDependencyStore, items: SqliteItemStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Blocker"))
        add_todo(items, NewItem(title="Waiting"))
        add_blocker(items, dependencies, 2, [1])

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open(pilot)  # cursor is on #1, the blocker
            notices: list[str] = []
            screen.notify = lambda msg, **kw: notices.append(str(msg))  # type: ignore[method-assign]
            await self._row(pilot, "status")
            options = app.screen.query_one("#prompt-options", OptionList)
            options.highlighted = [s.value for s in Status].index("done")
            await pilot.press("enter")
            await pilot.pause()

            assert items.get(1).status is Status.DONE
            assert any("#2" in n and "unblocked" in n for n in notices)

    async def test_a_bad_deadline_is_refused_inline(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Task", deadline=date(2099, 1, 1)))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open(pilot)
            await self._row(pilot, "deadline")
            app.screen.query_one("#prompt-input", Input).value = "next tuesday"
            await pilot.press("enter")
            await pilot.pause()

            assert app.screen is screen
            assert "YYYY-MM-DD" in str(screen.query_one("#item-error", Label).render())
            assert items.get(1).deadline == date(2099, 1, 1)  # untouched

    async def test_an_emptied_deadline_clears_it(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Task", deadline=date(2099, 1, 1)))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open(pilot)
            await self._row(pilot, "deadline")
            app.screen.query_one("#prompt-input", Input).value = ""
            await pilot.press("enter")
            await pilot.pause()

            assert items.get(1).deadline is None

    async def test_tags_are_replaced_by_what_you_type(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Task", tags=frozenset({"old"})))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open(pilot)
            await self._row(pilot, "tags")
            app.screen.query_one("#prompt-input", Input).value = "one, two"
            await pilot.press("enter")
            await pilot.pause()

            assert items.get(1).tags == frozenset({"one", "two"})

    async def test_a_blocker_is_removed_from_the_menu(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, db_path: Path
    ) -> None:
        """'you also need to be able to remove blockers and such'."""
        from todo.tui.blockers import BlockDialog

        add_todo(items, NewItem(title="Main"))
        add_todo(items, NewItem(title="Blocker"))
        add_blocker(items, dependencies, 1, [2])

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open(pilot)
            await self._row(pilot, "blocked_by")
            assert isinstance(app.screen, BlockDialog)
            # #2 is the current blocker, so it sorts first and is marked.
            assert str(
                app.screen.query_one("#block-options", OptionList)
                .get_option_at_index(0)
                .prompt
            ).startswith("✓ #2")
            await pilot.press("enter")
            await pilot.pause()

            assert dependencies.load().blockers_of(1) == []
            assert "Blocked by  —" in "\n".join(self._rows(app.screen))

    async def test_a_dependent_is_added_from_the_blocking_row(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, db_path: Path
    ) -> None:
        """Both ends of the relation are editable: a dependency belongs to
        neither item, so it can be written from either side."""
        from todo.tui.blockers import BlockDialog

        add_todo(items, NewItem(title="Main"))
        add_todo(items, NewItem(title="Later"))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open(pilot)  # #1
            await self._row(pilot, "blocking")
            assert isinstance(app.screen, BlockDialog)
            await pilot.press("enter")  # the only candidate, #2
            await pilot.pause()

            assert dependencies.load().blockers_of(2) == [1]
            assert dependencies.load().dependents_of(1) == [2]
            assert "Blocking    #2" in "\n".join(self._rows(app.screen))

    async def test_a_dependent_is_removed_from_the_blocking_row(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Main"))
        add_todo(items, NewItem(title="Waiting"))
        add_blocker(items, dependencies, 2, [1])

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open(pilot)  # #1
            await self._row(pilot, "blocking")
            options = app.screen.query_one("#block-options", OptionList)
            # The existing dependent is marked and sorted first.
            assert str(options.get_option_at_index(0).prompt).startswith("✓ #2")
            await pilot.press("enter")
            await pilot.pause()

            assert dependencies.load().blockers_of(2) == []
            assert "Blocking    —" in "\n".join(self._rows(app.screen))

    async def test_the_two_directions_ask_different_questions(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Main"))
        add_todo(items, NewItem(title="Other"))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open(pilot)
            await self._row(pilot, "blocked_by")
            waits_on = str(app.screen.query_one("#block-title", Label).render())
            await pilot.press("escape")
            await pilot.pause()
            await self._row(pilot, "blocking")
            blocks = str(app.screen.query_one("#block-title", Label).render())

            assert waits_on == "What does #1 wait on?"
            assert blocks == "What waits on #1?"

    async def test_a_cycle_from_the_blocking_side_is_refused_inline(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, db_path: Path
    ) -> None:
        """The cycle check does not care which end you entered from."""
        from todo.tui.blockers import BlockDialog

        add_todo(items, NewItem(title="Main"))
        add_todo(items, NewItem(title="Blocker"))
        add_blocker(items, dependencies, 1, [2])  # #1 waits on #2

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open(pilot)  # #1
            await self._row(pilot, "blocking")
            # Making #2 wait on #1 as well would close the loop.
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, BlockDialog)  # still open
            error = str(app.screen.query_one("#block-error", Label).render())
            assert "cycle" in error
            assert dependencies.load().blockers_of(2) == []

    async def test_the_body_row_hands_off_to_the_editor(
        self, dependencies: SqliteDependencyStore, items: SqliteItemStore, db_path: Path
    ) -> None:
        from todo.tui import item_screen as item_screen_module

        add_todo(items, NewItem(title="Task", body="line one\nline two"))

        seen: list[str] = []

        class FakeSession:
            def __init__(self, view: object, items: SqliteItemStore) -> None:
                pass

            def run(self, item: TodoItem) -> None:
                seen.append(item.body)
                return None

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open(pilot)
            assert "Body        2 lines" in "\n".join(self._rows(screen))
            with monkeypatched(item_screen_module, "EditorSession", FakeSession):
                await self._row(pilot, "body")
            assert seen == ["line one\nline two"]

    async def test_a_change_reaches_the_list_behind_it(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Before"))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await self._open(pilot)
            await self._row(pilot, "title")
            app.screen.query_one("#prompt-input", Input).value = "After"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            table = app.query_one("#item-list", DataTable)
            titles = [
                str(table.get_cell_at(Coordinate(r, COLUMNS.index("Title"))))
                for r in range(table.row_count)
            ]
            assert any("After" in t for t in titles)

    @pytest.mark.parametrize("size", [(80, 24), (80, 20), (60, 16)])
    async def test_the_hint_and_the_error_stay_on_screen(
        self, items: SqliteItemStore, db_path: Path, size: tuple[int, int]
    ) -> None:
        """The body preview is the only part allowed to give way: a screen
        taller than the terminal must never push the inline error off it
        (round-2 defect #7, one dialog over)."""
        add_todo(
            items, NewItem(title="Task", body="\n".join(f"line {i}" for i in range(40)))
        )

        app = TodoApp(db_path)
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            screen = await self._open(pilot)
            hint = screen.query_one("#item-hint", Label)
            assert hint.region.height > 0
            assert hint.region.bottom <= size[1]

            await self._row(pilot, "deadline")
            app.screen.query_one("#prompt-input", Input).value = "whenever"
            await pilot.press("enter")
            await pilot.pause()

            error = screen.query_one("#item-error", Label)
            assert "YYYY-MM-DD" in str(error.render())
            assert error.region.height > 0
            assert error.region.bottom <= size[1]

    async def test_escaping_a_prompt_changes_nothing(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        add_todo(items, NewItem(title="Task", priority=Priority.MEDIUM))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            before = items.get(1)
            await self._open(pilot)
            for field in ("title", "priority", "deadline", "tags"):
                await self._row(pilot, field)
                await pilot.press("escape")
                await pilot.pause()
            assert items.get(1) == before

    async def test_an_item_deleted_underneath_says_so(
        self, items: SqliteItemStore, db_path: Path
    ) -> None:
        """Another process (or another window) can delete the item while
        this screen is open. The write fails; saying so and staying put
        beats vanishing mid-keystroke, and Esc still works."""
        from todo.tui.item_screen import ItemScreen

        add_todo(items, NewItem(title="Doomed"))

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open(pilot)
            await self._row(pilot, "tags")
            items.delete(1)
            app.screen.query_one("#prompt-input", Input).value = "late"
            await pilot.press("enter")
            await pilot.pause()

            assert app.is_running
            assert app.screen is screen
            assert "1" in str(screen.query_one("#item-error", Label).render())
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ItemScreen)

    async def test_an_applied_body_edit_updates_the_row(
        self, items: SqliteItemStore, dependencies: SqliteDependencyStore, db_path: Path
    ) -> None:

        from tests.factory import edit_todo
        from todo.tui import item_screen as item_screen_module

        add_todo(items, NewItem(title="Task", body="one line"))

        class FakeSession:
            def __init__(self, view: object, item_store: SqliteItemStore) -> None:
                self._items = item_store

            def run(self, item: TodoItem) -> TodoItem:
                # What a real $EDITOR round trip leaves behind.
                edit_todo(self._items, item.id, body="one\ntwo\nthree")
                return self._items.get(item.id)

        app = TodoApp(db_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            screen = await self._open(pilot)
            with monkeypatched(item_screen_module, "EditorSession", FakeSession):
                await self._row(pilot, "body")
            assert "Body        3 lines" in "\n".join(self._rows(screen))
