# Ideas

Things worth building, with enough of the reasoning that a future reader can
disagree with it. Nothing here is a promise — the README's "named and
deliberately unbuilt" list is the short version, and this is the long one.

The rule that governs all of it: **a feature that cannot state its denominator,
or that would make the tool claim more than it can support, does not get built
here no matter how good the demo would look.**

---

## Near — small, and the value is clear

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

### Zero-config first run

`corpuslens run` currently demands both an adapter and a path. The first run is
the adoption moment, and it asks the user to know two things they may not.

`corpuslens run` with no arguments could look in `~/.claude/projects` and
`~/.cursor/chats`, report what it found, and run what it can. `ccusage`
(MIT, actively maintained) already solved "find the user's agent logs across
CLIs and versions" and is worth reading before writing this from scratch.

### Split the drop count

`doctor`'s drop warning is useless on agent corpora because "not a turn by
design" and "should have been a turn and failed" are counted together. See
[BUGS.md](BUGS.md) #1. This is the smallest change with the largest effect on
whether a reader can trust a first run.

It touches the audit sentence, so it is a wall-visible change and needs the
claim updated in the same pull request.

### Say which rubric question each analyzer answers

[GRADING.md](GRADING.md) poses ten questions; the battery instruments the first
four. Questions 5–8 are about a system's honesty machinery and 9–10 about
continuity — mostly not derivable from session logs at all.

The report could name the question each section answers, and state plainly that
the rest are not corpus-measurable. That stops the rubric reading like a promise
the tool did not keep, and costs almost nothing.

---

## Analyzers worth considering

Each needs a claim type on the process-only allowlist in `model.py` and a named
denominator that matches its actual filter. Several of these were arrived at
independently by other people's tools — noted, because convergence is evidence
the signal is real, and because their code is readable.

- **Correction / redirect rate.** How often an operator turn walks back the
  previous one. `agent-retro` (MIT) flags corrections, redirects and abandoned
  approaches from Claude Code transcripts and traces friction to config edits.
  The hard part is the classifier: "no, do X instead" has to be told from
  ordinary elaboration, and per this project's rule it must undercount.
- **Convergence / drift / thrash per thread.** `agent-insights` (MIT) computes
  exactly this, plus productive-vs-wasted turns. Its concurrency detection is
  the same signal `thread_shape` already reports, reached independently.
- **Backtrack detection with severity.** `clens` (MIT) scores backtracks and
  "plan drift" — intended spec versus actual execution.
- **Turn-length trajectory within a thread.** Do your prompts get shorter as a
  thread proceeds (converging) or longer (re-specifying)? Pure feature data,
  already on the `Event`, no new ingest.

Conspicuously **not** on this list: anything deriving features from content
tokens. That is where names and identities live, and it stays absent until the
feature layer has its own PII scrub. `distinctive_tokens` is the canonical
example and is named-and-unbuilt on purpose.

---

## Adapters

- **claude.ai web export.** Named unbuilt in the README. The export format is
  stable and documented enough to read.
- **Forge's own records.** `forge-play/Forge`'s friction log, calibration ledger
  and checkpoint memory are process records of human+agent interaction — exactly
  this tool's subject matter. An adapter reading `~/.forge` is roughly 100 lines
  on the existing seam. Two constraints: route rows through
  `ingest/_rows.py::assemble` so the builder id is hashed like a filename (a
  `builder_id` is a name), and it is only in scope pointed at *your own* builder
  id. If those records carry no per-turn clock, the `cursor-store` precedent
  applies exactly — no tempo, said plainly, never imputed.
- **Agent-fleet corpora.** Named unbuilt. Note the scope problem first: a fleet's
  traffic is not one person's process, and the `subagents/` bug (BUGS.md) is what
  happens when the two get mixed by accident. A fleet adapter is a *different
  instrument* with a different subject, not a wider net for this one.

---

## Further out, and harder

### Bootstrap CIs / band-sensitivity on rates

Every headline number is a rate over a named denominator, reported to one
decimal place with no interval. On a small corpus that decimal is noise; the
renderer currently labels `n < 30` and says "read the direction, not the
decimal," which is honest but crude.

Bootstrap confidence intervals would replace a convention with a computation.
The reason it is not near-term: the classifiers' own error almost certainly
dominates the sampling error, so an interval computed from sampling alone would
*look* rigorous while understating the real uncertainty. That would be a worse
claim than the current one. Worth doing only alongside a measured estimate of
classifier error.

### A prose renderer

Named unbuilt. The markdown renderer now leads with a findings list, which was
most of the value. A genuine prose renderer — a paragraph a person reads rather
than a list — needs care that it never says more than the numbers support.

### The guardian-consent model (owner ≠ subject)

The biggest gap between this toolkit and any family-facing instrument, and the
reason pointing corpuslens at another person is out of scope by design. Not
solved, so not shipped. Solving it is a consent-and-ethics design problem first
and a code problem second; a pull request that adds person-targeting analysis
without it will be declined on those grounds, not on quality.

### Publish the wall as a reusable mechanism

A search of prior art (2026-09-11) found no open-source implementation of the
mechanism this project's Guard implements: relative time flowing freely to
analysis while the absolute anchor is quarantined behind a capability gate, with
a per-run plain-language disclosure of what was released.

The nearest precedent is **per-subject date shifting** from clinical
de-identification — PhysioNet's `deid` (GPLv2, so not vendorable here) assigns
each patient a hidden random offset and preserves intervals, which is the same
insight reached decades earlier in a different field. ARX (Apache-2.0) handles
dates as quasi-identifiers but has no relative-time model. Presidio (MIT) has a
date recognizer but ships no date-shift operator. Capability gating exists for
filesystem and network resources, not for fields in an analysis result. Nobody
emits the audit sentence.

If that holds, the Guard is the genuinely novel part of corpuslens and the
analyzers are the application. Extracting it as its own small library would be
more useful to more people than another analyzer here. It would also need to be
much more careful than it is today about what it promises, because a library
gets used by people who did not read `guard.py`.

**Prior-art citations worth keeping:** de Montjoye et al., *Unique in the Crowd*
(Sci Rep 2013) and *Unique in the shopping mall* (Science 2015); Mayer, Mutchler
& Mitchell, *Evaluating the privacy properties of telephone metadata* (PNAS
2016) — the actual paper behind the "Stanford MetaPhone" study.
