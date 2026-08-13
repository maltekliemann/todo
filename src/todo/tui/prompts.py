"""The two small modals the item menu edits fields with.

`TextPrompt` for a free-text field, `ChoicePrompt` for a field with a
fixed set of values. Both are pure input: they return what was entered or
chosen and never touch storage, so the screen that opened them keeps the
one path to the database — and the one place errors are reported.
"""

from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option


class TextPrompt(ModalScreen[str | None]):
    """Ask for one line of text, pre-filled with the current value.

    Returns the raw string on Enter (the caller decides what stripping and
    validation mean for its field) and None on Esc.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, label: str, initial: str = "", placeholder: str = "") -> None:
        super().__init__()
        self._label = label
        self._initial = initial
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt-container"):
            yield Label(Text(self._label), id="prompt-title")
            yield Input(
                value=self._initial, placeholder=self._placeholder, id="prompt-input"
            )
            yield Label("Enter save · Esc cancel", id="prompt-hint")

    def on_mount(self) -> None:
        field = self.query_one("#prompt-input", Input)
        # Editing an existing value starts at its end, not in front of it:
        # the common edit is appending or backspacing, not prepending.
        field.cursor_position = len(field.value)
        field.focus()

    @on(Input.Submitted, "#prompt-input")
    def on_submit(self) -> None:
        self.dismiss(self.query_one("#prompt-input", Input).value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ChoicePrompt(ModalScreen[str | None]):
    """Pick one of a fixed set of values from a menu.

    `choices` are (key, label) pairs; the key of the chosen row comes back,
    or None on Esc. The row holding the current value starts under the
    cursor, so Enter alone changes nothing.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        label: str,
        choices: Sequence[tuple[str, str]],
        current: str | None = None,
    ) -> None:
        super().__init__()
        self._label = label
        self._choices = list(choices)
        self._current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="prompt-container"):
            yield Label(Text(self._label), id="prompt-title")
            yield OptionList(id="prompt-options")
            yield Label("↑↓ move · Enter choose · Esc cancel", id="prompt-hint")

    def on_mount(self) -> None:
        options = self.query_one("#prompt-options", OptionList)
        for _, label in self._choices:
            # Text, never markup: project names are user-controlled.
            options.add_option(Option(Text(label)))
        keys = [key for key, _ in self._choices]
        if self._choices:
            current = self._current
            options.highlighted = keys.index(current) if current in keys else 0
        options.focus()

    @on(OptionList.OptionSelected, "#prompt-options")
    def on_option_selected(self, event: OptionList.OptionSelected) -> None:
        index = event.option_index
        if 0 <= index < len(self._choices):
            self.dismiss(self._choices[index][0])

    def action_cancel(self) -> None:
        self.dismiss(None)
