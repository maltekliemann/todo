# WORK

Round 3, opened 2026-08-13. One request: **an item opens as a menu whose
fields you edit in place; `$EDITOR` is for the body and nothing else.**

Your two calls: every field except the body lives in the menu (title,
priority, status, deadline, tags, project, blockers), and `i` / `e` /
Enter collapse into that one screen — the read-only view goes away.

## done

1. **`ItemScreen`** — the menu. Rows: Title, Priority, Status, Deadline,
   Tags, Project, Blocked by, Blocking (read-only), Body. ↑↓ moves,
   Enter edits the highlighted row, Esc closes. Errors report inline and
   never close the screen; a body preview fills whatever height is left.
2. **The editing affordances** — a text prompt (title, deadline, tags),
   a choice menu (priority, status, project), and the existing searchable
   picker for blockers. Nothing is typed as `key: value` any more.
3. **`$EDITOR` carries the body alone** — no field lines, no `# Body`
   marker, so there is no format to get wrong and no parse to reject.
   `parse_editor_text` and the field parser go with it.
4. **One key opens an item** — `i`, `e` and Enter all reach `ItemScreen`;
   `InspectDialog` is deleted. The footer loses an entry.
5. **Project becomes editable** — it was context-only in the buffer and
   unreachable from the TUI; the menu picks from the existing projects
   (or none).

## what I looked at

Not widget state: the screens rendered to SVG at 80x24, 80x20 and 60x16
and read back as text. Two things only the render showed —

- the heading wrapped and left `11:10` alone on its own line (the box was
  too narrow), and
- at 60x16 the hint, and then the inline error, fell off the bottom —
  round-2 defect #7 in a new dialog.

Both fixed: a wider box, the body preview moved last so it is the only
part that gives way, and the error row shown only when it has something
to say.

## notes

- **`PRD.md` will be stale again** and I am not editing your spec: it
  describes `i` as a read-only inspect modal and `e` as the `$EDITOR`
  round trip with `title:`/`priority:`/... lines. Say the word and I
  will bring it up to date in a separate commit.
- **What the deleted inspect view could do that the menu cannot**: it
  scrolled a long body full-screen. The menu keeps a body preview, but
  it is smaller — the whole body is one Enter away in `$EDITOR`, and the
  detail pane under the table still renders it.
- **An item deleted while its screen is open** reports "not found" inline
  and stays; Esc closes it. Vanishing mid-keystroke was the alternative,
  and it explains less.
- **`Blocking` is a read-only row.** Dependents are set from their own
  side of the relation, so Enter there says where to go rather than
  opening a picker that cannot help.

---

Round 2 (the footer, the blocker picker, the Deps column, cursor modes)
is in git history: `fae5e2b..cb97d69`. Round 1 (PRD audit + the TUI
split) is `9edf848..3663d44`.
