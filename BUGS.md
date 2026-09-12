# Known bugs

What is actually wrong, what was wrong and is fixed, and what looks like a bug
but is a disclosed limit. The third list is load-bearing: this project's whole
value is that it does not overclaim, and a limit written down on purpose must
not get quietly "fixed" into a claim the code cannot support.

Report anything here, or anything missing from here, as an issue. A **wall
breach** goes to [SECURITY.md](SECURITY.md) instead — privately, and it is the
highest class of bug this project has.

---

## Open

### 1. `tempo` measures from the previous event, and a prompt-to-prompt number
would be a different measurement

**Half of this is fixed.** The headline used to read "your prompts arrive a
median N seconds apart", which claimed something narrower than the number:
`delta_prev_s` is the gap since the previous **event** in the thread, usually
the machine's own reply. The sentence now says that, in the report and in the
README. No number moved, so no analyzer version bump.

What is still open is whether the *measurement* should change. A
prompt-to-prompt gap — human turn to human turn, skipping whatever the machine
did in between — is a different and arguably more interesting quantity: it is
the one the reference N=1 in GRADING.md reads as a rhythm of a person. Adopting
it would move every tempo number, so it needs a `version` bump on the analyzer
and a re-based reference point, and it should probably be an additional field
rather than a replacement.

Note also that dropped records advance the clock on purpose (the `keep the
clock advancing` branch in `claude_code.py`), so a machine turn the injection
filter correctly refuses to count still contributes its timestamp to the next
real gap. Under the corrected wording that is consistent rather than wrong, but
it would have to be revisited alongside any prompt-to-prompt measurement.

### 2. A compaction boundary is invisible to `thread_shape` and `thread_span`

When the runtime compacts a conversation it writes a `system` record with
`subtype: "compact_boundary"` carrying the trigger and the uuid of the last
pre-compaction message, followed by a user-role record flagged
`isCompactSummary`. The summary is now skipped on that flag (see Fixed below).
The **boundary** is not used at all.

`system` records are already dropped, so nothing is miscounted. But a
compaction is a real discontinuity in a thread — the turns before it are no
longer in context — and `thread_shape` and `thread_span` treat the thread as
continuous across it. On a long session that compacts several times, whatever
those analyzers report about span and density is measured over a thread that
the runtime had already cut up.

Not fixed, for two reasons. Using the boundary would change what
`thread_shape` and `thread_span` mean, which needs an analyzer `version` bump
and a re-based reference point. And the record shape above comes from a
description of the producer's source that nobody on this side can reach: the
existence of `compact_boundary` in real transcripts was confirmed by the owner
grepping his own corpus on another machine, but the field layout was not.

**What would close it:** one real compacted transcript in the fixtures, with
the anchor quarantined per the Guard. Then the shape is observed rather than
described, and the semantic change can be made against something real.

### 3. `changelog_dedup.py` cannot fix a *first* release

This repo merges with merge commits, so release-please parses each change twice
— once from the real commit, once from the merge commit carrying its title.
`tools/changelog_dedup.py` rebuilds the section from the commits and drops merge
commits, and it works (verified on the 0.1.0 section).

It no-ops on a **first** release: its section matcher expects the
`## [x.y.z](…/compare/…)` heading release-please writes for every release after
the first, and a first release has no previous tag to compare against. The 1.0.0
section shipped with every entry duplicated.

Per that file's docstring the tool is fixed in forge-play first and re-synced
here, so this stays open until that happens. **Workaround:** fix a first
release's changelog section by hand before merging the release PR.

### 4. An unclosed known wrapper tag consumes the rest of the turn

`injection.py` strips an enumerated list of machine-injected wrappers. When a
known tag appears **unclosed**, the pattern consumes to the next open tag or the
end of the turn — so a human who writes `<timestamp>` or `<task-notification>`
in angle brackets mid-sentence loses everything after it.

This is a deliberate trade, not an oversight: the alternative is leaving
thousands of words of injected context counted as something a person typed, and
that is the failure this filter exists to prevent. It is listed here because it
*is* a way to lose real text, and because the odds rise as the tag list grows.
Plain prose is untouched — only the angle-bracketed form matches.

---

## Fixed

### `doctor`'s drop warning misfired on agentic corpora

`corpuslens doctor` used to warn whenever more than half of the records read
were dropped: *"check the adapter (and --table) before trusting any rate
computed from the rest."* On a modern Claude Code corpus that fired every
time and meant nothing.

Measured on this project's own session log: 1,112 records read, 70 kept,
**93.7% dropped** — and every one of those drops was correct. 272 were
`tool_use`, 271 `tool_result`, 108 `thinking`, 226 `attachment`, the rest
harness bookkeeping (`ai-title`, `atis-latch`, `last-prompt`,
`queue-operation`). None of them were turns. Nothing was wrong.

The drop count was conflating two different things:

- **not a turn by design** — tool traffic, thinking blocks, attachments,
  harness bookkeeping, dispatched/subagent traffic, a compaction summary.
  Normal, and no reason to distrust anything.
- **should have been a turn and failed** — an unparseable line, a record with
  no usable timestamp, an unrecognised role, an empty turn. *This* is the
  number a reader should judge a corpus by.

Fixed by widening the adapter contract's third element from a bare `int` to
`ingest/drops.py::DropCounts` — still always the same 3-tuple
`(events, quarantine, drops)` every adapter returns, for every call, with no
keyword that changes its shape (that exact shape-changes-under-a-flag mistake
is what the separate `label_text` seam already exists to avoid, and this
change was held to the same rule). `DropCounts` tallies every drop under a
CLOSED, enumerated reason (tool traffic, thinking, an attachment, harness
bookkeeping, a subagent, a compaction summary, and, for a genuine failure, an
unreadable file, an unparseable line, a missing timestamp, an unrecognised
role, or an empty turn — plus a single honest "unknown reason" bucket for an
adapter that cannot tell the two classes apart) and exposes `.total` so any
reader that only ever wanted the old aggregate number still has one line to
get it back. Every adapter — `claude-code`, `cursor`, `cursor-store`,
`gemini-cli`, `sqlite`, `postgres`, `forge` — classifies its own drop sites
into this vocabulary; `_rows.py::assemble`, the one shared assembler the
database-shaped adapters all go through, tags its one drop site (empty text
after de-injection) the same way.

`doctor` now reports `events_dropped_structural`, `events_dropped_malformed`
and a `dropped_by_reason` breakdown alongside the old `events_dropped` and
`drop_pct` (kept for continuity), and warns on `malformed_drop_pct` — the
malformed share of KEPT-plus-malformed records — rather than the combined
total. On the exact corpus this bug report measured, `drop_pct` still reads
in the 90s; `malformed_drop_pct` reads near zero, and the warning stays
quiet. `guard.AuditRecord`'s audit sentence — a wall-visible claim — grew the
same split (`n_dropped_structural`, `n_dropped_malformed`,
`dropped_by_reason`), so `run`'s output states the distinction too, not just
`doctor`'s diagnostic.

Two things this touched that are worth naming because they are easy to get
wrong the same way twice. First, a per-reason breakdown published at EXACT
counts in `--share` mode would have been a new instance of the very leak
class this file's `n_events`-vs-`scan_egress` finding (below, under the
postgres entry's near neighbors — see `share.py`'s own docstring) already
named: an exact count is not a quarantined literal, so the literal egress
scan cannot catch it. `share.coarsen_audit` now bands every one of the new
fields (`share.band_dropped_by_reason`, one `band_n` per reason), and
`share_shape.py`'s allowlists were extended to cover them structurally, so an
un-banded breakdown is refused by `Guard.scan_share_shape` rather than
shipped — proven by a hostile fixture in `tests/test_share_shape.py`. Second,
the audit record's shape changed (three new fields on `as_dict()`), which is
exactly what `render.SCHEMA_VERSION` exists to govern; it moved from `1` to
`2`, and `corpuslens diff` refuses to compare a report from before this
change against one from after it (naming `schema_version differs`, per its
own existing hard-refusal rule) rather than reading the older report's
absence of the new fields as if it were a changed value — the same mistake
recorded below for `analyzer_version`, avoided here on purpose.

### The postgres adapter printed the operator's database password

`psql` echoes the whole connection URI back on a URI parse error, and the
adapter raised `ValueError(f"psql error: {proc.stderr...}")`, which the CLI
printed verbatim:

```
$ corpuslens run --adapter postgres "postgres://seanuser:hunter2@[bad/corpus"
error: psql error: psql: error: end of string reached when looking for
matching "]" in IPv6 host address in URI: "postgres://seanuser:hunter2@[bad/corpus"
```

A plaintext database password on stderr, into shell scrollback and CI logs.
Other failure modes leaked less but in the same way: an internal hostname on a
DNS failure, a username on an authentication failure.

Two things made it invisible. First, `Guard.scan_egress` — both the literal
scan and the structural one — guards the *rendered report*, and **an error is
not a report**; nothing watched this channel at all. Second, the leaked text
was written by `psql`, not by this repo, so no amount of reviewing corpuslens's
own strings would have found it. It was found by probing the adapter with a
hostile DSN, not by reading the code.

Fixed by `corpuslens/failure_classes.py`: a closed vocabulary of failure
phrases. The foreign text is read to *classify* it and never interpolated, so
no substring of the input can reach the output — asserted directly, including
against the exact stderr above, in `tests/test_failure_classes.py`. The sqlite
adapter's `({e})` was the same shape and got the same treatment. The cost is
real and deliberate: "authentication failed" tells an operator less than
psql's own sentence, and the fix must not be quietly undone by appending
`(detail: ...)` to these messages later.


Every entry has a regression test; this project's rule is that a fixed bug gets
one. Named here so the finding survives even if the test is ever renamed.

### `subagents/` transcripts were read as the operator's own threads

The `claude-code` adapter walked into `<session>/subagents/agent-*.jsonl` and
treated it as another of the operator's threads. Those files have the same shape
and the same `"type": "user"` records — but that "user" is the model writing a
task prompt to its own subagent.

Found by running corpuslens on its own session log. Including three subagent
transcripts moved `opener_median_words` from **11 to 516**, turned one thread
into four, and pulled the mid-task share from 93.3% down to 77.8%. For a tool
whose scope rule is owner == subject, three of those four "threads" were not a
person at all.

Fixed by skipping any file under a `subagents/` directory component, counting
every skipped record as a drop. `tests/test_pipeline.py::DogfoodRegressions`.

### The corpus-type refusal, validated on a foreign corpus

Not a bug — a fixed thing confirmed working on data nobody wrote it for.

Pointed at SWE-agent's trajectories (22 real files, 489 steps),
`clarification_pull` refused rather than reporting 0.0%: 296 machine turns, and
`CLARIFY` matched none of them. That is the correct call and for the correct
reason. A SWE-agent machine turn is tool output and code, not conversational
English, so the regex genuinely cannot read it — which is one of the two
readings the refusal names, and it declined to pick between them.

The complementary case held too, measured the same night on this project's own
agent transcripts: there `CLARIFY` fired twice, so the analyzer reported a
genuine 0.0% instead of refusing. The distinction the feature draws between
"the regex found nothing" and "the regex works and the answer is zero" survives
contact with corpora it was not designed against.

### `diff` told the reader a classifier had changed when nothing had

Per-analyzer versions are new, so any report produced before them carries no
`analyzer_version`. Diffing such a report against a current one compared
`None` against `1`, called it a version mismatch, and stated that "the
classifier or threshold behind this number changed between the two runs."
Nothing had changed. The field simply did not exist when the older report was
written, and the tool had asserted a fact it did not have.

Worse in the other direction: two reports that **both** predated versioning
compared as equal, in silence, with no warning at all — a clean diff that had
checked nothing, which is the most misleading of the three outcomes.

Both are the same error, that absence of a version was being read as a value.
An absent version is now its own status: the comparison is still withheld,
because absence of evidence that two runs agree is not evidence that they do,
but the note says the older run predates versioning and that the tool cannot
tell whether the semantics match. The two-old-reports case warns instead of
passing silently.

Found by a reviewer reading the diff in PR 23 rather than by a test, which is
worth recording — nothing in the suite exercised a report older than the
feature, because every fixture was generated by the code under test.

### Dispatched traffic was skipped by directory name, not by its own marking

The `claude-code` adapter skipped subagent transcripts by looking for a
`subagents/` component in the path. That works for the layout it was written
against and nothing more.

The runtime marks the traffic on the **record**: every `user`/`assistant`
record carries `isSidechain`. Measured 2026-09-11 across this project's own
logs — 459 records in the operator's own thread, every one `False`; 1,634
records across seven subagent transcripts, every one `True`. Perfect
separation, from a first-class field rather than a naming convention.

The path check stays as the outer guard, because not reading those files at
all is cheaper. The field check is the inner one and is the more robust half:
a sidechain written anywhere else, or a runtime that renames the directory,
slips straight past a path filter.

The `gemini-cli` adapter reached the same conclusion from the opposite
direction — that runtime nests subagent logs under the *parent session's* id,
where a path filter finds nothing at all, so it keys on the record's own
`kind`. Two runtimes, one lesson: read the producer's marking, not the layout.

`tests/test_pipeline.py::DogfoodRegressions`.

The same commit gives compaction summaries the same treatment: they were caught only by the prose a summary happens to open with, and are now skipped on the runtime's own `isCompactSummary` flag, with the prose branch kept as the fallback. That field name is unverified on this side and the check is inert if it is wrong — see the provenance note in `claude_code.py`, and open bug 3 for the half that is not fixed.

### The harness's own "Continue from where you left off." was counted as the operator typing

Found 2026-09-12 by the owner, reading a report on his own 18-hour session:
he had never typed "Continue from where you left off." — the harness re-issues
it in the **user** role after every context reset. Eight of them in that log,
every one counted as an operator prompt against 23 the owner typed. They carry no
wrapper tag, so the injection filter could not see them, and the text is
exactly what a person might type, so a prose match would have been wrong in
both directions.

The record carries the answer itself. Each one is flagged `isMeta: true`; no
human turn is. And every turn the owner typed carries `origin: {"kind":
"human"}` (23 of 23, each also `promptSource: "sdk"`), while every finished
background task carries `origin: {"kind": "task-notification"}` (122 of 122).
Perfect separation on the producer's own marking — the `isSidechain` lesson a
third time.

Fixed by keying on those two fields in `claude_code.py`
(`_is_harness_authored`): a user-role record with `isMeta`, or with a present
`origin.kind` that is not `"human"`, is `HARNESS_BOOKKEEPING`. Fail-open on
absence — a record with neither field is as much a turn as before, so older
logs and other producers are untouched. The same check corrects a second
mis-bucketing: a `<task-notification>` turn was stripped to nothing by the tag
filter and then counted as `EMPTY_TURN`, "should have been a turn and failed",
which put 122 correct drops on the malformed side of `doctor`'s warning (36.8%
malformed on a corpus with nothing malformed in it). Keyed on the field they
are structural, and the corpus reads 0 malformed. Regression tests:
`tests/test_drop_reasons.py::HarnessAuthoredUserTurnTests`, including one that
keeps the same resume wording when `origin` says a human typed it — the check
reads the field, never the text.

**Residual, not fixed here:** `doctor` on that log now reads 24 operator
turns, not 23. The one left is `[Request interrupted by user]`, which the
harness writes in the user role with neither field — a text-anchored door of
the same class as the stop-hook prefix, and it belongs in `MACHINE_TURN`'s
enumeration in `injection.py`, not in a field check. Recorded so the next
person does not rediscover it.

### A peer agent's relayed message was counted as the operator typing

A message relayed from another agent session arrives in the **user** role,
wrapped in `<cross-session-message from=… from-name=… from-mode=…>` under a
plain-prose preamble. It is one agent's output handed to another, and
`owner == subject` is this tool's scope rule.

Observed 2026-09-11 in this project's own log: one such turn ran **505 words**
against a human whose median was **6**, pulling the operator's mean word count
from **8.9 to 70.9**. The fourth distinct door through which machine-authored
text has reached the user role in this corpus, after `subagents/`,
`<task-notification>`, and the local-slash-command replay below.

Fixed by enumerating the wrapper and anchoring the preamble in `MACHINE_TURN`.
Same regression test class.

### A local slash command was counted as three operator prompts

Found 2026-09-11, the third time running corpuslens on its own session log has
caught machine text counted as a person — and the first time the harness door
was not a single tag.

Running `/model` locally replays into the **user** role as three separate
turns: a `<local-command-caveat>` block, a `<command-name>`/`<command-message>`
/`<command-args>` echo, and a `<local-command-stdout>` line. Separately, a stop
hook's output arrives in the user role with **no wrapper at all**, prefixed
only by the prose "Stop hook feedback:".

On that corpus the four of them were 4 of 11 counted operator turns. The
damage was not only the count:

- Two carried backticks, which fired `CODE_REF`. The report stated the operator
  referred to existing code in **18.2%** of prompts. The true rate over the
  turns a person actually typed was **0.0%** — the entire signal was the
  machine quoting a model identifier.
- Three arrived with deltas of zero or a fraction of a second, so measured
  `burst_pct` read **70.0%** against a real **50.0%**, and the median gap read
  **25.8s** against a real **51.7s**. The same person-shaped-signal failure the
  task-notification finding below describes, from a different door.

Fixed by enumerating the five observed tags and adding the stop-hook prefix to
`MACHINE_TURN`. `tests/test_pipeline.py::DogfoodRegressions` covers both.

### `<task-notification>` blocks were counted as operator prompts

A finished background task delivers its whole result in the **user** role. The
injection filter knew `<system-reminder>` and Cursor's wrappers but not this
one, so the result counted as something the operator typed: three turns of
1728, 902 and 1246 words against a human whose median was 28, with
`injected_stripped` false on every one.

It was not only word counts. Those turns carried tempo deltas, and an automated
notification arrives seconds after the work it reports — so measured `burst_pct`
read **57.1%** when the human's own rate was **36.4%**. A machine turn counted
as a prompt does not just add noise, it adds a person-shaped signal that was
never there.

Fixed by enumerating the tag (observed, never guessed) and admitting `-` to the
terminator class for unclosed blocks. Same regression test class.

### The first release published `1.0.0`

Comments in `pyproject.toml` and `release-please-config.json` asserted that a
`0.0.0` manifest makes the first `feat:` propose `v0.1.0`. It does not: with no
prior release, release-please's first release is `1.0.0` whatever the manifest
says. The assertion was never tested, and the pipeline did exactly what it was
configured to do.

`1.0.0` is a compatibility promise, and this project ships a spine. It was the
largest overclaim in the repository for about fifteen minutes. Recovery required
deleting the PyPI project, because **a PyPI version can never be reused or
replaced**. Re-cut as `0.1.0` with a `Release-As` footer; both comments now say
what release-please actually does. See [CONTRIBUTING.md](CONTRIBUTING.md).

### The changelog preamble was deleted by a correction

An index-based cut removing the 1.0.0 section reached further up the file than
intended and took the preamble with it — including the line saying corrections
sit beside the record they correct, never overwrite it. Deleted, in a commit
whose purpose was to write a correction. Restored, with a sentence naming which
part of the file release-please owns.

---

## Not bugs: disclosed limits

These are in the design and in the docs on purpose. Changing any of them means
changing what the tool *claims*, in the same pull request.

- **The wall does not hide weekly cadence.** `day_offset % 7` preserves the
  shape of a week up to one unknown rotation. That is inherent to computing
  resumption and concurrency at all.
- **The wall does not fully hide within-day time-of-day.** Cross-midnight deltas
  are censored, but within-day tempo survives and its cumulative span loosely
  *bounds* the local clock on a long day. `tempo` deliberately publishes no
  cumulative within-day span so as not to sharpen that bound.
- **The wall is not an adversarial sandbox against its owner.** It stops
  accidental leaks and constrains analyzer plugins. You can always read your own
  quarantined data by editing your own script.
- **`cursor-store` reports no tempo for operator turns.** The store clocks tool
  steps, not prompts. Interpolating one would invent exactly the quantity the
  wall governs.
- **The `cursor` adapter undercounts badly** — it keeps only turns carrying the
  runtime's injected timestamp tag, which on one real corpus was 12 of 310
  session files. Every dropped turn is counted in the audit line.
  `cursor-store` is the way in to the same work.
- **The classifiers are regex heuristics** and undercount on purpose. A false
  negative on real code is acceptable; a false positive that inflates "you write
  code" is not.
- **`turns_to_completion` has no analyzer.** These corpora record an abandoned
  thread and a finished one identically, so the number would be a guess wearing
  a denominator.
- **`SMALL_N = 30`** in the renderer is a convention, not a power analysis. The
  report says "read the direction, not the decimal" rather than implying a
  confidence interval the tool does not compute.
- **The instrument alters its own subject.** Reading your own process numbers
  changes your process, so a second run measures someone who has read the first,
  and a longitudinal trend cannot separate real change from response to the
  instrument. Disclosed in the README ("Reading this changes what it measures").
  The size of the effect is unmeasured and probably unmeasurable — you cannot
  un-see your own numbers, so there is no control.
