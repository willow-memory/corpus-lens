# corpuslens

A local-first lens for your own human+agent corpus. Point it at your session
logs; get a process report — where your intent arrives, who writes the code,
whether you deliberate on purpose, what shape your threads have — with
reference points to grade yourself against.

**Stdlib only. Local only. Owner == subject.** Nothing to install beyond
Python, nothing leaves your machine, and this is for studying *yourself*.
Pointing it at another person (a child, a partner, an employee) is a different
consent object and is out of scope by design.

The rubric this instruments: [GRADING.md](GRADING.md)
(ten questions to grade your own system).

## The wall (what it guarantees, stated honestly)

The load-bearing design decision, inherited from the instrument's origin:
**relative time is process; the absolute anchor is person.** A custody
schedule was once reconstructed from keystroke timing alone — content
redaction does not scrub the shape of a week. So:

- Events carry **relative day offsets and deltas only**. The calendar anchor
  (which real date is day 0), the timezone, and the raw filenames (which embed
  dates and names) are quarantined at ingest and released only through the
  Guard with a granted capability + owner token + logged justification, fail-
  closed on every path.
- Analyzers declare **claim types** against a process-only allowlist.
  "He is [category]" has no representable claim type.
- Every run emits a **plain-language audit sentence** naming exactly what left
  the wall, and there is deliberately **no CLI flag to grant capabilities** —
  a grant is an owner-side code change.

**What this does — and does not — guarantee (read this).** The wall keeps the
*absolute anchor* out of the analysis: a real calendar **date**, a real
**weekday label**, and the **timezone** cannot be recovered without
re-supplying, through the Guard, the anchor you alone hold. What the wall does
**not** do:

- It does **not hide weekly cadence.** Relative day offsets preserve the shape
  of a week (`day_offset % 7` up to one unknown rotation) — that is inherent to
  computing resumption and concurrency at all, and we do not pretend otherwise.
  Mon-vs-weekend rhythm is visible; *which* real weekday is not.
- It does **not fully hide within-day time-of-day.** Cross-midnight deltas are
  censored, so the clock can't be pinned at a day boundary — but within-day
  tempo deltas survive (a tempo signal is the point), and their cumulative
  span loosely *bounds* the local time-of-day on a day one thread runs for many
  hours (a 21-hour span puts the first event before ~03:00 local). This is a
  weak local-clock **bound** — never the timezone, never the date. We disclose
  it rather than claim an absolute "no clock hour."
- It is **not an adversarial sandbox against you, the owner.** This is a local
  tool you run on your own logs to study yourself; you can always read your own
  quarantined data by editing your own script. The wall stops *accidental*
  leaks and constrains analyzer *plugins* — the supported path emits process
  only. Claiming it could stop its own owner would be the overclaim this
  project is built to forbid.

`tests/test_wall.py` holds the wall to exactly these claims — including a test
that asserts a plugin *cannot* recover the absolute anchor via the supported
path, and one that documents that weekly cadence *is* reconstructable.

## Install

Python 3.10+, no dependencies.

Not on PyPI yet, but the pipeline is wired: a merge to `main` opens a
release-please pull request, merging that cuts the tag, and the tag publishes
`corpuslens` to PyPI through Trusted Publishing (no token in the repo). Once the
first release lands, this becomes `pip install corpuslens` — or `uvx corpuslens`
/ `pipx install corpuslens`, which zero dependencies makes reliable. Until then,
from source:

```bash
git clone https://github.com/willow-memory/corpus-lens
cd corpus-lens
pip install .           # or: pip install -e .  (for development)
```

This installs a `corpuslens` console command. You can also run it without
installing, straight from a clone, via `python3 -m corpuslens`.

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

Point `--adapter claude-code` at a directory of Claude Code session `.jsonl`
files, or `--adapter cursor` at a directory of Cursor session `.jsonl` files.
`--adapter cursor-store` reads the chat store Cursor keeps for itself — a tree
of `store.db` SQLite files under `~/.cursor/chats`, one per thread. See
[Cursor's store.db](#cursor-storedb) for what that corpus can and cannot tell
you about time.
The report prints to stdout (or `--out FILE`), and always opens with a
plain-language audit line naming exactly what left the wall and how many input
records were dropped.

### The other subcommands

```bash
corpuslens doctor ~/.claude/projects --adapter claude-code   # what WOULD be read
corpuslens adapters                                          # what can be read
corpuslens analyzers                                         # what gets computed
```

`doctor` is a dry run of ingestion only: how many records an adapter could see,
how many it had to drop and what share that is, how many threads and relative
days it found, and — the useful part before you commit to a report — which
analyzers this corpus *cannot* feed (a corpus with no machine turns can't give
you `clarification_pull`; one with no prompt clock can't give you `tempo`). It
runs no analyzer and emits no rate, counts rather than content, and its output
passes the same fail-closed egress scan the report does. `adapters` and
`analyzers` list what is registered — each adapter with the argument it expects,
each analyzer with its claim type and its named denominator.

### JSON output, and analyzing a slice

```bash
corpuslens run ./corpus --adapter claude-code --format json
corpuslens run ./corpus --adapter claude-code --since-day 30 --until-day 60
```

`--format json` emits the same run as `{schema_version, audit, results,
caveat}` — for diffing two runs, tracking one number across months, or piping
somewhere else. The audit record comes along as structured fields **and** as the
plain-language sentence: a machine-readable result is not a way to get the
numbers without the statement of what left the wall.

`--since-day` / `--until-day` restrict the analysis to a **relative-day** window
(day 0 is the corpus's first event — never a calendar date, and the window never
re-bases it). A filtered run says so in its audit sentence, names the window, and
counts the events the window excluded: those are subset numbers, not corpus
numbers, and the report says that in words.

### Cursor's store.db

Cursor keeps each chat in its own directory holding a `store.db` and a
`meta.json`. There is no published schema, so the adapter reads the format from
the bytes: a `blobs` heap where a blob beginning `{` is the conversation as
plain JSON (`role` / `content`) and every other blob is protobuf, walked on the
wire format alone. Databases are opened `mode=ro` — pointing the lens at a live
Cursor cannot mutate it.

**What this corpus does not have: a clock on your turns.** The store timestamps
tool *steps*, not prompts. So a prompt is dated by the last logged moment at or
before it (the thread's `createdAtMs`, or the most recent tool step above it),
and its `delta_prev_s` is always `None`. Interpolating a plausible time would
be inventing exactly the quantity the wall exists to govern, and a fabricated
tempo is indistinguishable from a measured one downstream. `tempo` over this
corpus therefore describes the machine's step rate, never your typing rhythm.

Everything a blob cannot become — a tool or system message, an unparseable or
encrypted payload, a thread with no anchor — is counted in the audit line
rather than silently dropped.

### Database corpora (SQLite and Postgres)

If your turns live in a database rather than session files, point the `sqlite`
adapter at a `.db` **file** or the `postgres` adapter at a **connection string**
(a libpq URL, a `key=value` conninfo, or a bare dbname):

```bash
corpuslens run ./chat.db --adapter sqlite
corpuslens run ./chat.db --adapter sqlite --table messages   # if >1 table
corpuslens run "postgresql://localhost/mycorpus" --adapter postgres
```

Both read a **turns table** and resolve the four columns they need — timestamp,
role, content, and (optionally) a session/thread id — by alias, case-
insensitively, so a conventional schema needs no configuration (`ts`,
`timestamp`, `created_at`, …; `role`, `author`, `sender`, …; `content`, `text`,
`message`, `body`, …; `session_id`, `thread_id`, `conversation_id`, …). A
database with more than one table needs `--table` unless one obvious candidate
exists. A role the mapping doesn't recognize, an unparseable timestamp, or an
empty turn is **dropped and counted**, never guessed at.

The wall applies exactly as for the file adapters: relative day offsets only,
cross-midnight tempo deltas censored, the calendar anchor quarantined, and the
row locator (`table:row`) hashed before it reaches an event — a db path or DSN,
which can embed a username or home dir, never lands on an event. The SQLite
connection is opened **read-only**; the Postgres adapter issues only `SELECT` /
`COPY (SELECT …)`, so pointing the lens at a live store cannot mutate it.

**Zero Python dependencies, still.** SQLite uses the stdlib `sqlite3`. The
Postgres adapter shells out to the **`psql` client binary** (its one system
requirement) rather than importing a driver, so `pip install corpuslens` stays
dependency-free — install `psql` (e.g. `postgresql-client`) to use it.

The battery (v0): `steering_density`, `thread_shape`, `composition_mix`,
`clarification_pull`, `tempo`, `thread_span` — each with a named denominator,
dropped-event counts reported (never hidden), and reference points from one
measured N=1 operator corpus plus WildChat/OASST population aggregates.

`tempo` reports the gaps between your own prompts within a thread and within a
day, with the share of turns it has **no** gap for stated outright — a turn that
opens a thread, follows a censored midnight crossing, or comes from a store that
doesn't clock prompts is counted as uncovered, never imputed. It deliberately
publishes no *cumulative* within-day span: the loose local-clock bound disclosed
above is disclosed at its current strength, and no analyzer here sharpens it.
`thread_span` counts the span a thread stays open in and how densely it is worked
— the complement to `thread_shape`, which counts the resumption gaps inside it.

See [`examples/EXAMPLE.md`](examples/EXAMPLE.md) for a complete annotated run on
a small synthetic corpus you can reproduce byte-for-byte:

```bash
corpuslens run examples/sample-corpus --adapter claude-code
```

## Tests

```bash
python3 -m unittest discover -s tests
```

The suite covers the wall (fail-closed release, cross-midnight censoring, the
supported-path anchor-recovery attempt, the granted-profile audit sentence),
the adapters (drop-count accounting, malformed-line and unreadable-file
isolation, BOM, out-of-range dates, timezone reproducibility), the CLI surface
(the JSON renderer's shape and its egress scan, the window's subset disclosure,
`doctor`'s counts-not-content output, the listings), and a regression test for
every fixed review finding.

## Honesty about the numbers

The classifiers are regex heuristics: trust direction plus your own
spot-check, never raw percentages. The reference N=1 was verified by
re-derivation from raw and corrected five times in one session — the
reference table inherits those corrections, not the first drafts.

## Status: spine (v0.1)

Built: event model, the wall, five adapters (claude-code, cursor, cursor-store,
sqlite, postgres), injection filter, six analyzers, markdown + JSON renderers,
CLI (`run`, `doctor`, `adapters`, `analyzers`), test suite (wall + pipeline +
db-adapter + CLI-surface + regression tests for every review finding).

Named and deliberately unbuilt:
- `distinctive_tokens` and any content-derived token feature — **absent until
  the feature layer has its own PII scrub** (that feature is where names and
  identities live).
- The guardian-consent model (owner ≠ subject) — the biggest gap between this
  toolkit and any family-facing instrument; not solved, so not shipped.
- Bootstrap CIs / band-sensitivity on rates; claude.ai web-export and
  agent-fleet adapters; a prose renderer (JSON now ships; prose does not).
- `turns_to_completion` is on the claim allowlist and has **no analyzer**: these
  corpora record an abandoned thread and a finished one identically, so a
  "turns to completion" number would be a guess wearing a denominator.
- The cursor adapter keeps only turns carrying the runtime's injected
  timestamp tag — conservative, undercounts, and **every dropped turn is
  counted in the audit line** (not silently discarded). On a real corpus it
  read 12 of 310 session files for this reason; `cursor-store` is the way in
  to the same work.
- The cursor-store adapter gives operator turns no per-turn tempo, because the
  store has none to give. Reconstructing one would need Cursor to log it.

The classifiers are regex heuristics with known false-positive/negative modes
(a mixed personal + coding corpus is where they are weakest); the reference
numbers are one verified N=1, not a population you belong to. Grade direction,
spot-check before you cite.

Lineage: consolidates the ad-hoc instruments of the willow personal-research
sessions (2026-07) into the architecture planned there; the inference wall is
the `learner-model-ground-rules` made mechanical.

## Contributing & security

- [CONTRIBUTING.md](CONTRIBUTING.md) — the load-bearing rules (never overclaim;
  the wall discipline for new adapters/analyzers; classifiers undercount, never
  over) and how to run the tests.
- [SECURITY.md](SECURITY.md) — what counts as a wall breach (and what is a
  disclosed limit, by design), and how to report privately.
- [CHANGELOG.md](CHANGELOG.md) — dated, in-the-open amendments.

CI runs the suite on Python 3.10–3.14 plus a packaging smoke test on every push.

Apache-2.0 · ΔΣ = 42
