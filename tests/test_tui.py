from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets import DataTable, Label, Static

from todo.adapters.sqlite_storage import SqliteStorage
from todo.application.commands import add_todo
from todo.domain.enums import Priority, Status
from todo.tui.app import TodoApp
from todo.tui.list_view import TodoListView


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
        async with app.run_test() as pilot:
            assert app.is_running
            table = app.query_one("#item-list", DataTable)
            # 3 seeded items, all active (none done)
            assert table.row_count == 3

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
    async def test_x_opens_confirm_dialog(
        self, seeded_storage: SqliteStorage
    ) -> None:
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
                i for i in seeded_storage.list(include_done=True)
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
            assert app.screen.query_one(
                "#new-priority", AdvancingSelect
            ).has_focus

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
            assert app.screen.query_one(
                "#new-priority", AdvancingSelect
            ).has_focus

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

        from todo.tui.list_view import AdvancingSelect

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



class TestSearch:
    async def test_slash_opens_search(self, seeded_storage: SqliteStorage) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash")
            await pilot.pause()
            from todo.tui.list_view import SearchDialog

            assert isinstance(app.screen, SearchDialog)

    async def test_search_filters_list(
        self, seeded_storage: SqliteStorage
    ) -> None:
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
            assert table.row_count == 1

    async def test_escape_clears_search(
        self, seeded_storage: SqliteStorage
    ) -> None:
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
            assert app.query_one("#item-list", DataTable).row_count == 1

            # Clear
            await pilot.press("escape")
            await pilot.pause()
            assert app.query_one("#item-list", DataTable).row_count == 3


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


class TestExternalChangePolling:
    """The TUI should pick up changes made via the CLI (or any other process)."""

    async def test_external_add_appears(
        self, seeded_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            initial_rows = app.query_one("#item-list", DataTable).row_count

            # Simulate the CLI adding an item via a separate connection
            from pathlib import Path

            other = SqliteStorage(Path(seeded_storage._conn.execute(
                "PRAGMA database_list"
            ).fetchone()[2]))
            add_todo(other, "Added by CLI", priority=Priority.MEDIUM)
            other.close()

            # Trigger the poll
            view = app.query_one(TodoListView)
            view._poll_for_external_changes()
            await pilot.pause()

            new_rows = app.query_one("#item-list", DataTable).row_count
            assert new_rows == initial_rows + 1

    async def test_external_delete_disappears(
        self, seeded_storage: SqliteStorage
    ) -> None:
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            initial_rows = app.query_one("#item-list", DataTable).row_count

            from pathlib import Path

            other = SqliteStorage(Path(seeded_storage._conn.execute(
                "PRAGMA database_list"
            ).fetchone()[2]))
            other.delete(1)
            other.close()

            view = app.query_one(TodoListView)
            view._poll_for_external_changes()
            await pilot.pause()

            new_rows = app.query_one("#item-list", DataTable).row_count
            assert new_rows == initial_rows - 1

    async def test_no_refresh_when_unchanged(
        self, seeded_storage: SqliteStorage
    ) -> None:
        """Polling should be a no-op when data hasn't changed."""
        app = TodoApp(storage=seeded_storage)
        async with app.run_test() as pilot:
            await pilot.pause()
            view = app.query_one(TodoListView)
            v1 = view._last_data_version
            view._poll_for_external_changes()
            await pilot.pause()
            assert view._last_data_version == v1


class TestKeyBindingsDontHang:
    """Regression tests: ensure no key binding locks up the UI."""

    @pytest.mark.parametrize(
        "key",
        ["l", "h", "left", "right", "j", "k", "up", "down",
         "greater_than_sign", "less_than_sign"],
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
