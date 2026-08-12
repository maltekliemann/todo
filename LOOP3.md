# LOOP3

## The work list

Keep `WORK.md`. It is the single source of truth for what is left. Every item
has: a one-line description, a **reproduction or a PRD reference proving the
problem is real**, and a status (`todo` / `done` / `declined + reason`).

Nothing gets worked on that is not on the list. Only two things may ever be
added to it:

1. A gap found by the PRD audit (below).
2. A correctness finding that passed all four conditions in "Handling a bad
   reviewer".

Nothing else. Not a hunch, not something noticed in passing, not a reviewer
suggestion that failed the conditions. If it isn't on the list with a
reproduction, it is not a problem.

**When the list has no `todo` items left, the work is done. Stop.**

At any moment there are exactly two valid states: working on a listed item with
a recorded reproduction, or stopped. There is no third state.

## Implement the features I asked for

First action, before any code change: walk `PRD.md` section by section and check
each stated behavior against the actual code or the running CLI. Every gap goes
on the list with its PRD section as the reference. This audit happens once. The
resulting set is the feature work.

## Maintain clean architecture

Hexagonal / ports-and-adapters, matching choochoo conventions. The five layers
and their jobs, per `PRD.md` § Project Structure:

1. **`domain/`** — pure models, no dependencies. Frozen dataclasses and enums.
2. **`application/`** — business logic (`commands.py`, `queries.py`), plus
   `contracts/` holding the `@runtime_checkable` Protocols that define the
   ports it needs.
3. **`adapters/`** — external integrations: `sqlite_storage.py` implements
   `StorageProtocol`; `output.py` does Rich TTY / plain formatting.
4. **`infra/cli/`** — click entry point and wiring. The composition root.
5. **`tui/`** — the textual interactive UI.

`config.py` (DB path / env) and `exceptions.py` (TodoError hierarchy) are
dependency-free leaves.

Verify by reading, not by a test passing.

- **Direction.** domain → application → adapters → infra/tui. Nothing points
  back inward.
- **Inverted dependencies.** Ports belong to the inner layer and are expressed
  in its terms, not the adapter's. Before adding anything to `StorageProtocol`,
  ask whether a non-SQLite adapter could implement it — if not, it doesn't
  belong there.
- **Rules live in one place.** Business rules and validation belong in
  domain/application. An adapter or the TUI restating a rule is a violation
  even when the imports are legal.
- **The domain is framework-free.** No click, textual, rich, or sqlite3 types
  cross into domain or application — in either direction. Boundaries carry
  plain data and domain objects.
- **One reason to change per module.** A file holding dialogs, an editor
  protocol, and a list view is three modules. No file over ~400 lines.
- **Testable without infrastructure.** Application logic must be exercisable
  against a fake storage, with no database and no terminal.

## Don't introduce new bugs

- Write the failing test first for anything behavioral.
- Test the behavior you wrote, not the behavior described to you.
- Before changing a shared rule or helper, grep every call site and list them in
  the commit message.
- Never remove a capability. If a change removes a way to do something, the same
  commit provides the replacement.
- Commit only when `pytest`, `mypy`, `ruff check`, and `ruff format --check` all
  pass.

## Stop gaming tests

Never widen an interface, loosen a type, add a method, or relax an assertion to
make a test pass. Fix the code, or delete the test and justify it in the commit
message.

## Bring test coverage to a reasonable amount

Cover behavior. `pytest --cov=todo` to see what's uncovered. Never write a test
whose only purpose is raising the number.

## Remove bugs

Fix defects that have a concrete, reproducible, user-visible failure: wrong
output, data loss, a crash, or documented behavior that doesn't happen.

## Don't be an asshole

One line per commit. No campaign summaries, no progress essays, no restating
past mistakes. If a decision is needed, ask in one sentence and stop.

## Do proper reviews

Reproduce every candidate defect yourself before believing it. Two review
passes maximum, ever. Correctness only.

## Handling a bad reviewer

The reviewer is an advisor with no stake in the outcome. It produces a ranked,
capped list, so it will usually return roughly the same number of items no
matter how good the code is. **The count carries no information. Never treat it
as a measurement, and never use "the reviewer is happy" as a goal.**

Default is to decline. A finding earns a code change only if all four hold:

1. You reproduced it yourself.
2. It has a user-visible failure: wrong output, data loss, a crash, or
   documented behavior that doesn't happen.
3. You understand *why* it happens. Never change code to silence a complaint
   you don't understand.
4. Fixing it doesn't require inventing a new opinion. If the finding asserts a
   preference — naming, structure, "should be case-sensitive", "these look
   similar" — decline it. Do not encode a reviewer's taste as a test.

When a finding is real, **it describes a symptom, not a prescription.** Design
the fix yourself:

- Ask what depended on the current behavior before changing it. A finding that
  says "X is accepted and shouldn't be" is not permission to delete X.
- Fix at the altitude the bug actually lives at, and no higher. Do not
  generalize a mechanism because a finding hinted at it.
- Never act on cleanup, duplication, style, altitude, or performance findings
  at all. Log the ones that seem worth remembering, and move on.

An empty review is a normal, expected outcome, at any point, including the
first pass. Record every decline in one line with the reason.

## Then stop

Done means: no `todo` items remain in `WORK.md`, and the two review passes are
either used or unnecessary. At that point stop the loop and say so in one line.

Do not start another review. Do not re-audit the PRD. Do not look for more
work. A finished list is the finish.

Never `git push`. Never touch `~/.todo/todos.db`.
