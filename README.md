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
**relative time is process; the absolute anchor is person.** That origin is a
direct observation rather than a published study: on the author's own corpus of
thousands of sessions, a custody schedule was legible from keystroke timing
alone, with no content read at all. Content redaction does not scrub the shape
of a week. So:

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

The distribution is **`willow-corpus-lens`**; the command it installs is
**`corpuslens`**. (`corpus-lens` on PyPI is an unrelated project — a TF-IDF
corpus dashboard — so the fleet prefix disambiguates rather than competes.)

```bash
pip install willow-corpus-lens          # then: corpuslens run ...
pipx install willow-corpus-lens         # or, isolated
uvx --from willow-corpus-lens corpuslens run ~/.claude/projects --adapter claude-code
```

Zero dependencies is what makes those reliable. Releases are cut by
release-please and published on the tag through Trusted Publishing, with PEP 740
provenance attestations — no token in the repo.

From source instead:

```bash
git clone https://github.com/willow-memory/corpus-lens
cd corpus-lens
pip install .           # or: pip install -e .  (for development)
```

This installs a `corpuslens` console command. You can also run it without
installing, straight from a clone, via `python3 -m corpuslens`.

## Quickstart

```bash
corpuslens run                                          # find a corpus and read it
corpuslens run ~/.claude/projects --adapter claude-code --out report.md
corpuslens run ./my-cursor-sessions --adapter cursor
corpuslens run ~/.cursor/chats --adapter cursor-store  # Cursor's own store.db tree
corpuslens run ~/.gemini/tmp --adapter gemini-cli       # Gemini CLI's chat JSONL
corpuslens run ./corpus.db --adapter sqlite            # a SQLite corpus (a file)
corpuslens run "dbname=mycorpus" --adapter postgres    # a Postgres corpus (a DSN)
# equivalently, from a clone without installing:
python3 -m corpuslens run ~/.claude/projects --adapter claude-code
```

Point `--adapter claude-code` at a directory of Claude Code session `.jsonl`
files, or `--adapter cursor` at a directory of Cursor session `.jsonl` files.

**Two things the claude-code adapter deliberately does not count as you**, both
found by running this tool on its own session log:

- **`subagents/` transcripts are skipped.** An agent the assistant dispatched
  writes a transcript of the same shape, with the same `"type": "user"` records
  — but that "user" is the model prompting its own subagent. Including three of
  them moved `opener_median_words` from **11 to 516** and turned one thread into
  four. Skipped records are counted as drops, never hidden.
- **`<task-notification>` blocks are stripped.** A finished background task
  delivers its whole result in the user role: three such turns ran 1728, 902 and
  1246 words against a human whose median was 28. Left in, they also inflated
  the measured `burst_pct` — an automated notification arrives seconds after the
  work finishes, which is not a person typing fast.

Both are the Cursor front-loading finding again, in a different runtime. If your
corpus has machine-authored turns this filter does not know, the symptom is the
same: an opener median in the hundreds or thousands of words. `corpuslens doctor`
will show you the drop share; a look at `opener_median_words` will show you the
rest.
`--adapter gemini-cli` reads Gemini CLI's own session JSONL. Read the honesty
note on it first: unlike every other adapter here, it was built by reading the
**source that writes the format** rather than a real corpus, because nobody on
this project has one. The field names and the file layout come from that source
and are cited in the adapter's docstring; what has never happened is a run
against a real Gemini CLI log. Point it at yours and check `doctor`'s drop share
before trusting a rate.

It also does not filter dispatched traffic by directory. Gemini CLI nests a
subagent's transcript under the **parent session's id**, where a path filter
finds nothing, so the adapter keys on the runtime's own `kind` field instead.
The claude-code adapter learned the same lesson from the other end and now reads
`isSidechain` rather than trusting a directory name.

`--adapter cursor-store` reads the chat store Cursor keeps for itself — a tree
of `store.db` SQLite files under `~/.cursor/chats`, one per thread. See
[Cursor's store.db](#cursor-storedb) for what that corpus can and cannot tell
you about time.
The report prints to stdout (or `--out FILE`), and always opens with a
plain-language audit line naming exactly what left the wall and how many input
records were dropped.

### The first run, with no arguments

```bash
corpuslens run
```

With no path and no `--adapter`, corpuslens looks in the conventional locations
each adapter declares for itself — `~/.claude/projects`, `~/.cursor/chats`,
`~/.gemini/tmp` — and tells you what it found **before** it reads anything: which
locations exist, how many candidate session files are in each, and which adapter
it would use. If several corpora exist it runs the largest and names the
runner-up, so the guess is visible rather than silent. If it finds nothing it
lists every path it checked.

Discovery is a guess about intent, so the run says which corpus it chose in the
**audit sentence itself** — not just in the terminal — and a saved report
therefore records what was read.

It reports the location in its declared `~/...` form and never the resolved one.
That is not cosmetic: a resolved home directory contains the owner's username,
and printing it in the sentence that says no filename left the wall would put a
person's name in the one line that claims nothing identifying escaped. The audit
record refuses a resolved value outright rather than trusting callers not to
pass one.

The explicit two-argument form is unchanged. Giving only one of the two is an
error rather than a half-guess.

### The other subcommands

```bash
corpuslens doctor ~/.claude/projects --adapter claude-code   # what WOULD be read
corpuslens adapters                                          # what can be read
corpuslens analyzers                                         # what gets computed
corpuslens label ~/.claude/projects --adapter claude-code    # grade the classifiers yourself
corpuslens score ~/.claude/projects --adapter claude-code    # what your labels say they score
corpuslens diff a.json b.json                                # the delta between two runs
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

### Grading the classifiers against your own judgment

Every headline percentage rests on four regex classifiers, and until you measure
them the honest guidance is the one below: read the direction, spot-check before
you cite. `label` and `score` let you replace that advice with a number.

```bash
corpuslens label ~/.claude/projects --adapter claude-code   # then answer y/n
corpuslens score ~/.claude/projects --adapter claude-code
```

`label` samples eligible turns under a **fixed seed** — the same corpus and
sample size draw the same turns, so a session you abandon resumes rather than
re-rolls — shows you each one, and asks one yes/no per classifier that applies
to it. `score` then re-runs the classifiers over the same corpus and reports
**precision, recall and n per classifier**, with named denominators like every
other rate here.

**You** do the labelling. No model reads your turns and no heuristic guesses a
label, because the whole point is to grade the heuristics against a judgment
that is not another heuristic. The store keeps only the label, the turn's opaque
hash, and the version of the classifier set you graded — never content, never a
filename, never a timestamp. Grade a different version and it refuses rather
than silently comparing across a definition change.

The default sample of 50 is a **convention**, like the small-sample threshold in
the report. It is not a power analysis, and corpuslens does not compute how
large a sample would have to be for a given confidence.

`label` works only on the `claude-code` adapter, because it has to show you your
own text and no one has implemented or tested that path for the other stores.
It refuses the rest rather than guessing at their content shape.

### Sharing a reading without the fingerprint

```bash
corpuslens run ./corpus --adapter claude-code --share
corpuslens run ./corpus --adapter claude-code --share --format json
```

`--share` is a modifier, not a third format, so it composes with either
renderer. It emits the headline rates and nothing else: every `n` becomes a
band, and the shapes are dropped rather than rounded — no tempo quantiles, no
thread counts, no day spans, no concurrency, no active-day counts. The audit
sentence stays, with its own counts banded too, because a reading without the
statement of what left the wall is not a corpuslens result.

The filter is an **allowlist of field names**. A field a future analyzer invents
is excluded by default rather than included by default, which is the same
fail-closed rule the Guard follows: absence of policy reads as denial.

**Read what it claims carefully.** Share mode is *coarsened*. It is not
anonymized and not de-identified, and this project has **not measured** whether
a coarsened report can still re-identify its owner — that question is open in
[IDEAS.md](IDEAS.md). The output says so itself rather than leaving you to
infer it. `doctor` is deliberately not covered: it prints exact counts by
design and is not a share-safe surface.

### Diffing two runs

```bash
corpuslens run ./corpus --adapter claude-code --format json > june.json
corpuslens run ./corpus --adapter claude-code --format json > sept.json
corpuslens diff june.json sept.json
```

A single reading has only a stranger's N=1 to sit against. The interesting form
is the trend, and `diff` reports the delta for every shared headline number,
carrying both runs' audit sentences with it.

It is built to refuse more readily than it reports, because a diff's failure
mode is presenting a change in the software as a change in you:

- **Different adapters, or different `schema_version`** — refused outright. A
  claude-code run and a cursor run are two instruments over two kinds of corpus.
- **Either side filtered** with `--since-day`/`--until-day` — diffed, under a
  loud banner saying these are subset numbers.
- **A shared analyzer's `version` differs** — that analyzer alone is withheld,
  and the rest still diff. Which direction the definition change moved the
  number is not derivable from the two documents; the note says so and points
  at the changelog.
- **Either side predates per-analyzer versions** — withheld, with a note saying
  the run is older than the versioning rather than pretending a classifier
  changed. Two such runs warn instead of comparing silently, because a clean
  diff that checked nothing is the most misleading answer available.

Every analyzer now records a `version` alongside its number, and a test pins
each classifier's pattern to a hash, so editing a regex without bumping its
version fails the suite rather than quietly moving every rate downstream.

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

`tempo` reports how long passes before each of your prompts, within a thread and
within a day — measured from **whatever the thread recorded last**, which is
usually the machine's reply rather than your own previous turn. Those differ by
however long the machine took, so this is a rhythm-of-the-session number, not a
how-fast-you-type one. It states the share of turns it has **no** gap for
outright — a turn that
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

## Which of the ten questions this actually answers

[GRADING.md](GRADING.md) poses ten questions. The report now names, per section,
which one that section answers and **how fully** — and leads with the true
shape rather than the flattering one: the battery fully answers two of the ten,
partly answers two more, and two of its six analyzers answer none of the
numbered questions at all and are reported as supporting signal.

That last part was worth saying out loud. `tempo` measures inter-turn gaps that
no question asks for. `clarification_pull` measures the machine asking and you
answering, which is the *reverse* of question 3's "do your prompts open a
discussion channel". Forcing either onto a number would have been a small
overclaim, so neither is forced.

Questions 5 through 8 (whether a stored claim can be demoted, when a negative
result was last recorded, whether an agent can grant itself anything, whether
checks fail closed) and 9 through 10 (whether your timestamps are a fingerprint,
who carries continuity across a session gap) are **not corpus-measurable**.
GRADING.md gives each its own manual test. The report says so rather than
letting the rubric read as a promise the tool kept.

## Honesty about the numbers

**The reference is one person.** Every analyzer compares you to
`measured_director` — the author's own corpus, N=1. The report now says that
where the comparison appears, because a percentage printed beside a reference
reads as a population. The WildChat and OASST figures beside it *are*
populations and stay labelled as such. A gap from the N=1 is a gap from one
person, and until you run `corpuslens label` and `corpuslens score` nobody can
say how much of it is you and how much is the regex.

The classifiers are regex heuristics: trust direction plus your own
spot-check, never raw percentages. The reference N=1 was verified by
re-derivation from raw and corrected five times in one session — the
reference table inherits those corrections, not the first drafts.

## Reading this changes what it measures

Stated plainly, because it is the one limit that is not about the wall and not
about the classifiers: **this instrument alters its own subject.** A thermometer
does not change the temperature. corpuslens does, because what it measures is
you, and you read the output.

Once you have seen that (say) 91.7% of your turns arrive mid-task, you are no
longer the operator who had never seen it. If a later run reads 84%, two
explanations fit equally well and the tool cannot separate them: your process
changed, or you steered toward a number you had read. Both look identical in the
data. That is not a bug and there is no fix in the code — it is what an
instrument pointed at its own user does.

Three consequences worth holding:

- **A second run does not measure a pristine baseline.** It measures someone who
  has read the first. The deeper you go into a longitudinal comparison, the more
  of the trend may be response to the instrument rather than change in the work.
- **The reference N=1 is a clean baseline; your later runs may not be.** That
  corpus was gathered *before* its operator began reading these numbers, so it
  is not itself subject to this effect. The asymmetry is the useful part: your
  first run is comparable to it under the same conditions, while a run made
  after months of watching your own metrics is not — you have changed, the
  reference has not. Drift from the reference over time is therefore not
  automatically drift in your work.
- **The effect is unmeasured.** Quantifying it would need a before/after on your
  own corpus with a control, and you cannot un-see your own numbers. Named in
  [IDEAS.md](IDEAS.md) as a stretch goal for that reason, not a to-do.

None of this makes a computed number wrong. The denominators are still named,
the drops still counted, the wall still holds. It changes what the numbers
*mean* — and a tool that describes itself as a lens for studying yourself should
say out loud that looking is not a neutral act.

## Status: spine (0.2.0, on PyPI)

Built: event model, the wall, six adapters (claude-code, cursor, cursor-store,
gemini-cli, sqlite, postgres), injection filter, six analyzers with per-analyzer
semantic versions, markdown + JSON + share renderers, the `timing_fingerprint`
computation, CLI (`run` — with zero-argument discovery — `doctor`, `adapters`,
`analyzers`, `label`, `score`, `diff`), test suite (wall + pipeline + db-adapter + CLI-surface + render +
share + label + diff + fingerprint + a regression test for every review and
dogfooding finding).

**0.2.0 is still a spine, and the version number still says so.** The wall, the
adapters and the analyzers are tested and the report is honest about its own
denominators — but the classifiers are heuristics whose error nobody has
measured yet (`label` is how you measure it; nobody has run it on a large
corpus), the reference numbers are one verified N=1, and the list below is
real. This is not a 1.x compatibility promise, and the one time the release
pipeline accidentally published it as one, it was withdrawn
([BUGS.md](BUGS.md)).

**What 0.2.0 added, and what it cost.** Seven features landed at once, each
built in isolation and then audited against these rules before merging. The
audit found five defects the builders had not reported — among them a share
mode that banded every denominator and published the exact corpus size anyway,
and a fingerprint that read a strong schedule out of uniformly random
timestamps. Running the tool on its own session log then found four more doors
through which machine-authored text was reaching the operator's count. All nine
are written up in [BUGS.md](BUGS.md) rather than quietly fixed, because a
project whose value is not overclaiming does not get to hide the times it did.

Named and deliberately unbuilt — the long version, with reasoning, is
[IDEAS.md](IDEAS.md):
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
- `leakage_demonstration` is on the claim allowlist and still has **no
  registered analyzer**. The computation behind it ships as
  `corpuslens.analyze.fingerprint.timing_fingerprint()`, which takes timestamps
  you pass it and reports how re-identifying their shape is — never the
  schedule, never a weekday, never an hour, and never a safe/unsafe verdict,
  because no defensible cutoff exists. There is deliberately **no
  `corpuslens fingerprint` command**: it would need a non-default profile, and
  whether a subcommand may construct one is exactly the question `cli.py`'s
  no-capability-flag claim leaves open. Designed in IDEAS.md, unresolved on
  purpose.
- The Guard is **not** extracted as a library. The design for doing it is
  [DESIGN-guard-extraction.md](DESIGN-guard-extraction.md), which argues for
  waiting until two independently motivated callers want the same primitive —
  and records that share mode, the first of them, turned out to need almost
  nothing from the Guard at all.
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
spot-check before you cite — or run `corpuslens label` and replace that advice
with your own measured precision and recall.

They are also **English-and-Python shaped**, which is a narrower limit than
"heuristic" suggests: the code-reference regex knows nine file extensions, the
authored-code regex knows a handful of languages' block syntax, and the
deliberation and clarification regexes are lists of English phrases. A coding
corpus in an unlisted language, or a conversation in another language, scores
identically to one with no code and no deliberation in it. Past a threshold the
analyzers now **refuse** rather than report that zero, naming both readings and
choosing neither.

Lineage: consolidates the ad-hoc instruments of the willow personal-research
sessions (2026-07) into the architecture planned there; the inference wall is
the `learner-model-ground-rules` made mechanical.

## Contributing & security

- [CONTRIBUTING.md](CONTRIBUTING.md) — the load-bearing rules (never overclaim;
  the wall discipline for new adapters/analyzers; classifiers undercount, never
  over), how to run the tests, and how a release is cut.
- [SECURITY.md](SECURITY.md) — what counts as a wall breach (and what is a
  disclosed limit, by design), and how to report privately.
- [BUGS.md](BUGS.md) — what is actually wrong right now, what was wrong and is
  fixed, and what looks like a bug but is a disclosed limit. That third list is
  load-bearing: a limit written down on purpose must not get quietly "fixed"
  into a claim the code cannot support.
- [IDEAS.md](IDEAS.md) — what is worth building next and why, including the
  things deliberately refused.
- [CHANGELOG.md](CHANGELOG.md) — dated, in-the-open amendments.

CI runs the suite on Python 3.10–3.14 plus a packaging smoke test on every push.
Releases are cut by release-please and published to PyPI on the tag through
Trusted Publishing; the release workflow installs the built wheel into a clean
environment and re-checks the audit line before anything is uploaded.

Apache-2.0 · ΔΣ = 42
