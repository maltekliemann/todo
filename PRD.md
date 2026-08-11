# Todo App — Product Requirements Document

## Overview

A persistent, SQLite-backed todo application with two interfaces:

1. **CLI** — scriptable commands for adding, updating, listing, and summarizing todos. Designed to be called by both humans and AI agents (e.g., Claude Code via Bash tool).
2. **TUI** — an interactive terminal UI for browsing, filtering, and managing todos visually.

---

## Data Model

Each todo item has:

| Field        | Type                                    | Notes                          |
|--------------|-----------------------------------------|--------------------------------|
| `id`         | integer, auto-increment                 | Primary key                    |
| `title`      | text                                    | Required                       |
| `body`       | text                                    | Optional longer description    |
| `priority`   | enum: urgent, high, medium, low         | Default: medium                |
| `status`     | enum: backlog, todo, in-progress, done  | Default: todo                  |
| `created_at` | datetime                                | Set on creation                |
| `updated_at` | datetime                                | Set on every mutation          |
| `done_at`    | datetime, nullable                      | Set when status moves to done  |
| `deadline`   | date, nullable                          | Optional due date              |
| `tags`       | text (comma-separated)                  | Optional, for filtering        |

SQLite database stored at `~/.todo/todos.db` (configurable via `TODO_DB` env var).

### Dependencies (blockers)

Todos can block each other. The relation is stored in a `todo_dependencies`
join table (`blocker_id`, `blocked_id`) with cascade deletes. Derived fields on
each item:

| Field        | Type          | Notes                                              |
|--------------|---------------|----------------------------------------------------|
| `blocked_by` | list of ids   | Items that must be done before this one            |
| `blocking`   | list of ids   | Items waiting on this one                          |
| `is_blocked` | bool          | True while any blocker is not done (and item isn't done) |

Rules: an item cannot block itself, and relations that would form a cycle
(directly or transitively) are rejected with an error. Completing or deleting a
blocker unblocks its dependents automatically.

---

## CLI Interface

The CLI is the primary interface for AI agents. Commands should be simple, composable, and produce clean output.

```
todo add "Deploy new auth service" --priority high --status todo --tag deploy --deadline 2026-05-01
todo list                                # all non-done items
todo list --status done                  # done items
todo list --priority urgent              # filter by priority
todo list --tag deploy                   # filter by tag
todo list --all                          # include done items
todo show 7                              # show full detail for item #7
todo edit 7 --priority urgent            # change priority
todo mv 7 in-progress                    # change status (shorthand)
todo done 7                              # mark as done (sets done_at)
todo rm 7                                # delete an item
todo block 7 3                           # item #7 is blocked by item #3
todo block 7 3 5                         # add several blockers at once
todo unblock 7 3                         # remove a blocker
todo summary --since "7 days"            # what was completed in the last 7 days
todo summary --since "2025-04-01"        # what was completed since a specific date
todo edit 7 --deadline 2026-05-15        # set or change deadline
todo edit 7 --deadline none              # remove deadline
```

### CLI Output Style

Default output is a compact table for humans, with a `--json` flag for programmatic use:

```
$ todo list

 #   Pri      Status       Title                          Deadline       Age
 3   !! URG   in-progress  Fix auth token expiry          ⚠ Apr 25 (1d)   2d
 1   !  HIGH  todo         Deploy new auth service          May 01         5d
 5      MED   todo         Write migration tests                           1d
 9      LOW   backlog      Investigate flaky CI job                        3h

4 items

⚠ = deadline within 3 days   🔴 = overdue
```

```
$ todo summary --since "7 days"

── Done (Apr 17 → Apr 24) ───────────────────────────────
 #   Pri      Done        Title
 2   !  HIGH  Apr 22      Set up staging environment
 4      MED   Apr 20      Add rate limiting to /api/login
 6      MED   Apr 18      Update README with deploy steps

3 items completed
```

---

## TUI (Interactive Terminal UI)

Built with Python `textual` for a rich, keyboard-driven experience.

Launch with: `todo ui`

### Main View — List + Detail

```
┌─ Todo ──────────────────────────────────────────────────────────────┐
│ Filter: All ▾    Priority: All ▾    Search: _                      │
├────────────────────────────────────────────────────────────────────-┤
│                                                                     │
│  ▸ #3  !! URG   ● In Progress  Fix auth token expiry        2d     │
│    #1  !  HIGH  ○ Todo         Deploy new auth service       5d     │
│    #5     MED   ○ Todo         Write migration tests         1d     │
│    #8     MED   ○ Backlog      Refactor user model           1w     │
│    #9     LOW   ○ Backlog      Investigate flaky CI job      3h     │
│  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ done ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─   │
│    #2  !  HIGH  ✓ Done         Set up staging environment    5d     │
│    #4     MED   ✓ Done         Add rate limiting             4d     │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ #3  Fix auth token expiry                                           │
│ Priority: Urgent  Status: In Progress  Deadline: ⚠ Apr 25 (1d)     │
│ Created: Apr 22, 2025 14:30   Updated: Apr 23, 2025 09:12          │
│ Tags: auth, hotfix                                                  │
│                                                                     │
│ The JWT refresh token logic doesn't account for clock skew          │
│ between services. Need to add a 30s grace window.                   │
├─────────────────────────────────────────────────────────────────────┤
│ [d]one  [e]dit  [n]ew  [/]search  [←→]status  [↑↓]navigate   [q]uit│
└─────────────────────────────────────────────────────────────────────┘
```

### Key Bindings

| Key           | Action                                       |
|---------------|----------------------------------------------|
| `↑` / `k`     | Move selection up                            |
| `↓` / `j`     | Move selection down                          |
| `→` / `l`     | Move item to next status (backlog→todo→…)    |
| `←` / `h`     | Move item to previous status                 |
| `d`           | Mark item as done                             |
| `x`           | Delete item (with confirmation)               |
| `n`           | New item (opens inline form)                  |
| `e` / `Enter` | Edit in `$EDITOR` (structured temp file)      |
| `/`           | Focus search filter                           |
| `1-4`         | Filter by priority (1=urgent … 4=low)         |
| `0`           | Clear filters                                 |
| `q` / `Esc`   | Quit                                          |

### Priority Color Coding

| Priority | Color   | Indicator |
|----------|---------|-----------|
| Urgent   | Red     | `!!`      |
| High     | Orange  | `!`       |
| Medium   | Default | (none)    |
| Low      | Dim     | (none)    |

### Status Indicators

| Status      | Symbol |
|-------------|--------|
| Backlog     | `○`    |
| Todo        | `○`    |
| In Progress | `●`    |
| Done        | `✓`    |

Blocked items (any not-done blocker) are prefixed with `🚧` in both the CLI
list and the TUI table. The detail pane and `todo show` display the full
`Blocked by:` / `Blocking:` id lists. In the TUI, `b` opens a dialog to add a
blocker to the selected item by id.

---

## Deadline Warnings

Deadlines are optional. When set, items are visually flagged based on proximity:

| Condition               | Indicator | CLI behavior                                  |
|-------------------------|-----------|-----------------------------------------------|
| Overdue                 | `🔴`      | Red highlight, sorted to top                  |
| Due within 3 days       | `⚠`       | Yellow/orange highlight                       |
| Due later               | (date)    | Shown normally                                |
| No deadline             | (blank)   | No indicator                                  |

- `todo list` shows deadline warnings inline (see CLI output example above)
- `todo ui` highlights rows with approaching/overdue deadlines in the TUI
- Deadlines use date-only granularity (no time component) — the item is overdue at the start of the day after the deadline

---

## AI Integration

AI agents interact exclusively through the CLI. No special protocol needed — the commands are designed to be self-explanatory and produce parseable output.

Typical AI workflow:
```bash
# AI adds a todo while working
todo add "Refactor auth middleware — extracted from monolith" --priority high --tag refactor --deadline 2026-05-01

# AI checks what's on the list
todo list --json

# AI marks work as done
todo done 12

# User asks "what did we get done this week?"
todo summary --since "7 days"
```

The `--json` flag on `list`, `show`, and `summary` outputs structured JSON for reliable parsing.

---

## Tech Stack

| Component   | Technology                   |
|-------------|------------------------------|
| Language    | Python 3.10+                 |
| Build       | hatchling                    |
| Database    | SQLite via `sqlite3`         |
| CLI         | `click`                      |
| TUI         | `textual`                    |
| Output      | `rich` (TTY) / plain (pipes) |
| Linting     | `ruff`, strict `mypy`        |
| Testing     | `pytest`                     |
| Task runner | `just`                       |

### Why Python + Textual

- `textual` produces polished terminal UIs with minimal code (CSS-like styling, reactive data binding, built-in widgets for tables/trees/inputs)
- `click` is the gold standard for Python CLIs
- SQLite is in Python's stdlib — zero external database dependencies
- Easy to install: `pip install` or `pipx install`

---

## Project Structure

Hexagonal / ports-and-adapters layout, matching choochoo conventions:

```
todo/
├── pyproject.toml
├── justfile
├── src/
│   └── todo/
│       ├── __init__.py
│       ├── domain/                # pure models, no dependencies
│       │   ├── __init__.py
│       │   ├── models.py          # frozen dataclasses: TodoItem
│       │   └── enums.py           # Priority, Status enums
│       ├── application/           # business logic
│       │   ├── __init__.py
│       │   ├── contracts/         # @runtime_checkable Protocols
│       │   │   ├── __init__.py
│       │   │   └── storage.py     # StorageProtocol
│       │   ├── queries.py         # list, show, summary logic
│       │   └── commands.py        # add, edit, mv, done, rm logic
│       ├── adapters/              # external integrations
│       │   ├── __init__.py
│       │   ├── sqlite_storage.py  # StorageProtocol → SQLite
│       │   └── output.py          # Rich TTY / plain formatters
│       ├── infra/
│       │   └── cli/               # click entry point, wiring
│       │       ├── __init__.py
│       │       └── main.py
│       ├── tui/                   # textual interactive UI
│       │   ├── __init__.py
│       │   ├── app.py
│       │   ├── list_view.py
│       │   └── styles.tcss
│       ├── config.py              # DB path resolution, env vars
│       └── exceptions.py          # TodoError hierarchy
└── tests/
```

---

## Out of Scope (for now)

- Multi-user / sync
- Subtasks / checklists
- MCP server (can be added later as a thin wrapper over the CLI)
- Web UI
