# WORK

PRD audit run 2026-08-12 against commit 9edf848. Every item below was
reproduced against the running code before being listed.

## todo

1. **`todo project rm` has no `--json`.** PRD:80 — "all project commands
   support `--json`". Repro: `todo project rm platform --json` →
   `Error: No such option '--json'.`
2. **TUI `j` / `k` don't move the selection.** PRD § Key Bindings.
   Repro: press `j` in the TUI, `cursor_row` unchanged; `down` moves it.
3. **TUI `←`/`h` and `→`/`l` don't change an item's status.** PRD § Key
   Bindings, and the footer legend in the PRD mock (`[←→]status`). Repro:
   pressing `l`, `right`, `h`, `left` leaves `status` at `todo`. `<` and
   `>` do work and stay.
4. **TUI has no priority colour coding.** PRD § Priority Color Coding —
   urgent red, high orange, low dim. Repro: every cell in the table comes
   back with `style == ""`; only blocked rows get `dim`.
5. **TUI does not highlight approaching/overdue deadlines.** PRD § Deadline
   Warnings — "`todo ui` highlights rows with approaching/overdue deadlines
   in the TUI". Repro: the `🔴 Aug 09 (3d overdue)` cell has `style == ""`.
6. **`tui/list_view.py` is 1259 lines holding 8 classes plus the editor
   protocol.** LOOP3 § Maintain clean architecture — "one reason to change
   per module, no file over ~400 lines".

## declined

- **`Enter` should edit in `$EDITOR`** (PRD § Key Bindings). Declined: the
  hand-written commit 658ec6b ("add view modal") deliberately bound `Enter`
  to the inspect modal. `e` edits. Later intent beats the PRD line.
- **`Esc` should quit** (PRD § Key Bindings). Declined: 6b0f47f deliberately
  bound `Esc` to clearing the filter. `q` quits.
- **`🚧` prefix missing from piped `todo list`** (PRD:221). Declined: the
  Rich TTY list — the human CLI list — carries it; plain output is the
  machine format and is deliberately undecorated.
- **Overdue "sorted to top"** (PRD § Deadline Warnings). Declined: overdue
  already sorts first inside its status group, which is what the PRD's own
  example list shows.

## done
