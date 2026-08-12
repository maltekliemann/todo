# Final Report — autonomous development loop

17 iterations, 2026-08-11 → 2026-08-12. Baseline `658ec6b` → 36 commits.
Every roadmap task completed; nothing left BLOCKED.

## What was built

**Blockers** (finishing the in-flight work found uncommitted at start)
- `todo_dependencies` join table, cascade deletes, cycle/self-block rejection.
- CLI: `block`/`unblock` (multiple ids per call), `list --blocked`,
  `list --ready` (actionable: not done, not blocked).
- Completing/moving a blocker to done reports newly unblocked dependents:
  🔓 warnings on stderr in the CLI (stdout stays JSON-clean), toasts in TUI.
- TUI: 🚧 marker + dimmed rows for blocked items, `b` dialog adds a blocker
  by id and removes via `-id`; detail pane and inspect show both directions.

**Labels: search & filter**
- `todo tags` — usage counts, most-used first.
- `list --tag` repeatable with AND semantics; `list --search` over title/body
  (case-insensitive, `%`/`_`/`\` match literally).
- TUI: `t` cycles a tag filter, `1`–`4` toggle priority filters, `0` clears
  everything; active filters shown in a status line.

**Projects** (label = lightweight marker; project = first-class container)
- `projects` table + nullable `project_id` on todos (delete unassigns).
- CLI: `project add/list/show/edit/archive/rm/log`, all with `--json`;
  `--project` on `add`/`edit` (`none` clears)/`list`. Name-or-id resolution.
- `project show` renders description, x/y-done progress, the update log
  (newest first), and the project's items.
- TUI: project in detail views, `p` cycles a project filter.

**TUI sticky-cursor mode**
- `.` toggles follow-item (default) vs stay-on-row, so repeated `d` cleans a
  list top-down without re-navigating. Mode shown in the status line.

**Infrastructure & quality**
- Versioned in-place migrations via `PRAGMA user_version` (now v2); fresh and
  upgraded databases are verified schema-identical, and a smoke test upgrades
  a real pre-loop database with data intact.
- Dev tooling fixed: `dev` dependency group (pytest, pytest-asyncio,
  pytest-cov, mypy, ruff), justfile runs through `uv run`.
- `tests/test_architecture.py` machine-enforces the hexagonal layer rules
  (zero violations found).
- PRD.md and README.md updated to match everything above.

## Bugs found and fixed along the way

- **Rich markup crash**: medium-priority items (the default) rendered
  `[]…[/]`, crashing `todo list`/`summary` in a real terminal. Caught by the
  new RichOutput unit tests; fixed with a `_styled()` guard.
- **Traceback on bad input**: `--deadline garbage` raised a raw ValueError;
  now exits 1 with a clear message.
- 84 phantom mypy errors were just missing dev installs; strict mode was
  never weakened.

## Numbers

- Tests: 107 → **208 passed** (CLI, TUI via textual Pilot, storage,
  migrations, Rich output units, domain units, architecture).
- Coverage: 80% → **89%** overall (domain 100%, application 96–100%,
  output 42% → 90%).
- Gates on every commit: pytest, strict mypy (0 errors), ruff check,
  ruff format.

## Decisions taken (details in ROADMAP.md)

- TUI search stays a modal dialog; the status line is the filter readout.
- Tag/project filters cycle with `t`/`p` to stay keyboard-driven.
- Project ↔ label distinction documented in PRD (container vs marker).
- Project updates ("log") implemented as the stretch goal, migration v2.

## Known limits (deliberate, documented out-of-scope)

- Multi-user/sync, subtasks, MCP server, web UI — unchanged from PRD.
- TUI list filtering (search/tag/project/priority) happens in view state over
  fetched items; fine at personal-todo scale.

## Process notes

- One commit (ba5e3ac) landed with a red flaky test, fixed in the immediate
  follow-up (a5293ae); noted per the loop's honesty rule.
- Final verification: clean-state gates, scripted end-to-end CLI smoke on a
  temp DB, migration smoke from the true pre-loop schema, full-diff review
  vs `658ec6b` (findings: one dead function, one doc drift — fixed in
  4baa38d).
