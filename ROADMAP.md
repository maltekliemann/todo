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

- [x] CLI: `todo list --blocked` / `todo list --ready`; post-filter in
      application/queries; flags mutually exclusive; 6 new tests. (2a3ffb0)
- [x] `done`/`mv`-to-done reports newly unblocked dependents: CompletionResult
      from application layer, 🔓 stderr warnings in CLI, toast in TUI. (fb38a26)
- [x] TUI: detail pane shows Blocked by / Blocking (verified, pre-existing);
      blocked rows dimmed; `b` dialog adds by id, removes via `-id`. (4b9e557)
- [x] Tests: cycle chains, self-block, blocked TUI styling, JSON dependency
      fields all pre-existed; added unblock-nonexistent + idempotent-removal.
      (0398110)

## Phase 2 — Labels: search & filter

- [x] CLI: `todo tags` — usage counts, most-used first, --json. (7cfbab2)
- [x] CLI: `--tag` repeatable with AND semantics, single-tag compatible.
      (1008619)
- [x] CLI: `todo list --search TEXT` — SQL LIKE in storage with wildcard
      escaping, exposed via application/queries. (1008619)
- [x] TUI filters: `/` search (existing modal), `t` cycles tag filter, `1-4`
      toggle priority filter, `0` clears all; status line shows active
      filters. (ed248e8)
- [x] Tests: tag AND-filtering, search edge cases (case, unicode, `%`/`_`
      literals) in 1008619; TUI filter interactions via Pilot in ed248e8.

## Phase 3 — Projects

Design decision (already made — record deviations in Decisions): a **label** is a
lightweight cross-cutting marker; a **project** is a first-class container with
identity and lifecycle. Todos belong to at most one project (`project_id` FK,
nullable). Projects have: `id`, `name` (unique), `description`, `status`
(active/archived), `created_at`, `updated_at`. Project **updates** (timestamped
free-text notes on a project) are a stretch goal — do them last if everything else
is done.

- [x] Schema migration via `PRAGMA user_version`; fresh == migrated verified,
      idempotent, data preserved. (72d4a06)
- [x] Domain `Project` + ProjectStatus enum + protocol methods + sqlite CRUD
      with DuplicateProjectError/ProjectNotFoundError. (72d4a06)
- [x] CLI: `todo project add/list/show/edit/archive/rm` with counts, --json,
      name-or-id resolution. (965d19e)
- [x] CLI: `todo add --project`, `todo edit N --project NAME|none`,
      `todo list --project NAME`. (965d19e)
- [ ] TUI: project shown in detail pane; filter by project (key or Select widget).
- [x] PRD.md: Projects section with label-vs-project rationale and CLI
      examples. (965d19e) — "Out of scope" bullets still to review.
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

- TUI search stays a modal dialog (`/`) rather than an inline always-visible
  filter bar: same capability, already tested, one keystroke away; the status
  line acts as the "filter bar" readout. Tag filter cycles with `t` instead of
  a Select widget to keep the list keyboard-driven.

## Iteration log

- 2026-08-11 iter 1: Phase 0 complete — dev deps + gates working, justfile via
  uv, blockers feature committed (f4123f8), repo-wide format (3034dca). All
  gates green: 107 passed, mypy clean, ruff clean.
- 2026-08-11 iter 2: --blocked/--ready list filters (2a3ffb0). Gates green:
  113 passed, mypy clean, ruff clean, format clean.
- 2026-08-12 iter 3: unblock warnings on done/mv (fb38a26). Gates green:
  119 passed, mypy clean, ruff clean, format clean.
- 2026-08-12 iter 4: TUI blocked-row dimming + dialog removal (4b9e557).
  Gates green: 121 passed, mypy clean, ruff clean, format clean.
- 2026-08-12 iter 5: Phase 1 closed (unblock edge tests, 0398110) and 'todo
  tags' command (7cfbab2). Gates green: 127 passed, all clean.
- 2026-08-12 iter 6: multi-tag AND + --search with LIKE escaping (1008619).
  Gates green: 138 passed, all clean.
- 2026-08-12 iter 7: TUI tag/priority filters + clear-all, Phase 2 closed
  (ed248e8). Gates green: 142 passed, all clean.
- 2026-08-12 iter 8: projects storage foundation + user_version migrations
  (72d4a06). Fixed JOIN ambiguity in done_since and a list[]-shadowing mypy
  issue. Gates green: 154 passed, all clean.
- 2026-08-12 iter 9: full project CLI + --project on add/edit/list + PRD
  section (965d19e). Gates green: 166 passed, all clean.
