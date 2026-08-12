# Hardening loop — fix all verified findings; adversarial review is the exit gate

You are running in a self-paced loop (~60s downtime) inside
`/Users/malte/airlock/todo`. The previous loop (LOOP.md) shipped features that
passed their own tests but an independent adversarial review confirmed 31 real
defects (`FINDINGS.md`). This loop exists to eliminate every one of them and to
prove it — **the loop may not declare itself done until a full adversarial
review returns clean.** Your own tests passing is a precondition, never the
conclusion.

## The core discipline (this is what the last loop lacked)

For every finding:
1. **Red first**: write a test that reproduces the failure scenario and FAILS
   on the current code. If you cannot make it fail, you have not understood
   the bug — stop and re-read the finding. Only then fix it.
2. **Fix the class, not the instance.** FINDINGS.md lists class sweeps
   (markup safety, atomicity, path parity, plain-output contract). When a
   finding is one instance of a class, the fix must cover every sink/path in
   that class, with hostile-input tests per sink. The last loop "fixed" a
   markup crash while leaving the same class live in four other places —
   do not repeat that.
3. Prefer shared code paths over parallel copies so parity can't drift.

## Each iteration

1. Read `FINDINGS.md`. If the tree is red, restore green first.
2. Take the next unchecked finding(s) — P1 before P2; group findings that
   share a root cause and fix them as one unit with their class sweep.
3. Red test → fix → full gates (`uv run pytest -q`, `uv run mypy`,
   `uv run ruff check src tests`, `uv run ruff format --check src tests`).
4. Commit (conventional message, end with
   `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`), check the box
   in FINDINGS.md with the commit hash, append a Status log line.
5. `ScheduleWakeup {delaySeconds: 60, prompt: "/loop Follow the instructions
   in /Users/malte/airlock/todo/LOOP2.md ...", noop: false}`.

A finding may only be closed without a fix via the Triage log: it requires a
genuine failed reproduction attempt written down. "Looks fine to me" is not
triage.

## The exit gate (mandatory, no exceptions)

When every FINDINGS.md box is checked and all gates are green:

1. Re-run the behavioral smokes from the first loop (e2e CLI on a temp
   `TODO_DB`; migration from the `658ec6b` schema) plus a crash-interrupted-
   migration smoke, all with hostile input (titles like `"Fix [/] thing"`).
2. Launch the adversarial review in the background:
   `Workflow({name: "code-review", args: "high 658ec6b..HEAD — Full-app
   correctness audit. Be adversarial about hostile input reaching render
   sinks, partial-failure atomicity, behavior parity across mutation paths,
   machine-output contracts, and tests that pass vacuously."})`
3. While the review runs: do NOT modify the code (it would invalidate the
   review) and do NOT start a second review. Schedule a fallback wakeup of
   1800s with `noop: true`; the completion notification will wake the loop
   earlier.
4. When the result arrives:
   - **Findings reported** → append every one to FINDINGS.md as unchecked
     items (false positives go through the Triage log with failed-repro
     evidence), and loop back to fixing. The next review pass starts from
     scratch — partial credit does not carry over.
   - **Zero findings** → the gate is passed. Then, in order: call
     ReportFindings re-reporting the 10 findings filed earlier in this
     session, each with its `outcome` (fixed / no_change_needed with the
     triage evidence); write `HARDENING_REPORT.md` (what was fixed, what was
     triaged and why, review-pass count, final numbers); commit; end the loop
     with `ScheduleWakeup {stop: true}`.

"Clean" means the review's verified findings list is empty — or contains only
items already refuted in the Triage log with failed reproduction attempts,
which the report must quote. Nothing else counts. If three consecutive review
passes fail to come back clean, keep going anyway — the stop condition does
not weaken with time.

## Hard rules (unchanged from LOOP.md)

- Never touch `~/.todo/todos.db`; tests and smokes use temp DBs via `TODO_DB`.
- Never push; never rewrite committed history; small commits to `main`.
- Layer rules are enforced by `tests/test_architecture.py` — keep it green.
- Strict mypy stays strict; never weaken a test to make it pass; never delete
  a failing test except by fixing what it tests.
- The review costs ~1M tokens per pass — run it only when the queue is empty
  and gates are green, never speculatively.
