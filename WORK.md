# WORK

Round 2, opened 2026-08-13 from your list. Every item reproduced against the
running program before being listed.

## todo

1. **The footer is cut off.** 16 bindings render 187 columns into a
   single-row footer; at width 80, 100 and 120 the tail is invisible —
   which includes `.` (cursor mode). The special keys also render under
   their raw names (`greater_than_sign`, `less_than_sign`, `full_stop`,
   `slash`) instead of `>`, `<`, `.`, `/`.
2. **Setting a blocker requires remembering an id.** `BlockDialog` is a
   bare `Input`: you type `3` to add and `-3` to remove. Wanted: pick from
   a searchable list.
3. **The `$EDITOR` buffer shows neither the project nor the blockers.**
   `item_to_editor_text` emits title/priority/status/deadline/tags/body
   only. (The inspect modal — `i` / `Enter` — does show both; verified.)
4. **Stay mode doesn't let you walk the list with `>`/`<`.** Repro: five
   items, press `.` for stay, then `>` three times. The cursor sits on row
   1 the whole time, but the item that lands on row 1 is the one just
   moved (in-progress sorts above todo), so the same item is advanced
   again and again. With `d` it happens to work, because done sorts to the
   bottom.
5. **The table shows no dependency information.** Which items block a row,
   and how many items it blocks, appear only in the detail pane for the
   selected item.

## declined

_(nothing yet this round)_

## done

_(nothing yet this round)_

---

Round 1 (PRD audit + the TUI split) is in git history: `9edf848..3663d44`.
