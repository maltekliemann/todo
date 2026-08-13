# WORK

Round 4, opened 2026-08-13. The domain layer holds the domain rules.

## done

1. **One file per model.** `enums.py` and `models.py` are gone — they
   sorted by Python data type (all the Enums here, all the dataclasses
   there), which says how a thing is built and not what it is.

   ```
   domain/  title.py  tag.py  deadline.py  priority.py  status.py
            project_status.py  todo_item.py  project.py
            project_update.py  dependency_graph.py  text.py
   ```

2. **`DependencyGraph`** — the aggregate. An edge belongs to neither item
   it joins, and the rule that admits it (acyclic) ranges over the whole
   set, so the graph is the consistency boundary. `with_edge` returns a
   valid graph or raises; construction validates too, which is what
   catches a set written by something that went around the type.
   `_assert_no_cycle` is gone from `commands.py`.

3. **`Title`, `Tag`, `Deadline`** — `str`/`date` subclasses that validate
   on construction, so an invalid one cannot exist and therefore cannot
   be stored. `_normalize_title` and `_normalize_tags` are gone.
   `StorageProtocol.add`/`update` now say `Title`, `list[Tag]`,
   `Deadline`, so a raw string cannot reach storage.

4. **`Deadline` owns "has it passed"; `TodoItem` owns "is it overdue"** —
   the date knows about itself, and only the item knows whether that
   still matters.

## what moved and what didn't

- `is_blocked` is still computed in SQL (`sqlite_storage.py:279–286`).
  It's the same species of misplacement, and it needs the port to change
  shape. Not this round.
- The row-level `add_blocker`/`remove_blocker` port is unchanged, so the
  graph can still be bypassed — thirteen test call sites do exactly that.
  Deliberate: closing it costs the adapter plus those thirteen, and buys
  only that tests cannot lie. Production has one caller, `commands.py`.
- `'none' is a reserved tag name` stayed in `commands.py`. It is a fact
  about the CLI's clear-sentinel, not about a valid tag — and putting it
  in the type would make a legacy row unreadable.

## one rule I changed

`tests/test_architecture.py` said the domain may import stdlib and
`todo.domain` only. `DependencyGraph` needs `DependencyError`, so the
rule now allows `todo.exceptions` as well. A domain that enforces a rule
has to be able to say what it refused, and `exceptions.py` is a
dependency-free leaf, so this cannot invert the layering. Say if you'd
rather the graph raised something of its own instead.

## notes

- **`PRD.md` is stale from round 3** and I have not touched your spec: it
  still describes `i` as a read-only modal and `e` as the `$EDITOR`
  buffer with `title:`/`priority:` lines.

---

Round 3 (the item menu, `$EDITOR` reduced to the body, both ends of a
dependency editable) is `70fa827..5a34bdc`. Round 2 is
`fae5e2b..cb97d69`. Round 1 is `9edf848..3663d44`.
