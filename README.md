# todo

A persistent, SQLite-backed todo app for the terminal. Designed to be used by both humans and AI agents.

Two interfaces:

- **CLI** — scriptable commands for adding, updating, listing, and summarizing todos. Every command supports `--json` for programmatic use, making it trivial for AI agents (e.g. Claude Code) to manage tasks via Bash.
- **TUI** — an interactive terminal UI for browsing, filtering, and managing todos with keyboard shortcuts.

## Features

- **Four statuses**: backlog, todo, in-progress, done
- **Four priorities**: urgent, high, medium, low (color-coded)
- **Deadlines**: optional due dates with visual warnings (overdue, due soon)
- **Tags**: categorize and filter items (AND-combine filters, usage counts)
- **Blockers**: items can block each other; blocked items are marked 🚧 and
  cycles are rejected; completing a blocker tells you what got unblocked
- **Projects**: first-class containers with description, archive lifecycle,
  and per-project progress
- **Search**: match text in titles and bodies from CLI and TUI
- **Timestamps**: tracks when items are created, updated, and completed
- **Summary reports**: see what was completed in any time window
- **$EDITOR integration**: edit items in your preferred editor from the TUI

## Installation

Requires Python 3.10+.

```bash
just install
```

This installs the `todo` command globally in an isolated environment (via `uv tool install`).

## Quick start

```bash
# Add some items
todo add "Fix auth token expiry" --priority urgent --deadline 2025-05-01 --tag auth
todo add "Write migration tests" --priority medium
todo add "Investigate flaky CI" --priority low --status backlog

# See what's on the list
todo list

# Work on something
todo mv 1 in-progress

# Finish it
todo done 1

# What did we get done this week?
todo summary --since "7 days"

# Launch the interactive UI
todo ui
```

## CLI reference

```
todo add TITLE [options]          Add a new item
todo list [options]               List items (excludes done by default)
todo show ID [--json]             Show full detail for an item
todo edit ID [options]            Edit an item's fields
todo mv ID STATUS [--json]        Move an item to a new status
todo done ID [--json]             Mark an item as done
todo rm ID                        Delete an item
todo block ID BLOCKER...          Mark an item as blocked by other item(s)
todo unblock ID BLOCKER...        Remove blocker(s) from an item
todo tags [--json]                List all tags with usage counts
todo project add NAME             Create a project (-D for description)
todo project list [--all]         List projects with open/done counts
todo project show REF             Show a project and its items
todo project edit REF             Rename / change description
todo project archive REF          Archive (hide from default list)
todo project rm REF               Delete; items survive unassigned
todo summary --since PERIOD       Show completed items in a time window
todo ui                           Launch the interactive TUI
```

Projects are referenced by name or id. Blocked items render with a 🚧 marker;
`todo list --blocked` shows only blocked items and `todo list --ready` shows
what's actionable right now (not done, not blocked).

### Common options

| Option | Short | Description |
|--------|-------|-------------|
| `--priority` | `-p` | `urgent`, `high`, `medium`, `low` |
| `--status` | `-s` | `backlog`, `todo`, `in-progress`, `done` |
| `--deadline` | `-d` | Due date as `YYYY-MM-DD`, or `none` to clear |
| `--tag` | `-t` | Tag (repeatable; on `list`, multiple tags AND together) |
| `--body` | `-b` | Longer description text |
| `--project` | | Project name or id (`none` clears on `edit`) |
| `--search` | | Match text in title or body (`list`) |
| `--blocked` / `--ready` | | Only blocked / only actionable items (`list`) |
| `--json` | | Output as JSON |
| `--all` | | Include done items in list |

### Summary periods

The `--since` flag accepts relative durations or absolute dates:

```bash
todo summary --since "7 days"
todo summary --since "2 weeks"
todo summary --since "1 month"
todo summary --since "2025-04-01"
```

### Deadline warnings

Items with deadlines show visual indicators:

| Condition | Indicator |
|-----------|-----------|
| Overdue | `🔴` red highlight, sorted to top |
| Due within 3 days | `⚠` yellow highlight |
| Due later | Date shown normally |

## TUI key bindings

Launch with `todo ui`. A footer at the bottom shows the available keys.

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate rows |
| `>` | Advance status (backlog → todo → in-progress → done) |
| `<` | Move status back |
| `d` | Mark as done |
| `i` | Inspect (full read-only view, scrollable body) |
| `e` / `Enter` | Edit in `$EDITOR` |
| `n` | New item |
| `x` / `Delete` | Delete (with confirmation) |
| `b` | Add blocker by id (`-id` removes) |
| `/` | Search |
| `t` | Cycle tag filter |
| `p` | Cycle project filter |
| `1`-`4` | Filter by priority (same key toggles off) |
| `0` | Clear all filters |
| `.` | Toggle cursor mode: follow moved item (default) or stay on row |
| `Esc` | Clear active search |
| `q` | Quit |

The `.` cursor mode is for cleanup sessions: in "stay" mode the cursor keeps
its visual row when an item moves, so pressing `d` repeatedly marks a list
done top-down without re-navigating.

## AI integration

AI agents interact through the CLI. The commands are designed to be self-explanatory and every read command supports `--json` for structured output.

```bash
# AI adds a todo while working
todo add "Refactor auth middleware" --priority high --tag refactor --deadline 2025-05-01

# AI checks the list
todo list --json

# AI marks work as done
todo done 12

# User asks "what did we get done this week?"
todo summary --since "7 days"
```

## Configuration

The database is stored at `~/.todo/todos.db` by default. Override with the `TODO_DB` environment variable:

```bash
export TODO_DB=/path/to/custom.db
```

## Development

### Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv)
- [just](https://github.com/casey/just) (task runner)

### Setup

```bash
uv sync   # installs the package plus the dev dependency group
```

### Commands

```bash
just test       # run tests
just lint       # ruff + mypy
just fmt        # auto-format
just cov        # test coverage report
```

### Project structure

Hexagonal / ports-and-adapters architecture:

```
src/todo/
├── domain/              # Pure models, no dependencies
│   ├── models.py        #   TodoItem, Project (frozen dataclasses)
│   └── enums.py         #   Priority, Status, ProjectStatus
├── application/         # Business logic
│   ├── contracts/       #   StorageProtocol (interface)
│   ├── commands.py      #   add, edit, mv, done, rm, block, project ops
│   └── queries.py       #   list, show, summary, tags, projects
├── adapters/            # External integrations
│   ├── sqlite_storage.py#   StorageProtocol → SQLite (+ migrations)
│   └── output.py        #   Rich (TTY) / plain (pipe) formatters
├── infra/cli/           # Click entry point, wiring
├── tui/                 # Textual interactive UI
├── config.py            # DB path resolution
└── exceptions.py        # TodoError hierarchy
```

The layer rules are enforced by `tests/test_architecture.py`, which walks the
import graph and fails on violations. Schema changes ship as in-place
`PRAGMA user_version` migrations — existing databases upgrade automatically
on first open.

### Tech stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.10+ |
| Build | hatchling |
| Database | SQLite (stdlib) |
| CLI | click |
| TUI | textual |
| Output | rich (TTY) / plain (pipes) |
| Linting | ruff, strict mypy |
| Testing | pytest |
| Task runner | just |

## License

[MIT](LICENSE)
