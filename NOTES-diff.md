# Doc changes needed for the `diff` + per-analyzer-version feature

Written instead of editing README.md / IDEAS.md directly (seven agents are
working in parallel on this repo). Each block below is an exact old/new pair
a maintainer can apply verbatim. Code changes are already committed on
`claude/expand-diff`: `corpuslens/diff.py`, `corpuslens/analyze/__init__.py`
(the `version` / `semantic_hash` fields), `corpuslens/cli.py` (the `diff`
subcommand), and `tests/test_diff.py` + `tests/test_analyzer_versions.py`.

Note on fencing below: README.md and IDEAS.md quote fenced code blocks (bash
examples, JSON shapes) inside their own text. Each Old/New pair here is
wrapped in 4-backtick fences purely so those inner ``` fences survive
copy-paste — the 4 backticks themselves are not part of what to paste.

---

## README.md

### 1. Add `diff` to the subcommand list and mention analyzer versions

**Old** (in `### The other subcommands`):

````markdown
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
````

**New:**

````markdown
```bash
corpuslens doctor ~/.claude/projects --adapter claude-code   # what WOULD be read
corpuslens adapters                                          # what can be read
corpuslens analyzers                                         # what gets computed, and each one's version
```

`doctor` is a dry run of ingestion only: how many records an adapter could see,
how many it had to drop and what share that is, how many threads and relative
days it found, and — the useful part before you commit to a report — which
analyzers this corpus *cannot* feed (a corpus with no machine turns can't give
you `clarification_pull`; one with no prompt clock can't give you `tempo`). It
runs no analyzer and emits no rate, counts rather than content, and its output
passes the same fail-closed egress scan the report does. `adapters` and
`analyzers` list what is registered — each adapter with the argument it expects,
each analyzer with its claim type, its named denominator, and its semantic
`version` (see "Diffing two runs" below).
````

### 2. New subsection: "Diffing two runs"

Insert this whole new subsection immediately after the existing `--since-day`
/ `--until-day` paragraph (which currently ends the `### JSON output, and
analyzing a slice` section) and before `### Cursor's store.db`:

````markdown
### Diffing two runs

```bash
corpuslens run ./corpus --adapter claude-code --format json --out jan.json
corpuslens run ./corpus --adapter claude-code --format json --out mar.json
corpuslens diff jan.json mar.json
```

A single reading has no baseline except a stranger's N=1; `diff` makes a
*second* reading of your own corpus meaningful. Every analyzer now carries a
semantic `version` — not `schema_version` (the JSON document's shape) but what
a number *means*: the classifiers and thresholds it depends on. `diff` uses
both to decide what it can honestly report:

- **Refuses outright** (no numbers at all) when the two runs used a different
  `--adapter`, or a different `schema_version` — these are different
  instruments over different corpora, or documents this code was not built to
  read the same way; there is no reading under which a delta between them is a
  trend in your process rather than a difference in the tool.
- **Runs, but says so loudly** when either side was filtered with
  `--since-day`/`--until-day` (a banner marks the comparison a subset one), or
  when a specific shared analyzer's `version` disagrees between the two runs
  (that one analyzer's delta is withheld and explained; every other analyzer
  that didn't change version is still diffed normally).

A malformed or non-corpuslens JSON file is a clear `error:` line, never a
traceback. `--format json` on `diff` emits the full comparison as data
(`{diff_schema_version, a, b, refused, refusal_reasons,
comparability_warnings, analyzers, caveat}`); both runs' full audit records —
sentence included — travel with it, the same rule `--format json` already
holds for a single run.
````

### 3. Battery / status line

**Old:**

````markdown
Built: event model, the wall, five adapters (claude-code, cursor, cursor-store,
sqlite, postgres), injection filter, six analyzers, markdown + JSON renderers,
CLI (`run`, `doctor`, `adapters`, `analyzers`), test suite (wall + pipeline +
db-adapter + CLI-surface + render + regression tests for every review finding).
````

**New:**

````markdown
Built: event model, the wall, five adapters (claude-code, cursor, cursor-store,
sqlite, postgres), injection filter, six analyzers (each carrying a semantic
`version`, distinct from `schema_version`), markdown + JSON renderers,
CLI (`run`, `doctor`, `adapters`, `analyzers`, `diff`), test suite (wall +
pipeline + db-adapter + CLI-surface + render + analyzer-version + diff +
regression tests for every review finding).
````

---

## IDEAS.md

### 1. Mark `corpuslens diff two runs` as shipped

**Old** (the whole entry, under `## Near`):

````markdown
### `corpuslens diff two runs`

A single reading has no baseline except a stranger's N=1. Process metrics are
interesting as *trends*: "your mid-task share moved 62% → 81% since June" is a
different product from "your mid-task share is 81%."

`--format json` now exists, which is most of the work: the JSON carries a
`schema_version`, the full results, and the audit record. A `diff` subcommand
taking two JSON files and reporting the deltas is maybe a day's work, and it is
the feature that makes someone run the tool twice.

Care needed: two runs are only comparable if the corpus and the filters match.
A diff across different adapters, or where one side used `--since-day`, has to
say so loudly rather than subtract the numbers anyway.

**Ship it with per-analyzer semantic versions, not before them.** The Stretch
entry [Metrics that stay comparable across tool versions](#metrics-that-stay-comparable-across-tool-versions)
explains why: the injection filter has already changed what counts as an
operator turn twice, and a `diff` that cannot tell a software change from a
process change is worse than no `diff` — it would print a trend that is really
a changelog entry. The mechanism is small: each analyzer declares a `version`,
the result records it, and `diff` refuses (or loudly annotates) a comparison
where the two sides disagree. What stays in Stretch is the discipline of
bumping it correctly forever; what moves here is the field and the check.
````

**New:**

````markdown
### `corpuslens diff two runs` — shipped

Built: `corpuslens diff a.json b.json` (`corpuslens/diff.py`), together with
per-analyzer semantic `version` + a pinned `semantic_hash` on every analyzer
(`corpuslens/analyze/__init__.py`), exactly the pairing this entry called for.

The split that shipped: `diff` **refuses outright** (no numbers at all) when
the two runs used a different `--adapter` or a different `schema_version` —
different instruments, or documents this code was not built to read the same
way, so no number on either side would stay meaningful next to a warning.
It **runs but annotates loudly** when a side was filtered with
`--since-day`/`--until-day` (a real, nameable scope difference a reader may
actually want to compare), or when one shared analyzer's `version` disagrees
between the two runs — scoped to that analyzer alone, so one classifier
change doesn't silently withhold every other number that is still honestly
comparable.

What is still open: the maintenance discipline of bumping `version` correctly
forever is unchanged from the Stretch entry below — a pinned `semantic_hash`
test (`tests/test_analyzer_versions.py`) catches a classifier/threshold edit
that forgets to bump `version`, but it cannot catch a bump that was made for
the wrong reason, or a change to filtering logic that isn't a regex the hash
mechanism was pointed at.
````

### 2. Update the Stretch entry's closing note

**Old** (last paragraph of `### Metrics that stay comparable across tool versions`):

````markdown
*2026-09-11:* the field and the check moved to Near, coupled to `diff` so the
two ship together ([`corpuslens diff two runs`](#corpuslens-diff-two-runs)).
What stays here is the maintenance discipline — a test that fails when a
classifier regex changes without its version bumping would carry most of it,
and is worth writing with the field.
````

**New:**

````markdown
*2026-09-11:* the field and the check moved to Near and shipped, coupled to
`diff` as planned ([`corpuslens diff two runs`](#corpuslens-diff-two-runs)).
The maintenance-discipline test was written
(`tests/test_analyzer_versions.py`): each analyzer pins a `semantic_hash`
computed from the literal classifier regex / threshold text its number
depends on, and the test recomputes that hash from the live source and fails
the moment it drifts from the pinned value — which is exactly what an
unbumped `version` looks like from the outside. What remains open is the part
this note always said would remain open: the test forces the DECISION (bump
version, recompute the hash) into the open, but cannot make the decision
correctly for someone in a hurry, and it only covers analyzers whose
semantics live in a regex or a named threshold constant — a change to
control-flow (e.g. which turns count as "eligible" at all) would not move
any pinned hash and would need its own inputs added deliberately.
````
