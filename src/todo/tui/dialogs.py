"""The modal screens for creating, confirming and searching."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timezone

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Select, Static

from todo.application.contracts.counter_store import CounterStore
from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemStore
from todo.application.workflows.add_blocker import AddBlocker
from todo.application.workflows.create_todo import CreateTodo
from todo.application.workflows.take_item_id import TakeItemId
from todo.domain.body import Body
from todo.domain.deadline import Deadline
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.title import Title
from todo.domain.todo_item import TodoItem
from todo.exceptions import TodoError
from todo.tui.blockers import BlockerPicker
from todo.tui.edit_session import EditorSession
from todo.tui.render import escape_markup
from todo.tui.tag_input import parse_tag_input


class ConfirmDialog(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n,escape", "no", "No"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Container(id="confirm-container"):
            yield Label(self._message)
            # Text, not markup: Textual parses "[y]"/"[n]" as style tags
            # and would render the hint with no key labels at all.
            yield Label(Text("[y] Yes   [n] No"), id="confirm-hint")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class AdvancingSelect(Select[str]):
    """Priority Select with keyboard-friendly behavior.

    - Enter / Down (when closed): advance to the next field
    - Up (when closed): go back to the previous field
    - Right (when closed): step priority up (low → medium → high → urgent)
    - Left (when closed): step priority down (urgent → high → medium → low)
    - Space: open the dropdown
    """

    _PRIORITY_ORDER = ["low", "medium", "high", "urgent"]

    BINDINGS = [
        Binding("enter", "advancing_submit", show=False),
        Binding("down", "advancing_submit", show=False),
        Binding("up", "advancing_retreat", show=False),
        Binding("left", "step_down", show=False),
        Binding("right", "step_up", show=False),
    ]

    class Submitted(Message):
        def __init__(self, select: "AdvancingSelect") -> None:
            super().__init__()
            self.select = select

        @property
        def control(self) -> "AdvancingSelect":
            return self.select

    class Retreated(Message):
        def __init__(self, select: "AdvancingSelect") -> None:
            super().__init__()
            self.select = select

        @property
        def control(self) -> "AdvancingSelect":
            return self.select

    def action_advancing_submit(self) -> None:
        if not self.expanded:
            self.post_message(self.Submitted(self))

    def action_advancing_retreat(self) -> None:
        if not self.expanded:
            self.post_message(self.Retreated(self))

    def action_step_down(self) -> None:
        self._step(-1)

    def action_step_up(self) -> None:
        self._step(1)

    def _step(self, direction: int) -> None:
        if self.expanded:
            return
        try:
            idx = self._PRIORITY_ORDER.index(str(self.value))
        except ValueError:
            idx = 1
        new_idx = max(0, min(len(self._PRIORITY_ORDER) - 1, idx + direction))
        self.value = self._PRIORITY_ORDER[new_idx]


class FieldScroll(VerticalScroll):
    """A scroll container whose keys still belong to the form.

    VerticalScroll binds the arrow keys to scrolling, and as an ancestor
    of the focused field it would swallow the dialog's field navigation.
    Scrolling still happens — as the side effect of focus moving to a
    field outside the visible window, and by mouse wheel.
    """

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        return not action.startswith("scroll_")


class FormField(Static, can_focus=True):
    """A form row whose value is made somewhere richer, never typed here.

    Space opens that somewhere — a picker, $EDITOR — and the field only
    shows what came back. The walking keys stay the form's, exactly like
    the priority Select: Enter and ↓ move on, ↑ moves back.
    """

    BINDINGS = [
        Binding("space", "pick", show=False),
        Binding("enter", "submit", show=False),
        Binding("down", "submit", show=False),
        Binding("up", "retreat", show=False),
    ]

    class Pick(Message):
        def __init__(self, field: "FormField") -> None:
            super().__init__()
            self.field = field

        @property
        def control(self) -> "FormField":
            return self.field

    class Submitted(Message):
        def __init__(self, field: "FormField") -> None:
            super().__init__()
            self.field = field

        @property
        def control(self) -> "FormField":
            return self.field

    class Retreated(Message):
        def __init__(self, field: "FormField") -> None:
            super().__init__()
            self.field = field

        @property
        def control(self) -> "FormField":
            return self.field

    def action_pick(self) -> None:
        self.post_message(self.Pick(self))

    def action_submit(self) -> None:
        self.post_message(self.Submitted(self))

    def action_retreat(self) -> None:
        self.post_message(self.Retreated(self))


class BlockerField(FormField):
    """The blocked-by row: chosen from a menu, because an id is not
    something to remember and type — that is the picker's whole argument."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._value: tuple[ItemId, ...] = ()

    @property
    def value(self) -> list[ItemId]:
        return list(self._value)

    def set_value(self, blockers: Iterable[ItemId]) -> None:
        self._value = tuple(sorted(blockers))
        if self._value:
            text = Text(", ".join(b.label for b in self._value))
            text.append("  · Space to change", style="dim")
        else:
            text = Text("none — Space to choose", style="dim")
        self.update(text)

    def on_mount(self) -> None:
        self.set_value(self._value)


class BodyField(FormField):
    """The body row: prose, so it is written in $EDITOR, not a line widget.

    The same exception the item menu makes for the same reason — the row
    only says how much is there.
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._text = ""

    @property
    def text(self) -> str:
        return self._text

    def set_text(self, text: str) -> None:
        self._text = text
        if self._text:
            lines = len(self._text.splitlines())
            shown = Text(f"{lines} line{'' if lines == 1 else 's'}")
            shown.append("  · Space to edit", style="dim")
        else:
            shown = Text("empty — Space to write", style="dim")
        self.update(shown)

    def on_mount(self) -> None:
        self.set_text(self._text)


class NewItemDialog(ModalScreen[TodoItem | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "field_advance", show=False),
        Binding("up", "field_retreat", show=False),
    ]

    def __init__(
        self,
        items: ItemStore,
        dependencies: DependencyStore,
        item_ids: CounterStore,
    ) -> None:
        super().__init__()
        self._items = items
        self._dependencies = dependencies
        self._item_ids = item_ids

    def compose(self) -> ComposeResult:
        # A scroll container, not a plain Vertical: with every field the
        # item has, the dialog is taller than a short terminal, and focus
        # moving to a field scrolls it into view.
        with FieldScroll(id="dialog-container"):
            yield Label("New Todo", id="dialog-title")
            yield Label("Title:")
            yield Input(id="new-title", placeholder="What needs to be done?")
            yield Label("Priority:")
            yield AdvancingSelect(
                [(p.value, p.value) for p in Priority],
                value="medium",
                id="new-priority",
                allow_blank=False,
            )
            yield Label("Deadline (YYYY-MM-DD, optional):")
            yield Input(id="new-deadline", placeholder="")
            yield Label("Tags (comma-separated, optional):")
            yield Input(id="new-tags", placeholder="")
            yield Label("Blocked by (optional):")
            yield BlockerField(id="new-blockers")
            yield Label("Body (optional):")
            yield BodyField(id="new-body")
            yield Label("", id="dialog-error")
            yield Label(
                "↓/Enter next · ↑ prev · ←/→ priority · Esc cancel",
                id="dialog-hint",
            )

    def on_mount(self) -> None:
        self.query_one("#new-title", Input).focus()

    def _set_error(self, msg: str) -> None:
        self.query_one("#dialog-error", Label).update(msg)

    def _clear_error(self) -> None:
        self.query_one("#dialog-error", Label).update("")

    def _check_title(self) -> bool:
        title = self.query_one("#new-title", Input).value.strip()
        if not title:
            self._set_error("Title is required")
            return False
        return True

    def _check_deadline(self) -> bool:
        deadline_str = self.query_one("#new-deadline", Input).value.strip()
        if not deadline_str:
            return True
        try:
            date.fromisoformat(deadline_str)
        except ValueError:
            self._set_error("Invalid date — use YYYY-MM-DD")
            return False
        return True

    @on(Input.Submitted, "#new-title")
    def _on_title_submit(self) -> None:
        if not self._check_title():
            return
        self._clear_error()
        self.query_one("#new-priority", AdvancingSelect).focus()

    @on(AdvancingSelect.Submitted, "#new-priority")
    def _on_priority_submit(self) -> None:
        self._clear_error()
        self.query_one("#new-deadline", Input).focus()

    @on(AdvancingSelect.Retreated, "#new-priority")
    def _on_priority_retreat(self) -> None:
        self._clear_error()
        self.query_one("#new-title", Input).focus()

    @on(Input.Submitted, "#new-deadline")
    def _on_deadline_submit(self) -> None:
        if not self._check_deadline():
            return
        self._clear_error()
        self.query_one("#new-tags", Input).focus()

    @on(Input.Submitted, "#new-tags")
    def _on_tags_submit(self) -> None:
        self._clear_error()
        self.query_one("#new-blockers", BlockerField).focus()

    @on(FormField.Pick, "#new-blockers")
    def _on_blockers_pick(self) -> None:
        field = self.query_one("#new-blockers", BlockerField)

        def after(selected: frozenset[ItemId] | None) -> None:
            if selected is not None:
                field.set_value(selected)

        self.app.push_screen(BlockerPicker(self._items, frozenset(field.value)), after)

    @on(FormField.Submitted, "#new-blockers")
    def _on_blockers_submit(self) -> None:
        self._clear_error()
        self.query_one("#new-body", BodyField).focus()

    @on(FormField.Retreated, "#new-blockers")
    def _on_blockers_retreat(self) -> None:
        self._clear_error()
        self.query_one("#new-tags", Input).focus()

    @on(FormField.Pick, "#new-body")
    def _on_body_pick(self) -> None:
        field = self.query_one("#new-body", BodyField)
        edited = EditorSession(self, self._items).run_text(field.text)
        if edited is not None:
            field.set_text(edited)

    @on(FormField.Submitted, "#new-body")
    def _on_body_submit(self) -> None:
        self.action_save()

    @on(FormField.Retreated, "#new-body")
    def _on_body_retreat(self) -> None:
        self._clear_error()
        self.query_one("#new-blockers", BlockerField).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_field_advance(self) -> None:
        focused = self.focused
        if focused is None:
            return
        if focused.id == "new-title":
            self._on_title_submit()
        elif focused.id == "new-deadline":
            self._on_deadline_submit()
        elif focused.id == "new-tags":
            self._on_tags_submit()
        # priority, blocked-by and body carry their own arrow bindings

    def action_field_retreat(self) -> None:
        focused = self.focused
        if focused is None:
            return
        if focused.id == "new-deadline":
            self._clear_error()
            self.query_one("#new-priority", AdvancingSelect).focus()
        elif focused.id == "new-tags":
            self._clear_error()
            self.query_one("#new-deadline", Input).focus()
        # title has no previous; priority, blocked-by and body bind their own up

    def action_save(self) -> None:
        if not self._check_title():
            self.query_one("#new-title", Input).focus()
            return
        if not self._check_deadline():
            self.query_one("#new-deadline", Input).focus()
            return
        blockers = self.query_one("#new-blockers", BlockerField).value

        title = self.query_one("#new-title", Input).value.strip()
        priority = Priority.from_string(
            str(self.query_one("#new-priority", AdvancingSelect).value)
        )
        deadline_str = self.query_one("#new-deadline", Input).value.strip()
        deadline = date.fromisoformat(deadline_str) if deadline_str else None
        tags_str = self.query_one("#new-tags", Input).value.strip()
        tags = parse_tag_input(tags_str) if tags_str else None
        # As it came back from $EDITOR: the body has no rule, and that is
        # its point.
        body = self.query_one("#new-body", BodyField).text

        try:
            # Blockers are re-checked BEFORE the item is written: they were
            # picked from a list, but an item can vanish between the pick
            # and the save, and that must fail the whole form rather than
            # leave a half-made item behind.
            missing = next((b for b in blockers if not self._items.exists(b)), None)
            if missing is not None:
                self._set_error(f"No item {missing.label}")
                self.query_one("#new-blockers", BlockerField).focus()
                return
            stamp = datetime.now(tz=timezone.utc)
            item = TodoItem(
                id=TakeItemId(self._item_ids).execute(),
                title=Title(title),
                body=Body(body),
                priority=priority,
                status=Status.TODO,
                created_at=stamp,
                updated_at=stamp,
                deadline=Deadline.from_date(deadline) if deadline else None,
                tags=frozenset(Tag(t) for t in tags or ()),
            )
            CreateTodo(self._items).execute(item)
        except (TodoError, ValueError) as exc:
            # E.g. a locked database or a rejected tag: report inline and
            # keep the dialog (and the user's typed input) alive.
            self.query_one("#dialog-error", Label).update(
                Text(str(exc) if str(exc) else "Could not save item")
            )
            return
        if blockers:
            try:
                AddBlocker(self._items, self._dependencies).execute(item.id, blockers)
            except TodoError as exc:
                # Existence was checked before the item was written, so
                # only a race lands here. The item exists either way, so
                # the dialog closes and the failure is reported where the
                # list will show it.
                self.app.notify(escape_markup(str(exc)), severity="error")
        self.dismiss(item)


class SearchDialog(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="search-container"):
            yield Label("Search (Enter to apply, Esc to cancel):")
            yield Input(id="search-input", placeholder="Title, body, or tag...")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()

    @on(Input.Submitted, "#search-input")
    def on_submit(self) -> None:
        value = self.query_one("#search-input", Input).value.strip()
        self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)
