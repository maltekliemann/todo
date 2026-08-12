# WORK

PRD audit run 2026-08-12 against commit 9edf848. Every item below was
reproduced against the running code before being listed.

## todo

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

1. **`todo project rm --json`** — PRD:80. Emits the deleted project's
   record. `29ad72a`.
2. **TUI `j`/`k` navigation** — PRD § Key Bindings. `18f0f29`.
3. **TUI `h`/`l`/`←`/`→` status stepping** — PRD § Key Bindings. `<`/`>`
   kept. `18f0f29`.
4. **TUI priority colour coding** — PRD § Priority Color Coding. `c7d61bc`.
5. **TUI deadline highlighting** — PRD § Deadline Warnings. The deadline
   cell carries the colour, as in the CLI, rather than painting the whole
   row. `c7d61bc`.
