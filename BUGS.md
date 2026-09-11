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

### 1. `doctor`'s drop warning misfires on agentic corpora

`corpuslens doctor` warns when more than half of the records read were dropped:
*"check the adapter (and --table) before trusting any rate computed from the
rest."* On a modern Claude Code corpus that fires every time and means nothing.

Measured on this project's own session log: 1,112 records read, 70 kept, **93.7%
dropped** — and every one of those drops is correct. 272 were `tool_use`, 271
`tool_result`, 108 `thinking`, 226 `attachment`, the rest harness bookkeeping
(`ai-title`, `atis-latch`, `last-prompt`, `queue-operation`). None of them are
turns. Nothing was wrong.

The drop count is conflating two different things:

- **not a turn by design** — tool traffic, thinking blocks, attachments. Normal,
  and no reason to distrust anything.
- **should have been a turn and failed** — an unparseable line, a record with no
  usable timestamp, an unrecognised role, an empty turn. *This* is the number a
  reader should judge a corpus by.

The fix is to count them separately and warn on the second only. That changes
the audit sentence's `dropped` figure, which is a wall-visible claim, so it is
a design change rather than a patch — hence open rather than done.

**Workaround:** on an agent corpus, read the `operator_turns` / `machine_turns`
/ `threads` counts and ignore `drop_pct`.

### 2. `tempo`'s headline says "your prompts", its computation says "any event"

`tempo` reports "Your prompts arrive a median N seconds apart within a thread."
The number under that sentence is `delta_prev_s`, which `claude_code.py`
defines as seconds since the previous **event** in the thread — usually the
machine's own response, not the operator's previous prompt.

Those differ by however long the machine's turn sat in between. On a corpus
where the assistant answers in ten seconds the gap is small; on one where it
works for four minutes the headline understates the operator's real
prompt-to-prompt rhythm by roughly that much, every time.

Dropped records advance the clock too, on purpose — the `keep the clock
advancing` branch in `claude_code.py`. So a machine turn that the injection
filter correctly refuses to count as a prompt still contributes its timestamp
to the next real turn's delta. Found 2026-09-11 while writing the regression
test for finding 3 below, where a stop hook's output one second after a prompt
left the next gap reading 539s instead of 540s.

Neither half is a coding error; both are deliberate and the docstrings say what
they do. The bug is that the **sentence claims something narrower than the
number measures**, and this project's first rule is that claims match code.

Fixing it means either rewording the headline to say what is measured, or
measuring prompt-to-prompt and re-basing every tempo reference point. The
second changes what the number means, so it needs an analyzer `version` bump —
the mechanism for which now exists. Open rather than patched because picking
between those two is a design decision, not a typo.

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
