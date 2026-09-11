# Changelog

All notable changes to corpuslens are recorded here. This project keeps to the
spirit of [Keep a Changelog](https://keepachangelog.com) and dated, in-the-open
amendments — corrections sit beside the record they correct, never overwrite it.

Versioned sections are written by release-please from the commit messages; the
hand-written history below them predates the release pipeline.

## [0.1.0](https://github.com/willow-memory/corpus-lens/compare/v1.0.0...v0.1.0) (2026-09-11)


### Fixed

* cut 0.1.0, not 1.0.0 ([515ca9f](https://github.com/willow-memory/corpus-lens/commit/515ca9f6294e97e75a21c6c062e2abfee3656969))

## Corrected: there is no 1.0.0

release-please cut `1.0.0` on 2026-09-11 and it was published to PyPI, then
withdrawn — the PyPI project was deleted and re-created, so **no 1.0.0 exists**
on PyPI, and the version is not coming back.

Two things went wrong, recorded here rather than quietly rewritten:

- **The number was wrong.** With no prior release, release-please's first
  release defaults to `1.0.0` regardless of the manifest starting at `0.0.0`.
  The comments in `pyproject.toml` and `release-please-config.json` asserted it
  would propose `0.1.0`; that assertion was never tested and was false. For a
  project whose one rule is never to overclaim, shipping a `1.0.0` compatibility
  promise on a spine was the largest overclaim in the repository.
- **The changelog section carried duplicates**, one entry per change from both
  the real commit and the merge commit that carried its title. That is exactly
  what `tools/changelog_dedup.py` exists to prevent, and it no-ops on a *first*
  release: its section matcher expects the `## [x.y.z](…/compare/…)` heading
  release-please writes for every release *after* the first, and a first release
  has no previous tag to compare against. Recorded as a known gap.

This release cuts `0.1.0` instead, forced with a `Release-As: 0.1.0` footer —
release-please's own mechanism, so the pipeline still cuts the release.

## Unreleased — the spine (hand-written)

Everything below this line was written by hand, before the repository had a
release pipeline. From the first release onward this file is maintained by
release-please (`release-please-config.json`), which prepends a dated section
per version above this one — so this section keeps its own heading rather than
claiming a version number that was never tagged or published.

First cut: the wall, five adapters, six analyzers, hardened across four rounds
of adversarial review.

### Added
- **JSON output** (`run --format json`): the same run as
  `{schema_version, audit, results, caveat}`, for diffing two runs or tracking a
  number over months. The audit record travels as structured fields **and** as
  the plain-language sentence — a machine-readable result must not be a way to
  get the numbers without the statement of what left the wall. It goes through
  the same fail-closed `scan_egress` backstop as markdown; a test holds that a
  leaking analyzer is refused in JSON exactly as it is in markdown.
- **`doctor`**: a dry run of ingestion — records read, events kept, drop share,
  operator/machine split, threads, relative-day span, tempo-delta coverage, and
  notes naming which analyzers this corpus *cannot* feed. Runs no analyzer,
  emits no rate, reports counts and never content, and passes the same egress
  scan: a diagnostic is an output door too, not the quieter way out.
- **`adapters` / `analyzers`**: what can be read (each with the argument kind it
  expects) and what gets computed (each with its claim type and its named
  denominator).
- **Relative-day window** (`run --since-day N --until-day N`): analyze a slice.
  Day 0 stays the corpus's first event — the window never re-bases it, so "day
  0" means the same thing across two runs. A filtered run names the window in
  its audit sentence and counts the events the window excluded, in the words
  "subset numbers, not corpus numbers".
- **`tempo` analyzer** (claim `tempo`): gaps between operator prompts, within a
  thread and within a day — median, quartiles, and the share of gaps under a
  minute (volleys) or over half an hour (you left and came back). It states the
  share of eligible turns it has **no** delta for instead of imputing one: a
  turn that opens a thread, follows a censored midnight crossing, or comes from
  a store that doesn't clock prompts (`cursor-store`) is counted as uncovered.
  On a corpus with no deltas at all it returns an error naming why, never a rate
  over an invented sample. It publishes no *cumulative* within-day span — the
  README discloses that a long span loosely bounds the local clock hour, and
  percentiles over individual gaps do not sharpen that bound while a published
  span would. A test holds that omission.
- **`thread_span` analyzer** (claim `thread_shape`): the span a thread stays
  open in, its active days, and the density of the two — the complement to
  `thread_shape`, which counts the resumption gaps *inside* that span.
- **Per-adapter source pattern** in the ingest registry (`register(...,
  pattern=)`). `cursor-store` walks `store.db`, not `*.jsonl`, so "no *.jsonl
  files found under X" was the wrong thing to say about it. The CLI now counts
  and names the pattern the adapter actually walks.

- **Cursor `store.db` adapter** (`ingest/cursor_store.py`, `--adapter
  cursor-store`): reads the chat store Cursor keeps for itself — a tree of
  `store.db` SQLite files under `~/.cursor/chats`, one per thread. The format
  is undocumented, so it is read from the bytes: a `blobs` heap where a blob
  beginning `{` is the conversation as plain JSON (`role`/`content`) and every
  other blob is protobuf, walked on the wire format alone (stdlib only, no
  schema, no dependency) to recover the tool-step clocks in fields 59/60. The
  thread anchor comes from the sibling `meta.json`'s `createdAtMs`. On the
  corpus this was written for it read 266 threads and 3,734 turns that the
  `cursor` adapter could not see at all.

  **It gives operator turns no `delta_prev_s`, on purpose.** The store
  timestamps tool steps, not prompts; a prompt is dated by the last logged
  moment at or before it, and its tempo is `None`. Interpolating a plausible
  clock would invent exactly the quantity the wall governs, and a fabricated
  tempo is indistinguishable from a measured one downstream. Databases open
  `mode=ro`; a malformed, encrypted, or anchorless blob is counted, never
  hidden. `meta.json`'s `title` and `cwd` are read and deliberately never
  emitted.

### Fixed
- **The injection filter missed most of what Cursor injects**, and the
  front-loading finding it was built for was still in the numbers: on the
  `store.db` corpus the median "opener" was **3617 words**. `<user_info>` was
  the only Cursor wrapper it knew. Now it also strips
  `always_applied_workspace_rule(s)`, `agent_transcripts`, `git_status`,
  `rules`, `user_rule`, `agent_skill(s)`, `summary_content`, `hooks_context`,
  `system_notification`, `system_reminder`, `mcp_instructions`,
  `mcp_meta_tool(s|_servers)`, `dynamic_tool(s|_catalog|_namespaces)`,
  `available_subagent_(types|models)`, `mermaid_syntax` and `todo_update` —
  **including tags carrying attributes** (`<mcp_instructions description="…">`
  matched nothing before, which alone left 277 turns with a four-figure word
  count), and including a block left unclosed by a context boundary.

  Three injections are not tags at all: a runtime that compacts a conversation
  re-injects the summary **as a user turn**. `[Previous conversation summary]`,
  `Your conversation was summarized due to…`, `This session is being continued
  from a previous conversation` and a subagent-result preamble are now
  recognised as whole-turn machine text and carry no authored words. The
  patterns are anchored at the start of the turn, so a human quoting one of
  those phrases mid-message is untouched.

  Median opener on the store corpus: **3617 → 12 words**; turns still over 300
  words after stripping: **438 → 0**. The `claude-code` adapter shares this
  filter; measured on a frozen snapshot, its opener median is unchanged and it
  correctly drops 7 compaction summaries it had been counting as prompts.

- **Database adapters** (`ingest/sqlite.py`, `ingest/postgres.py`): read a
  corpus from a **SQLite `.db` file** or a **Postgres connection string** instead
  of a directory of session files. Both resolve the turns table's timestamp /
  role / content / session columns by alias (case-insensitive), auto-detect the
  table when one obvious candidate exists (else `--table`), and honor the wall
  identically to the file adapters — the row→`Event` logic is factored into
  `ingest/_rows.py::assemble` so a DB backend cannot re-derive and weaken it.
  Relative day offsets only, cross-midnight deltas censored, calendar anchor
  quarantined, `table:row` locators hashed (a db path / DSN never reaches an
  `Event`), and every unusable row dropped-and-counted. SQLite opens read-only;
  Postgres issues only `SELECT` / `COPY (SELECT …)`. **Still zero Python
  dependencies**: SQLite via stdlib `sqlite3`, Postgres by shelling to the
  `psql` client binary (its one system requirement) rather than importing a
  driver. The CLI now takes a source-kind per adapter (`dir` / `file` / `dsn`,
  via `register(..., source=)`) so a file or DSN is not rejected as "not a
  directory", plus a `--table` flag and a new honest `Surface.DB`. Covered by
  `tests/test_db_adapters.py` (wall parity, drop-counting, cross-midnight
  censoring, alias resolution, CSV-embedded-newline handling, CLI end-to-end;
  the Postgres tests run against a live cluster and skip cleanly without one).
- **The inference wall** (`guard.py`, `model.py`): `Event`s carry relative time
  only (day offsets + within-day deltas, cross-midnight deltas censored); the
  calendar anchor, timezone, and real filenames are quarantined and released
  only through a fail-closed `Guard` (capability + owner token + logged
  justification). Analyzers declare claim types against a process-only
  allowlist. Every run emits a plain-language audit sentence naming exactly what
  left the wall — and disclosing what it does not hide (weekly cadence; a loose
  within-day time-of-day bound).
- **Adapters**: `claude-code` and `cursor` session JSONL, injection-filtered,
  dates from log fields only, filenames hashed to opaque ids, every dropped line
  counted, malformed-line and unreadable-file isolation, BOM-safe, timezone-
  reproducible.
- **Analyzers**: `steering_density`, `thread_shape`, `composition_mix`,
  `clarification_pull` — each with a named denominator and reference points from
  a measured N=1 plus public population aggregates.
- **CLI** (`corpuslens run … --adapter …`), markdown report, an annotated
  reproducible [example](examples/EXAMPLE.md), and a test suite whose wall tests
  double as the acceptance tests for the centerpiece.
- **Egress backstop** (`Guard.scan_egress`, wired at the CLI output door): a
  defense-in-depth re-check of the rendered report right before it leaves. The
  wall keeps the anchor out of `Event`s upstream; this catches the accidental
  leak that upstream guarantee is supposed to prevent — if a quarantined value
  (calendar anchor, timezone, or a real filename) whose capability was not
  released this run appears verbatim in the report, the emit is refused
  (fail-closed, exit code 3) and the report is discarded. Grant-aware (a value
  released under an owner grant is allowed to appear) and payload-free (the
  error never echoes the value it caught). Hostile fixtures in `test_wall.py`
  and an end-to-end leaking-analyzer test in `test_pipeline.py`.

### Deliberately not built (named, not hidden)
- Any content-derived token feature (`distinctive_tokens`) — absent until a
  feature-layer PII scrub exists.
- The guardian-consent model (owner ≠ subject) — out of scope by design.
- Bootstrap CIs, web-export / agent-fleet adapters, JSON/prose renderers.
