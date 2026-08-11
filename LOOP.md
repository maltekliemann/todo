# Autonomous development loop — todo app

You are running in a self-paced loop (~60s downtime between iterations) inside
`/Users/malte/airlock/todo`. Your mission: finish this todo app to a state that is
**clean, perfectly executed, properly tested, and working** — per `PRD.md` and the
roadmap in `ROADMAP.md`. The user is away for up to 12–24 hours. Do not ask questions;
make sensible decisions and record them in the Decisions section of `ROADMAP.md`.

## Each iteration

1. Read `ROADMAP.md`. If the previous iteration left the repo red (failing gates,
   uncommitted half-done work), restoring green is the first task.
2. Pick the next unchecked task (top to bottom, unless something is blocked).
   Implement it **completely**: code + tests + docs (PRD.md/README.md where behavior
   changed). An iteration may take as long as it needs — the 60s is downtime, not a
   time limit. Prefer finishing one task per iteration over starting several.
3. Run the quality gates (below). Fix everything they surface.
4. Commit with a conventional-commit message (`feat:`/`fix:`/`refactor:`/`test:`/
   `chore:`), small and self-contained. Never push. End commit messages with:
   `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
5. Update `ROADMAP.md`: check off the task, add an Iteration Log line
   (one sentence: what was done, gate status), record any decisions made.
6. Schedule the next wakeup with ScheduleWakeup: `delaySeconds: 60`,
   `prompt: "Follow the instructions in /Users/malte/airlock/todo/LOOP.md"`,
   `noop: false` when work happened. Keep looping until the stop condition.

## Quality gates (all must pass before every commit)

```
uv run pytest -q
uv run mypy
uv run ruff check src tests
uv run ruff format --check src tests
```

Until the tooling task (Phase 0) is done, use
`uv run --with pytest --with pytest-asyncio pytest -q` as the test gate.
After Phase 0, `just test` / `just lint` / `just fmt` must also work via uv.

## Hard rules

- **Never touch `~/.todo/todos.db`** or any real user data. Tests and manual smoke
  runs use a temp DB via `TODO_DB` (tests already do this via `conftest.py` — keep it
  that way). Temp files go to the session scratchpad, not the repo.
- **Never push, never force-anything, never rewrite committed history.** Commit to
  `main` only, small commits.
- **Clean architecture is a requirement, not a preference.** Layer rules:
  - `domain/` imports stdlib + `domain` only.
  - `application/` imports stdlib, `domain`, `application`, `exceptions` only —
    never adapters, infra, tui, click, rich, textual, sqlite3.
  - `adapters/` implement `application/contracts` protocols; no click/textual.
  - `infra/cli` and `tui/` are thin: parse input, call `application` functions,
    render output via `adapters/output`. Business logic never lives here.
  - There is a roadmap task to enforce this with an automated test — after it
    exists, it is part of the gate.
- Strict mypy stays strict; do not weaken `[tool.mypy]` to make errors go away.
  Targeted per-line `# type: ignore[code]` needs a reason comment only if genuinely
  unavoidable (e.g. untyped third-party decorator).
- New DB schema changes must migrate existing databases in place (PRAGMA
  `user_version`-gated migrations in `sqlite_storage.py`); a fresh DB and an
  upgraded old DB must end up identical. Test both paths.
- TUI work is verified with `textual` Pilot tests (`tests/test_tui.py` has the
  pattern). Never launch the interactive TUI in the loop.
- If genuinely stuck on the same task after 3 attempts, mark it `[BLOCKED: reason]`
  in ROADMAP.md, move on, and revisit at the end.

## Stop condition

When every roadmap task is checked (or explicitly BLOCKED with a reason), run the
final verification phase in `ROADMAP.md`. Then do one full extra review iteration:
re-read the diff of everything the loop produced (`git log` / `git diff` against the
starting commit `658ec6b`), hunt for bugs, dead code, doc drift, and architecture
violations. If that pass finds nothing to fix, write `FINAL_REPORT.md` (what was
built, decisions taken, test/coverage numbers, anything BLOCKED and why), commit it,
and end the loop with `ScheduleWakeup {stop: true}`. If it finds problems, fix them
and repeat — the loop only stops on a clean review pass.
