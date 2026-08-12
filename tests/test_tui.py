from __future__ import annotations

from pathlib import Path

import pytest
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Label, Static

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import add_todo
from todo.domain.enums import Priority, Status
from todo.tui.app import TodoApp
from todo.tui.list_view import TodoListView, _is_separator


def _item_rows(table: DataTable) -> int:
    """Count rows in a TodoTable that represent actual items (skip separators)."""
    return sum(1 for row_key in table.rows if not _is_separator(row_key.value))


@pytest.fixture()
def seeded_storage(db_path: Path) -> SqliteStorage:
    storage = SqliteStorage(db_path)
    add_todo(storage, "Urgent task", priority=Priority.URGENT)
    add_todo(storage, "High task", priority=Priority.HIGH)
    add_todo(storage, "Backlog thing", status=Status.BACKLOG)
    return storage


class TestBasics:
    async def test_app_launches(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test():
            assert app.is_running
            table = app.query_one("#item-list", DataTable)
            # 3 seeded items (separators in table not counted)
            assert _item_rows(table) == 3

    async def test_quit_with_q(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.press("q")
            await pilot.pause()
        assert not app.is_running


class TestStatusNavigation:
    async def test_greater_than_advances_status(
        self, seeded_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Cursor starts on first row (Urgent task)
            await pilot.press("greater_than_sign")
            await pilot.pause()

            # Item #1 should now be in-progress
            item = seeded_storage.get(1)
            assert item.status == Status.IN_PROGRESS

    async def test_less_than_moves_back(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            # First item is "todo" — move back to backlog
            await pilot.press("less_than_sign")
            await pilot.pause()

            item = seeded_storage.get(1)
            assert item.status == Status.BACKLOG

    async def test_advance_to_done(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            # todo -> in-progress -> done
            await pilot.press("greater_than_sign")
            await pilot.pause()
            await pilot.press("greater_than_sign")
            await pilot.pause()

            item = seeded_storage.get(1)
            assert item.status == Status.DONE
            assert item.done_at is not None


class TestPrdKeyBindings:
    """The PRD's key table: arrows and hjkl, alongside the < > pair."""

    @pytest.mark.parametrize("key", ["l", "right"])
    async def test_advances_status(
        self, seeded_storage: SqliteStorage, key: str
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()
            assert seeded_storage.get(1).status == Status.IN_PROGRESS

    @pytest.mark.parametrize("key", ["h", "left"])
    async def test_reverses_status(
        self, seeded_storage: SqliteStorage, key: str
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()
            assert seeded_storage.get(1).status == Status.BACKLOG

    async def test_j_and_k_move_the_selection(
        self, seeded_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=seeded_storage)
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

    async def test_j_skips_separator_rows(self, seeded_storage: SqliteStorage) -> None:
        """j must behave exactly like down, separators included."""
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            for _ in range(table.row_count):
                await pilot.press("j")
                await pilot.pause()
                key = table.coordinate_to_cell_key(
                    Coordinate(table.cursor_row, 0)
                ).row_key.value
                assert not _is_separator(key)


class TestDoneAction:
    async def test_d_marks_done(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()

            item = seeded_storage.get(1)
            assert item.status == Status.DONE


class TestDelete:
    async def test_x_opens_confirm_dialog(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            # Confirm dialog should be on screen
            from todo.tui.list_view import ConfirmDialog

            assert isinstance(app.screen, ConfirmDialog)

    async def test_delete_y_confirms(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()

            # Item 1 should be gone
            from todo.exceptions import NotFoundError

            with pytest.raises(NotFoundError):
                seeded_storage.get(1)

    async def test_delete_n_cancels(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            # Item 1 should still exist
            assert seeded_storage.get(1).id == 1


class TestNewDialog:
    async def test_n_opens_new_dialog(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            from todo.tui.list_view import NewItemDialog

            assert isinstance(app.screen, NewItemDialog)

    async def test_escape_cancels_new(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

            # Back to list view, no new item
            count_before = len(seeded_storage.list(include_done=True))
            assert count_before == 3

    async def test_enter_advances_through_fields_then_saves(
        self, seeded_storage: SqliteStorage
    ) -> None:
        """Step priority up with right arrow, then Enter through the rest to save."""
        from todo.tui.list_view import AdvancingSelect

        app = TodoApp(storage=seeded_storage)
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

            # Tags -> Save
            for ch in "demo":
                await pilot.press(ch)
            await pilot.press("enter")
            await pilot.pause()

            items = seeded_storage.list(include_done=True)
            new_item = next(i for i in items if i.title == "From dialog")
            assert new_item.priority == Priority.HIGH
            assert "demo" in new_item.tags
            assert new_item.deadline is None

    async def test_default_priority_when_kept(
        self, seeded_storage: SqliteStorage
    ) -> None:
        """Hitting Enter without changing the priority keeps the default 'medium'."""
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()

            for ch in "Default pri":
                await pilot.press(ch)
            # Title → Priority (default medium) → Deadline → Tags → Save
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            new_item = next(
                i
                for i in seeded_storage.list(include_done=True)
                if i.title == "Default pri"
            )
            assert new_item.priority == Priority.MEDIUM

    async def test_priority_left_right_steps_clamped(
        self, seeded_storage: SqliteStorage
    ) -> None:
        """Right increases priority (toward urgent); Left decreases it (toward low).
        Both clamp at the ends — no wraparound."""
        from todo.tui.list_view import AdvancingSelect

        app = TodoApp(storage=seeded_storage)
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
        self, seeded_storage: SqliteStorage
    ) -> None:
        """Down advances and Up retreats on every field in the dialog."""
        from textual.widgets import Input

        from todo.tui.list_view import AdvancingSelect

        app = TodoApp(storage=seeded_storage)
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

            # Tags <- Deadline (up)
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
        self, seeded_storage: SqliteStorage
    ) -> None:
        """Down on the priority field advances to deadline (does not open dropdown)."""
        from textual.widgets import Input

        from todo.tui.list_view import AdvancingSelect

        app = TodoApp(storage=seeded_storage)
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
        self, seeded_storage: SqliteStorage
    ) -> None:
        """Bad date keeps focus on deadline; no bouncing to tags or save."""
        from textual.widgets import Input

        app = TodoApp(storage=seeded_storage)
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
                i.title == "Bad date" for i in seeded_storage.list(include_done=True)
            )
            # An error message is shown
            error_label = app.screen.query_one("#dialog-error", Label)
            assert "date" in str(error_label.render()).lower()

    async def test_empty_title_does_not_advance(
        self, seeded_storage: SqliteStorage
    ) -> None:
        """Pressing Enter with no title keeps focus on the title field."""
        from textual.widgets import Input

        app = TodoApp(storage=seeded_storage)
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
    def tagged_storage(self, db_path: Path) -> SqliteStorage:
        storage = SqliteStorage(db_path)
        add_todo(storage, "Backend work", priority=Priority.URGENT, tags=["backend"])
        add_todo(storage, "Frontend work", tags=["frontend"])
        add_todo(storage, "Untagged", priority=Priority.URGENT)
        return storage

    async def test_priority_filter_toggles(self, tagged_storage: SqliteStorage) -> None:
        app = TodoApp(storage=tagged_storage)
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

    async def test_tag_filter_cycles(self, tagged_storage: SqliteStorage) -> None:
        app = TodoApp(storage=tagged_storage)
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

    async def test_zero_clears_all_filters(self, tagged_storage: SqliteStorage) -> None:
        app = TodoApp(storage=tagged_storage)
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

    async def test_status_line_shows_filters(
        self, tagged_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=tagged_storage)
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
    def three_todos(self, db_path: Path) -> SqliteStorage:
        storage = SqliteStorage(db_path)
        add_todo(storage, "First")
        add_todo(storage, "Second")
        add_todo(storage, "Third")
        return storage

    def _selected_id(self, app: TodoApp) -> object:
        view = app.query_one(TodoListView)
        return view._selected_item_id()

    async def test_follow_mode_default_follows_item(
        self, three_todos: SqliteStorage
    ) -> None:
        app = TodoApp(storage=three_todos)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert self._selected_id(app) == 1
            await pilot.press("d")  # complete #1; cursor follows into done group
            await pilot.pause()
            assert self._selected_id(app) == 1

    async def test_stay_mode_keeps_row_for_cleanup(
        self, three_todos: SqliteStorage
    ) -> None:
        app = TodoApp(storage=three_todos)
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

    async def test_toggle_back_restores_follow(
        self, three_todos: SqliteStorage
    ) -> None:
        app = TodoApp(storage=three_todos)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("full_stop")
            await pilot.press("full_stop")  # back to follow
            await pilot.pause()
            await pilot.press("d")
            await pilot.pause()
            assert self._selected_id(app) == 1

    async def test_stay_mode_at_last_row(self, three_todos: SqliteStorage) -> None:
        app = TodoApp(storage=three_todos)
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


class TestProjectFilter:
    @pytest.fixture()
    def project_storage(self, db_path: Path) -> SqliteStorage:
        storage = SqliteStorage(db_path)
        infra = storage.add_project("infra")
        web = storage.add_project("web")
        add_todo(storage, "Infra task", project_id=infra.id)
        add_todo(storage, "Web task", project_id=web.id)
        add_todo(storage, "Loose task")
        return storage

    async def test_p_cycles_project_filter(
        self, project_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=project_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert _item_rows(table) == 3

            await pilot.press("p")  # infra
            await pilot.pause()
            assert _item_rows(table) == 1

            await pilot.press("p")  # web
            await pilot.pause()
            assert _item_rows(table) == 1

            await pilot.press("p")  # back to all
            await pilot.pause()
            assert _item_rows(table) == 3

    async def test_zero_clears_project_filter(
        self, project_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=project_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            await pilot.press("p")
            await pilot.pause()
            assert _item_rows(table) == 1
            await pilot.press("0")
            await pilot.pause()
            assert _item_rows(table) == 3

    async def test_detail_pane_shows_project(
        self, project_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=project_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            meta = str(app.query_one("#detail-meta", Static).render())
            assert "Project: infra" in meta


class TestSearch:
    async def test_slash_opens_search(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash")
            await pilot.pause()
            from todo.tui.list_view import SearchDialog

            assert isinstance(app.screen, SearchDialog)

    async def test_search_filters_list(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
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

    async def test_escape_clears_search(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
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
        self, seeded_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            title = app.query_one("#detail-title", Static)
            assert "Urgent task" in str(title.render())

    async def test_arrow_down_updates_detail(
        self, seeded_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            title = app.query_one("#detail-title", Static)
            assert "High task" in str(title.render())


class TestInspect:
    async def test_i_opens_inspect_dialog(self, seeded_storage: SqliteStorage) -> None:
        from todo.tui.list_view import InspectDialog

        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            assert isinstance(app.screen, InspectDialog)

    async def test_enter_opens_inspect_dialog(
        self, seeded_storage: SqliteStorage
    ) -> None:
        from todo.tui.list_view import InspectDialog

        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, InspectDialog)

    async def test_inspect_shows_full_body(self, db_path: Path) -> None:
        """Long bodies are visible in the inspect modal (not clipped)."""
        from todo.tui.list_view import InspectDialog

        storage = SqliteStorage(db_path)
        long_body = "\n".join(f"line {i}" for i in range(40))
        add_todo(storage, "Has long body", body=long_body)

        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            assert isinstance(app.screen, InspectDialog)

            body_widget = app.screen.query_one("#inspect-body", Static)
            rendered = str(body_widget.render())
            assert "line 0" in rendered
            assert "line 39" in rendered

    async def test_escape_closes_inspect(self, seeded_storage: SqliteStorage) -> None:
        from todo.tui.list_view import InspectDialog

        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("i")
            await pilot.pause()
            assert isinstance(app.screen, InspectDialog)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, InspectDialog)


class TestStatusGroups:
    async def test_separator_per_status(self, db_path: Path) -> None:
        """A separator row appears for each non-empty status group."""
        storage = SqliteStorage(db_path)
        add_todo(storage, "todo 1")  # default status: todo
        add_todo(storage, "backlog 1", status=Status.BACKLOG)
        add_todo(storage, "in-progress 1", status=Status.IN_PROGRESS)
        add_todo(storage, "done 1", status=Status.DONE)

        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            separator_keys = [
                row_key.value for row_key in table.rows if _is_separator(row_key.value)
            ]
            # One separator per status, in display order
            assert separator_keys == [
                "__sep_in-progress",
                "__sep_todo",
                "__sep_backlog",
                "__sep_done",
            ]

    async def test_arrow_down_skips_separators(self, db_path: Path) -> None:
        """Pressing down on the last item of a group skips the next separator."""
        storage = SqliteStorage(db_path)
        add_todo(storage, "alpha")  # todo
        add_todo(storage, "bravo", status=Status.BACKLOG)

        app = TodoApp(storage=storage)
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

    async def test_external_add_appears(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            initial_rows = _item_rows(app.query_one("#item-list", DataTable))

            # Simulate the CLI adding an item via a separate connection
            from pathlib import Path

            other = SqliteStorage(
                Path(seeded_storage._conn.execute("PRAGMA database_list").fetchone()[2])
            )
            add_todo(other, "Added by CLI", priority=Priority.MEDIUM)
            other.close()

            # Trigger the poll
            view = app.query_one(TodoListView)
            view._poll_for_external_changes()
            await pilot.pause()

            new_rows = _item_rows(app.query_one("#item-list", DataTable))
            assert new_rows == initial_rows + 1

    async def test_external_delete_disappears(
        self, seeded_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            initial_rows = _item_rows(app.query_one("#item-list", DataTable))

            from pathlib import Path

            other = SqliteStorage(
                Path(seeded_storage._conn.execute("PRAGMA database_list").fetchone()[2])
            )
            other.delete(1)
            other.close()

            view = app.query_one(TodoListView)
            view._poll_for_external_changes()
            await pilot.pause()

            new_rows = _item_rows(app.query_one("#item-list", DataTable))
            assert new_rows == initial_rows - 1

    async def test_no_refresh_when_unchanged(
        self, seeded_storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Polling must not call _refresh_list when data hasn't changed."""
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)

            calls: list[None] = []
            original = view._refresh_list
            monkeypatch.setattr(
                view,
                "_refresh_list",
                lambda **kw: (calls.append(None), original(**kw))[1],
            )

            view._poll_for_external_changes()
            await pilot.pause()
            assert calls == []  # unchanged data: refresh must NOT run

    async def test_refresh_on_external_change(
        self,
        seeded_storage: SqliteStorage,
        db_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Polling must refresh when another process wrote to the database."""
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)

            calls: list[None] = []
            original = view._refresh_list
            monkeypatch.setattr(
                view,
                "_refresh_list",
                lambda **kw: (calls.append(None), original(**kw))[1],
            )

            # Simulate an external writer via a second connection.
            other = SqliteStorage(db_path)
            add_todo(other, "From outside")
            other.close()

            view._poll_for_external_changes()
            await pilot.pause()
            assert len(calls) == 1
            table = app.query_one("#item-list", DataTable)
            assert _item_rows(table) == 4


class TestBlocking:
    async def test_blocked_marker_appears_in_list(self, db_path: Path) -> None:
        """An actively blocked item shows the crane marker in its title cell."""
        from todo.application.commands import block_todo

        storage = SqliteStorage(db_path)
        add_todo(storage, "Blocked item")  # id 1
        add_todo(storage, "Blocker item")  # id 2
        block_todo(storage, 1, 2)  # #1 blocked by #2

        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)

            def _title_cell(item_id: int) -> str:
                row_index = table.get_row_index(str(item_id))
                return str(table.get_row_at(row_index)[3])

            blocked_title = _title_cell(1)
            assert "\U0001f6a7" in blocked_title
            assert "Blocked item" in blocked_title
            # The blocker itself is not marked.
            blocker_title = _title_cell(2)
            assert "\U0001f6a7" not in blocker_title

    async def test_b_opens_block_dialog(self, seeded_storage: SqliteStorage) -> None:
        from todo.tui.list_view import BlockDialog

        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            assert isinstance(app.screen, BlockDialog)

    async def test_b_block_dialog_creates_relation(
        self, seeded_storage: SqliteStorage
    ) -> None:
        """Submitting a blocker id via the 'b' dialog persists the relation."""
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Cursor starts on item #1; block it by #2.
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("2")
            await pilot.press("enter")
            await pilot.pause()

            item = seeded_storage.get(1)
            assert item.blocked_by == [2]
            assert item.is_blocked is True
            # Dialog dismissed back to the list view.
            from todo.tui.list_view import BlockDialog

            assert not isinstance(app.screen, BlockDialog)

    async def test_b_block_dialog_shows_error_and_stays_open(
        self, seeded_storage: SqliteStorage
    ) -> None:
        """A self-block keeps the dialog open and shows the error message."""
        from todo.tui.list_view import BlockDialog

        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Cursor on item #1; try to block it by itself.
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("1")
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, BlockDialog)
            error_label = app.screen.query_one("#block-error", Label)
            assert "itself" in str(error_label.render()).lower()
            # No relation was created.
            assert seeded_storage.get(1).blocked_by == []

    async def test_b_block_dialog_negative_id_removes_relation(
        self, seeded_storage: SqliteStorage
    ) -> None:
        from todo.application.commands import block_todo

        block_todo(seeded_storage, 1, 2)
        assert seeded_storage.get(1).is_blocked is True

        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            # Cursor on item #1; remove blocker #2 via "-2".
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("minus", "2")
            await pilot.press("enter")
            await pilot.pause()

            item = seeded_storage.get(1)
            assert item.blocked_by == []
            assert item.is_blocked is False

    async def test_blocked_row_is_dimmed(self, db_path: Path) -> None:
        from rich.text import Text

        from todo.application.commands import block_todo

        storage = SqliteStorage(db_path)
        add_todo(storage, "Blocked item")  # id 1
        add_todo(storage, "Blocker item")  # id 2
        block_todo(storage, 1, 2)

        app = TodoApp(storage=storage)
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
        self, seeded_storage: SqliteStorage, key: str
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press(key)
            await pilot.pause()
            # If we got here without hanging, we're good
            assert app.is_running


class TestConcurrentDeletionGuards:
    async def test_done_on_vanished_item_does_not_crash(
        self, seeded_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            seeded_storage.delete(1)  # vanishes between poll refreshes
            await pilot.press("d")
            await pilot.pause()
            assert app.is_running

    async def test_confirmed_delete_of_vanished_item_does_not_crash(
        self, seeded_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
            seeded_storage.delete(1)  # deleted while the dialog was open
            await pilot.press("y")
            await pilot.pause()
            assert app.is_running

    async def test_status_move_on_vanished_item_does_not_crash(
        self, seeded_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            seeded_storage.delete(1)
            await pilot.press("greater_than_sign")
            await pilot.pause()
            assert app.is_running


class _LockedStorage(SqliteStorage):
    """Simulates a database whose write lock another process holds."""

    from todo.exceptions import StorageError as _SE

    def add_blocker(self, blocked_id: int, blocker_id: int) -> None:
        raise self._SE("Failed to add blocker: database is locked")

    def add(self, title: str, **kwargs):  # type: ignore[override]
        raise self._SE("Failed to add todo: database is locked")


class TestLockedDatabaseDialogs:
    async def test_block_dialog_shows_storage_error_inline(self, db_path: Path) -> None:
        storage = _LockedStorage(db_path)
        SqliteStorage.add(storage.__class__.__bases__[0], "seed") if False else None
        # Seed via a plain connection so add() override doesn't block us.
        plain = SqliteStorage(db_path)
        add_todo(plain, "One")
        add_todo(plain, "Two")
        plain.close()

        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("b")
            await pilot.pause()
            await pilot.press("2")
            await pilot.press("enter")
            await pilot.pause()
            from todo.tui.list_view import BlockDialog

            assert app.is_running
            assert isinstance(app.screen, BlockDialog)  # stays open with error

    async def test_new_item_save_shows_storage_error(self, db_path: Path) -> None:
        plain = SqliteStorage(db_path)
        add_todo(plain, "Existing")
        plain.close()
        storage = _LockedStorage(db_path)

        app = TodoApp(storage=storage)
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
        self, seeded_storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_refresh_list already holds fully hydrated items; moving the
        cursor must render the detail pane from them, not re-run four SQL
        queries per keystroke."""
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()

            calls = 0
            original_get = SqliteStorage.get

            def counting_get(self: SqliteStorage, item_id: int):  # type: ignore[no-untyped-def]
                nonlocal calls
                calls += 1
                return original_get(self, item_id)

            monkeypatch.setattr(SqliteStorage, "get", counting_get)
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
        from datetime import date, datetime, timezone

        from todo.domain.models import TodoItem
        from todo.tui.list_view import _meta_lines

        item = TodoItem(
            id=7,
            title="t",
            body="",
            priority=Priority.HIGH,
            status=Status.TODO,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            done_at=None,
            deadline=date(2099, 1, 1),
            tags=["a[red]b"],
            blocked_by=[1],
            blocking=[2, 3],
            is_blocked=True,
            project_id=1,
            project_name="proj [/]",
        )
        lines = _meta_lines(item)
        joined = "\n".join(lines)
        assert "Priority: high" in joined
        assert "Deadline:" in joined
        assert "Blocked by: #1" in joined
        assert "Blocking: #2, #3" in joined
        # User text is escaped for markup-parsing widgets.
        assert "proj [/]" not in joined
        assert "a[red]b" not in joined


class TestStorageFailureDoesNotCrashTui:
    """A database-level read failure must degrade to a notification on
    every keypress path, like the CLI's one-line 'Database error'."""

    @staticmethod
    def _boom(*args: object, **kwargs: object) -> object:
        from todo.exceptions import StorageError

        raise StorageError("database disk image is malformed")

    async def test_cycle_tag_survives_read_failure(
        self, seeded_storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            monkeypatch.setattr(SqliteStorage, "tag_strings", self._boom)
            await pilot.press("t")
            await pilot.pause()
            assert app.is_running

    async def test_cycle_project_survives_read_failure(
        self, seeded_storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            monkeypatch.setattr(SqliteStorage, "list_projects", self._boom)
            await pilot.press("p")
            await pilot.pause()
            assert app.is_running

    async def test_refresh_after_action_survives_read_failure(
        self, seeded_storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """action_done's own error handler calls _refresh_list; a failure
        there must not escape the handler and kill the session."""
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            monkeypatch.setattr(SqliteStorage, "list", self._boom)
            await pilot.press("d")
            await pilot.pause()
            assert app.is_running

    async def test_poll_timer_survives_read_failure(
        self, seeded_storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from todo.tui.list_view import TodoListView

        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            monkeypatch.setattr(SqliteStorage, "data_version", self._boom)
            view = app.query_one(TodoListView)
            view._poll_for_external_changes()
            await pilot.pause()
            assert app.is_running

    async def test_edit_and_inspect_survive_read_failure(
        self, seeded_storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            monkeypatch.setattr(SqliteStorage, "get", self._boom)
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
        self, seeded_storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A degraded (notified) refresh must not wipe the table — query
        first, clear only on success."""
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert _item_rows(table) == 3

            from todo.exceptions import StorageError

            original = SqliteStorage.list
            fail_once = {"armed": True}

            def flaky(self: SqliteStorage, **kwargs: object):  # type: ignore[no-untyped-def]
                if fail_once["armed"]:
                    fail_once["armed"] = False
                    raise StorageError("database disk image is malformed")
                return original(self, **kwargs)

            monkeypatch.setattr(SqliteStorage, "list", flaky)
            await pilot.press("d")
            await pilot.pause()
            assert app.is_running
            # Stale but visible beats blank and dead.
            assert _item_rows(table) == 3

    async def test_emptied_table_clears_detail_pane(self, db_path: Path) -> None:
        """Deleting the last item must not leave it rendered in the detail
        pane forever."""
        storage = SqliteStorage(db_path)
        add_todo(storage, "only item", body="ghost body")
        app = TodoApp(storage=storage)
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

    async def test_startup_survives_data_version_failure(
        self, seeded_storage: SqliteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from todo.exceptions import StorageError

        def boom(self: SqliteStorage) -> int:
            raise StorageError("database disk image is malformed")

        monkeypatch.setattr(SqliteStorage, "data_version", boom)
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.is_running


class TestEditorBufferReadFailure:
    async def test_unreadable_buffer_reports_path_and_keeps_file(
        self, seeded_storage: SqliteStorage, tmp_path: Path
    ) -> None:
        """An unreadable buffer after a successful editor run must tell the
        user where their (possibly recoverable) buffer lives — never strand
        it silently."""
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            missing = tmp_path / "vanished.todo.txt"
            notices: list[str] = []
            view.notify = lambda msg, **kw: notices.append(str(msg))  # type: ignore[method-assign]
            content = view._read_edited_buffer(str(missing))
            assert content is None
            assert notices
            assert str(missing) in notices[0]


class TestPollRetryAndRenameStableFilter:
    async def test_poll_retries_after_transient_refresh_failure(
        self, db_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failed refresh must not record the new data_version, or the
        poll never retries and the TUI shows stale rows forever."""
        from todo.exceptions import StorageError
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        for title in ("one", "two", "three"):
            add_todo(storage, title)
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            table = app.query_one("#item-list", DataTable)
            assert _item_rows(table) == 3

            # External write bumps data_version.
            other = SqliteStorage(db_path)
            add_todo(other, "four")
            other.close()

            original = SqliteStorage.list
            fail_once = {"armed": True}

            def flaky(self: SqliteStorage, **kwargs: object):  # type: ignore[no-untyped-def]
                if fail_once["armed"]:
                    fail_once["armed"] = False
                    raise StorageError("database is locked")
                return original(self, **kwargs)

            monkeypatch.setattr(SqliteStorage, "list", flaky)
            view._poll_for_external_changes()  # sees change, refresh fails
            await pilot.pause()
            view._poll_for_external_changes()  # must retry, not no-op
            await pilot.pause()
            assert _item_rows(table) == 4

    async def test_project_filter_survives_external_rename(self, db_path: Path) -> None:
        """The filter keys on the stable project id: a rename must neither
        blank the list nor mislabel the status bar."""
        from todo.application.commands import add_project, edit_project
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        project = add_project(storage, "Alpha")
        add_todo(storage, "in alpha", project_id=project.id)
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("p")  # filter: Alpha
            await pilot.pause()
            table = app.query_one("#item-list", DataTable)
            assert _item_rows(table) == 1

            other = SqliteStorage(db_path)
            edit_project(other, project.id, name="Beta")
            other.close()

            view = app.query_one(TodoListView)
            view._refresh_list()
            await pilot.pause()
            assert _item_rows(table) == 1  # still filtered to the project
            status = str(app.query_one("#search-status", Static).render())
            assert "Beta" in status


class TestPollVersionRaceAndToastStreak:
    async def test_write_during_rebuild_is_not_marked_seen(self, db_path: Path) -> None:
        """The version must be captured BEFORE the reads: a commit landing
        during the table rebuild would otherwise be recorded as already
        seen and never displayed (round-10 regression)."""
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        add_todo(storage, "first")
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            table = app.query_one("#item-list", DataTable)
            assert _item_rows(table) == 1

            # An external write lands mid-rebuild, after this refresh read
            # its rows but before it records the version.
            original_rows = TodoListView._rows_for_refresh

            def racing(self: TodoListView):  # type: ignore[no-untyped-def]
                result = original_rows(self)
                other = SqliteStorage(db_path)
                add_todo(other, "added mid-rebuild")
                other.close()
                return result

            TodoListView._rows_for_refresh = racing  # type: ignore[method-assign]
            try:
                view._refresh_list()
                await pilot.pause()
            finally:
                TodoListView._rows_for_refresh = original_rows  # type: ignore[method-assign]

            # The racing write must still be pending, not swallowed.
            view._poll_for_external_changes()
            await pilot.pause()
            assert _item_rows(table) == 2

    async def test_repeated_refresh_failure_toasts_once_per_streak(
        self,
        seeded_storage: SqliteStorage,
        db_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A persistently broken database must not stack an error toast
        every 2 seconds forever."""
        from todo.exceptions import StorageError
        from todo.tui.list_view import TodoListView

        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            notices: list[str] = []
            monkeypatch.setattr(
                view, "notify", lambda msg, **kw: notices.append(str(msg))
            )

            def boom(self: SqliteStorage, **kwargs: object):  # type: ignore[no-untyped-def]
                raise StorageError("no such table: todos")

            # An external write makes every tick see a version change, so
            # each tick genuinely attempts (and fails) a refresh.
            other = SqliteStorage(db_path)
            add_todo(other, "external")
            other.close()

            monkeypatch.setattr(SqliteStorage, "list", boom)
            for _ in range(5):
                view._poll_for_external_changes()
                await pilot.pause()
            assert len(notices) == 1

    async def test_deleted_filtered_project_is_named_not_question_mark(
        self, db_path: Path
    ) -> None:
        """A deleted filtered project must still be nameable in the status
        bar (round-10 regression: it degraded to '?')."""
        from todo.application.commands import add_project, delete_project
        from todo.tui.list_view import TodoListView

        storage = SqliteStorage(db_path)
        project = add_project(storage, "Apollo")
        add_todo(storage, "in apollo", project_id=project.id)
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("p")
            await pilot.pause()

            other = SqliteStorage(db_path)
            delete_project(other, project.id)
            other.close()

            view = app.query_one(TodoListView)
            view._refresh_list()
            await pilot.pause()
            status = str(app.query_one("#search-status", Static).render())
            assert "?" not in status
            assert "Apollo" in status


class TestCreateUnderActiveFilter:
    async def test_new_item_lands_in_the_filtered_project(self, db_path: Path) -> None:
        """Creating while a project filter is active must not produce an
        item the user can never see."""
        from todo.application.commands import add_project

        storage = SqliteStorage(db_path)
        project = add_project(storage, "Alpha")
        add_todo(storage, "Alpha work item", project_id=project.id)
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("p")  # filter: Alpha
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            for ch in "Buy milk":
                await pilot.press(ch)
            for _ in range(4):
                await pilot.press("enter")
                await pilot.pause()

            created = next(
                i for i in storage.list(include_done=True) if i.title == "Buy milk"
            )
            assert created.project_id == project.id
            table = app.query_one("#item-list", DataTable)
            assert _item_rows(table) == 2  # visible, not invisible

    async def test_new_item_visible_with_no_filter(self, db_path: Path) -> None:
        storage = SqliteStorage(db_path)
        app = TodoApp(storage=storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("n")
            await pilot.pause()
            for ch in "Solo":
                await pilot.press(ch)
            for _ in range(4):
                await pilot.press("enter")
                await pilot.pause()
            created = next(
                i for i in storage.list(include_done=True) if i.title == "Solo"
            )
            assert created.project_id is None
