# NOTES: what README.md and IDEAS.md need after this branch

Written instead of editing README.md / IDEAS.md directly, per instructions
(multiple agents working in parallel on those files). This lists every
sentence that is now stale, quoting the exact old text and the exact proposed
new text, so whoever reconciles the docs can apply these as literal edits.

Everything below assumes this branch's implementation: `corpuslens run` with
no arguments (`corpuslens/cli.py::run_discovered` and `_discover_corpora`),
and the per-adapter discovery seam (`ingest.register_default_path` /
`default_path_of` / `discoverable`), declared for `claude-code`
(`~/.claude/projects`), `cursor-store` (`~/.cursor/chats`) and `gemini-cli`
(`~/.gemini/tmp`) — not for `cursor`, which has no fixed on-disk home to
guess at.

---

## 1. IDEAS.md — mark "Zero-config first run" built

**File:** `IDEAS.md`, the "### Zero-config first run" entry under "Near".

**Old text (the whole entry):**

```
### Zero-config first run

`corpuslens run` currently demands both an adapter and a path. The first run is
the adoption moment, and it asks the user to know two things they may not.

`corpuslens run` with no arguments could look in `~/.claude/projects` and
`~/.cursor/chats`, report what it found, and run what it can. `ccusage`
(MIT, actively maintained) already solved "find the user's agent logs across
CLIs and versions" and is worth reading before writing this from scratch.
```

**New text:**

```
### Zero-config first run

*2026-09-11: built.* `corpuslens run` with no PATH and no `--adapter` now
looks in every "dir" adapter's declared conventional location —
`~/.claude/projects` (claude-code), `~/.cursor/chats` (cursor-store),
`~/.gemini/tmp` (gemini-cli) — reports what it found at EACH one (present or
not, how many candidate files, unreadable, or refused) before reading a
single turn, then runs the battery on what it found. `cursor` has no fixed
on-disk home and is not offered.

Discovery is declared PER ADAPTER, not hardcoded in the CLI:
`ingest.register_default_path(name, path)` is a third small registry next to
`register()` and `register_label_text()` — a new directory adapter says
where it conventionally lives right next to its own `ingest()` function, and
`corpuslens run`'s discovery loop (`ingest.discoverable()`) needs no edit to
pick it up.

Two things kept it from being a plain convenience wrapper around the
explicit form. First, containment: a declared path is checked against the
CLI's actual `$HOME` at run time (never at import time) and refused — not
followed — if it resolves outside it (a symlinked `~/.claude/projects`
pointing elsewhere, or a future adapter that misdeclares its own
convention), and file counting never follows a symlinked directory or counts
a symlinked file. An unreadable location is reported in the same per-adapter
line, never a traceback. Second, the multiple-corpora question the original
entry left open: when more than one location is usable, this runs the
LARGEST by file count and says so in the same output, rather than running
each in turn or refusing and asking — `run` renders one report, and a
non-interactive first run has no one to ask. Any of the three is defensible;
see `cli.py::run_discovered`'s docstring for why this one was chosen.

The honesty question this raised: is naming the ADAPTER enough, or does the
report also need to name the PATH it guessed? Decided the latter. Every run's
audit sentence already names the adapter (`guard.AuditRecord.sentence()`),
but that sentence is written assuming the user typed the path themselves —
true for every run before this feature. A discovered run breaks that
assumption: the tool chose the path, not the user, so a reader of the saved
report ALONE (not this run's terminal transcript — `--out` may have written
the report elsewhere, and the discovery preamble does not go into that file)
has no other way to learn what was actually read. `AuditRecord` grew one new
field, `discovered_path` (`None` on every explicit-path run, which is why the
sentence and JSON shape are byte-identical to before for every run that
existed prior to this feature), and the sentence gets one prepended clause
naming both the adapter and the resolved path when it is set. `--share`
strips it in `share.coarsen_audit()` — a home directory path can carry the
owner's username, which is exactly the class of machine-identifying detail
share mode exists to omit from an output meant to leave the machine.

`ccusage`'s approach was read as background per the original entry's
pointer, not ported: its multi-tool detection logic solves a broader problem
(several CLIs' worth of format-sniffing) than this feature needed, given
that this project's adapters already each know their own file pattern and
directory shape.
```

---

## 2. README.md — add zero-config to the Quickstart

**File:** `README.md`, "## Quickstart" section (right after the code fence
that currently opens with `corpuslens run ~/.claude/projects --adapter
claude-code --out report.md`).

**Old text:**

```
## Quickstart

```bash
corpuslens run ~/.claude/projects --adapter claude-code --out report.md
corpuslens run ./my-cursor-sessions --adapter cursor
corpuslens run ~/.cursor/chats --adapter cursor-store  # Cursor's own store.db tree
corpuslens run ./corpus.db --adapter sqlite            # a SQLite corpus (a file)
corpuslens run "dbname=mycorpus" --adapter postgres    # a Postgres corpus (a DSN)
# equivalently, from a clone without installing:
python3 -m corpuslens run ~/.claude/projects --adapter claude-code
```
```

**New text:**

```
## Quickstart

The fastest first run needs neither argument — point it at nothing and it
looks for you:

```bash
corpuslens run
```

That checks the conventional locations (`~/.claude/projects`,
`~/.cursor/chats`, `~/.gemini/tmp`), reports what it found at each one
*before reading anything*, and runs the battery on the largest corpus it
found — see "Zero-config discovery" below for exactly what that means and
does not mean. To point it at a corpus yourself instead:

```bash
corpuslens run ~/.claude/projects --adapter claude-code --out report.md
corpuslens run ./my-cursor-sessions --adapter cursor
corpuslens run ~/.cursor/chats --adapter cursor-store  # Cursor's own store.db tree
corpuslens run ./corpus.db --adapter sqlite            # a SQLite corpus (a file)
corpuslens run "dbname=mycorpus" --adapter postgres    # a Postgres corpus (a DSN)
# equivalently, from a clone without installing:
python3 -m corpuslens run ~/.claude/projects --adapter claude-code
```
```

---

## 3. README.md — new subsection documenting the behavior

**File:** `README.md`, insert immediately after the paragraph ending "Point
`--adapter claude-code` at a directory of Claude Code session `.jsonl`
files, or `--adapter cursor` at a directory of Cursor session `.jsonl`
files." (line 106) and before the "**Two things the claude-code adapter
deliberately does not count as you**" paragraph — a natural break, and close
to where `--adapter` is first explained.

**New text to insert (addition, no old text replaced):**

```
### Zero-config discovery

`corpuslens run` with no PATH and no `--adapter` (give both together, or
neither — giving only one is an error) looks in the conventional location
each directory-reading adapter has declared for itself: `~/.claude/projects`
(claude-code), `~/.cursor/chats` (cursor-store), `~/.gemini/tmp`
(gemini-cli). It reports every location it checked — found or not, how many
candidate files, or why not (not present, unreadable, not a directory,
resolves outside your home directory) — before reading a single turn, then
runs the battery on what it found.

**If more than one corpus exists, it runs the largest by file count** and
says so, naming the corpus it skipped too. Run corpuslens explicitly against
a path to analyze a different one instead — the auto-picked run always tells
you the exact command's shape to do that.

**If nothing is found**, it says exactly which paths it checked and why each
one came up empty, and points at the explicit two-argument form — never a
traceback, and never a guess dressed up as an answer.

Because the tool chose the path here instead of you typing it, the report
itself — not just this run's terminal output — names both the adapter and
the exact path it read, right in the audit sentence at the top: "No path or
--adapter was given: corpuslens discovered this corpus itself at
`/home/you/.claude/projects`, using the 'claude-code' adapter." `--share`
removes that path (a home directory can carry your username) along with
everything else share mode omits.

Discovery never widens outside your home directory and never follows a
symlink out of it — a conventional location that turns out to be a symlink
elsewhere is refused, not read.
```

---

## 4. README.md — mention it in the "Built" line

**File:** `README.md`, "Status: spine" section.

**Old text:**

```
Built: event model, the wall, five adapters (claude-code, cursor, cursor-store,
sqlite, postgres), injection filter, six analyzers, markdown + JSON renderers,
CLI (`run`, `doctor`, `adapters`, `analyzers`), test suite (wall + pipeline +
db-adapter + CLI-surface + render + regression tests for every review finding).
```

**New text (adjust to whatever the adapter/analyzer counts have grown to by
merge time on other in-flight branches — the load-bearing addition is the
"zero-config discovery" clause):**

```
Built: event model, the wall, adapters (claude-code, cursor, cursor-store,
gemini-cli, sqlite, postgres), injection filter, analyzers, markdown + JSON
renderers, zero-config discovery on `run` (per-adapter declared, largest
corpus wins, never a traceback), CLI (`run`, `doctor`, `adapters`,
`analyzers`), test suite (wall + pipeline + db-adapter + CLI-surface + render
+ zero-config + regression tests for every review finding).
```

Note: this repo has several branches in flight adding adapters/analyzers of
its own (gemini-cli, corpus-refusal, labelling, ...) — whoever merges last
should reconcile this line against what actually landed rather than taking
either branch's wording verbatim.

---

## Judgment calls, for a future reader to weigh

- **Path lives on `AuditRecord`, not just printed to the terminal.** The
  alternative — printing the chosen adapter+path only as CLI preamble before
  the report — was rejected because a saved `--out` report would then carry
  only the adapter name, and "a reader of the report alone can tell what was
  read" was the explicit bar. The cost: `AuditRecord` (and therefore the
  JSON schema's `audit` object) gained one field. It defaults to `None` and
  is invisible in the sentence when unset, so every run made before this
  feature — and every explicit-path run after it — is unaffected byte for
  byte; only `--format json` output gains one new (usually-null) key.
- **"Largest corpus wins" over "run each" or "ask".** `run` is a
  single-report command; multiplexing several reports out of one invocation
  would need a rendering shape nothing here has, and asking has no answer in
  a piped or scripted first run. Named as a judgment call in
  `run_discovered`'s own docstring, not hidden as an unexamined default.
- **`cursor` is not discoverable.** It reads a directory of Cursor session
  `.jsonl` files the user names themselves (`./my-cursor-sessions` in the
  Quickstart) — there is no OS-level convention for where that lives, unlike
  `cursor-store`'s actual on-disk store. Declaring a fake convention for it
  would be a guess the tool cannot honestly stand behind.
- **Discovery counts files without reading them.** The per-adapter report's
  file counts come from the same "walk and count a pattern" logic
  `_check_path` already uses for the explicit form, not from a preview
  ingest — so "3 files found" is a promise about what will be attempted, not
  about how many will parse. A corpus that counts high and yields nothing
  still gets picked (if it is the largest) and then reports its own honest
  "none yielded a datable, non-empty turn" failure, same as the explicit
  form always has.
