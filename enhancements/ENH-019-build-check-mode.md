# ENH-019 — `build.py --check` mode

Status: open · Category: quality of life / dev experience

**Why:** the build must be deterministic (AGENTS.md standing rule), and
agents keep verifying it by hand ("a second build changes nothing"). Make it
one command that ENH-033's `tasks.py check` can run.

## Build

- `python build.py --check` renders the whole site into a **temporary
  directory**, not `docs/`, using the same code path as a normal build, and
  compares it with the committed `docs/`, byte for byte.
- Exit 0 if identical. Otherwise exit 1 and list every differing, missing
  or extra file, one per line, with a short unified diff of the first few
  text differences.
- It must never write to `docs/`. It must handle the passphrase gate the
  way a normal build does: use `LEAGUE_PHRASE`, `LEAGUE_PHRASE_SHA256` or
  the digest already in `docs/index.html` (see `previous_gate_hash`), so a
  plain `--check` on a laptop without the phrase doesn't report every page
  as changed.
- It covers everything a normal build writes, including `static/` copies,
  the team pages, and `live-data.json`.

## Done when

- `--check` exits 0 on a clean `dev` checkout.
- It exits 1 and names the file after a one-character template edit (then
  revert).
- It exits 1 after a hand-deleted `docs/` file (then restore).
- `docs/` is untouched after all three runs (`git status` clean).
