# Roadmap — state file for the autonomous loop (see LOOP.md)

Work top to bottom. Check tasks off as they complete. Log every iteration at the
bottom. Baseline commit before the loop started: `658ec6b`.

## Phase 0 — Tooling & baseline ✅

- [x] Add a `dev` dependency group: pytest, pytest-asyncio, pytest-cov, mypy,
      ruff. All gates run via `uv run`; `uv.lock` committed. (1171366)
- [x] Fix mypy: all 84 errors were missing-import noise; zero errors once dev
      deps are installed. Strict mode untouched.
- [x] `justfile` recipes run through `uv run`; lint recipe also checks
      formatting. (1171366)
- [x] `ruff format` applied repo-wide as a style-only commit. (3034dca)
- [x] Blockers WIP reviewed (contracts, cycle detection, TUI dialog, 24 new
      tests) and committed; PRD.md documents dependencies, block/unblock, 🚧.
      (f4123f8)

## Phase 1 — Blockers: finish the feature

- [ ] CLI: `todo list --blocked` (only blocked items) and `todo list --ready`
      (actionable: not done, not blocked). Filtering logic lives in
      application/queries, not in the CLI layer.
- [ ] `done`/`mv`-to-done on an item that still blocks others: allowed, but warn on
      stderr listing the newly unblocked items (nice UX, keep it simple).
- [ ] TUI: detail pane shows Blocked by / Blocking (verify it does); blocked rows
      get a distinct style; `b` binding opens a small input to add/remove a blocker
      by id (comma/`-` prefix to remove, or similar — decide and document).
- [ ] Tests: cycle chains (a→b→c→a), self-block, unblock-nonexistent, blocked
      styling in TUI, JSON output includes dependency fields.

## Phase 2 — Labels: search & filter

- [ ] CLI: `todo tags` — list all tags with usage counts (plus `--json`).
- [ ] CLI: `--tag` repeatable on `list` with AND semantics; keep single-tag
      behavior backward compatible.
- [ ] CLI: `todo list --search TEXT` — case-insensitive substring match over title
      and body. Implement in storage (SQL LIKE with proper escaping), expose
      through application/queries.
- [ ] TUI: implement the PRD's filter bar — `/` focuses a search input that
      live-filters the table (title/body); Esc clears/unfocuses. A tag filter
      (Select or cycling with a key) alongside it. `0` clears all filters
      (PRD binding).
- [ ] Tests: tag AND-filtering, search edge cases (case, unicode, `%`/`_`
      literals), TUI search interaction via Pilot.

## Phase 3 — Projects

Design decision (already made — record deviations in Decisions): a **label** is a
lightweight cross-cutting marker; a **project** is a first-class container with
identity and lifecycle. Todos belong to at most one project (`project_id` FK,
nullable). Projects have: `id`, `name` (unique), `description`, `status`
(active/archived), `created_at`, `updated_at`. Project **updates** (timestamped
free-text notes on a project) are a stretch goal — do them last if everything else
is done.

- [ ] Schema migration via `PRAGMA user_version`: new `projects` table,
      `project_id` column on todos (`ON DELETE SET NULL`). Fresh DB == migrated DB;
      test both.
- [ ] Domain model `Project` (frozen dataclass) + storage protocol methods +
      sqlite implementation.
- [ ] CLI: `todo project add NAME [--description]`, `todo project list`
      (with open/done counts per project), `todo project show NAME_OR_ID` (details,
      progress, its todos), `todo project edit`, `todo project archive`,
      `todo project rm` (todos survive, unassigned). All with `--json`.
- [ ] CLI: `todo add --project NAME`, `todo edit N --project NAME|none`,
      `todo list --project NAME`.
- [ ] TUI: project shown in detail pane; filter by project (key or Select widget).
- [ ] PRD.md: new Projects section incl. the label-vs-project rationale;
      remove/adjust the stale "Out of scope" bullets this obsoletes.
- [ ] Stretch: `todo project log NAME "update text"` + updates shown in
      `project show`.

## Phase 4 — TUI: sticky-cursor mode

- [ ] Add a cursor-mode toggle for status moves (`←`/`→`/`d`): **follow** (default,
      cursor follows the item to its new position) vs **stay** (cursor keeps its
      visual row, so repeatedly hitting `d` cleans a list top-down without
      re-navigating). Pick a free key (e.g. `.` or `g`), show current mode in the
      footer/status area, document in PRD key-binding table.
- [ ] Pilot tests for both modes, including edge rows (last row, done-section
      boundary).

## Phase 5 — Architecture & hardening

- [ ] Add `tests/test_architecture.py`: walk `src/todo` module imports and assert
      the layer rules from LOOP.md (domain imports nothing outer, application never
      imports adapters/infra/tui/click/rich/textual/sqlite3, etc.). This becomes
      part of the standard gate.
- [ ] Audit TUI/CLI for business logic that belongs in application layer; move it.
- [ ] Error-handling audit: consistent exit codes and stderr messages across CLI;
      `TodoError` hierarchy used consistently.
- [ ] Coverage run (`just cov`): ≥90% on domain/application/adapters; fill gaps
      with meaningful tests (not assertion-free padding).
- [ ] README.md: refresh usage docs for all new commands.

## Phase 6 — Final verification (see LOOP.md stop condition)

- [ ] From a clean checkout state: `uv sync && uv run pytest -q && uv run mypy &&
      uv run ruff check src tests && uv run ruff format --check src tests` all green.
- [ ] Scripted end-to-end smoke against a temp `TODO_DB`: add/list/search/block/
      project flow via the real CLI; verify JSON output parses.
- [ ] Migration smoke: build a DB with the pre-loop schema (commit `658ec6b`),
      run current code against it, verify data intact.
- [ ] Full-diff review pass vs `658ec6b`; then write `FINAL_REPORT.md` and stop
      the loop.

## Decisions

- (record decisions the loop makes here, with one-line rationale)

## Iteration log

- 2026-08-11 iter 1: Phase 0 complete — dev deps + gates working, justfile via
  uv, blockers feature committed (f4123f8), repo-wide format (3034dca). All
  gates green: 107 passed, mypy clean, ruff clean.
