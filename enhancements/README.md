# Enhancements

The backlog. There's one file per item, so an agent reads only the item it
was given, not the whole history.

- **`enhancements/ENH-NNN-<slug>.md`**: open items. Pick one by ID.
- **`enhancements/done/`**: shipped items, kept for reference. Don't read
  this folder unless a task points you there.
- **`enhancements/shelved/`**: items set aside because other work covered
  them or they can't work here. Each one ends with a "Why shelved" note.
  To revive one, `git mv` it back and set `Status: open`. Don't read this
  folder unless a task points you there.
- **`NOT-BUILDING.md`**: decisions not to re-litigate. It's short, so read it
  before proposing anything architectural.

## Working an item

1. Read the item's file. It is the spec. `AGENTS.md` has the working
   protocol.
2. Build it, verify it, and commit.
3. When it's done, `git mv` the file into `done/`, and change `Status: open`
   to `Status: done YYYY-MM-DD`. Add a short "Shipped" paragraph saying what
   was actually built and how it was verified. If anything in the spec
   didn't ship, say so and open a new item for it; don't claim it.

## Adding an item

Create `ENH-NNN-<short-slug>.md` with the next free ID. It's one higher than
the highest ID in any of the three folders, so check them all.

```
# ENH-NNN — Short title

Status: open · Category: <content & features | polish & UX | quality of life / dev experience | multi-league>

What and why, then the spec: what to build, the rules it must follow, what
"done" means and how to verify it.
```

Bugs live in `BUGS.md` at the repo root; that file is still small.
