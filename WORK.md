# WORK

Round 2, opened 2026-08-13 from your list. Every item reproduced against the
running program before being listed.

## todo

_(none)_

## done

1. **The footer is cut off** — 16 bindings rendered 189 columns into a
   one-row footer, hiding everything past the edge (including `.`). Special
   keys show as `<`, `>`, `/`, `.` instead of `greater_than_sign` and
   friends; status and filter keys share a group label; the priority digits
   left the footer; the command-palette key is gone. 189 → 76 columns, and
   a test now fails if it ever exceeds 80 again. `fae5e2b`.
2. **Blockers are picked, not remembered** — `b` lists every other item,
   marks and sorts first the ones already blocking this one, and narrows as
   you type (title or id). Enter toggles. `-3` still removes blocker #3.
   `ea99cf8`.
3. **The `$EDITOR` buffer shows the project and the dependencies** — as
   commented context lines the parser never sees, so editing one cannot
   silently do nothing. `970dbd8`.
4. **Stay mode walks the list** — it now names the item that *followed* the
   one you moved, instead of holding a row index. Holding the index was why
   `>` kept re-touching the same item: a status step re-sorts it to the top
   of its new group, which is the row the cursor was on. `0f8df0c`.
5. **A `Deps` column on every row** — `←#2,#3` for what it waits on (ids,
   capped at two then `+n`), `→3` for how many wait on it. `cb718f5`.

## notes

- **`PRD.md` is now stale in one place** and I did not edit your spec: it
  describes `b` as "a dialog to add a blocker to the selected item by id
  (a `-` prefix removes it)". The `-id` form still works, but the dialog
  is a searchable picker now.
- **Self-blocking is unreachable rather than rejected.** The picker never
  offers the item itself, so the inline "an item cannot block itself"
  error no longer appears in the TUI. The domain rule is unchanged and
  still tested.

---

Round 1 (PRD audit + the TUI split) is in git history: `9edf848..3663d44`.
