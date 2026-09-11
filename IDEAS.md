# Ideas

Things worth building, with enough of the reasoning that a future reader can
disagree with it. Nothing here is a promise — the README's "named and
deliberately unbuilt" list is the short version, and this is the long one.

The rule that governs all of it: **a feature that cannot state its denominator,
or that would make the tool claim more than it can support, does not get built
here no matter how good the demo would look.**

Four sections are things to build. The last one, [Stretch](#stretch--capability-the-tool-should-have-with-no-good-read-yet),
is different: capability the tool arguably *ought* to have where nobody has
worked out yet whether it can be done honestly. Some of those entries will
probably end as documented refusals, and a refusal reached on purpose is a
result worth having.

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

These support the thesis that timing metadata alone re-identifies. They are
**not** the source of this project's own origin story: the custody schedule read
from keystroke timing is the author's own N=1 observation on a corpus of
thousands of sessions, and README and GRADING now say so rather than leaving it
in a passive voice that reads like a citation.

---

## Stretch — capability the tool should have, with no good read yet

Not a roadmap. Each of these is something corpuslens arguably *ought* to be able
to do, where nobody has yet worked out whether it can be done **honestly** —
within the wall, with a nameable denominator, without claiming more than the
data supports. They are written down so the question stays open rather than
getting answered by accident, one convenient commit at a time.

Each entry says what it would give, why there is no good read, and what would
have to be true before it could be attempted. Where a thing would require
breaking one of this project's rules, that is said outright; "we would have to
stop meaning it" is a legitimate finding and probably a refusal.

### Population reference points without pooling anyone's corpus

**What it would give.** The reference table is one verified N=1 plus two public
population aggregates from datasets nobody here belongs to. Every reading is
therefore "you versus one stranger and a crowd of strangers." Real reference
points — *people like you, doing work like yours* — would make every number in
the battery mean more.

**Why there is no read.** The tool's whole premise is that nothing leaves your
machine, and its own founding observation is that timing shape re-identifies a
person even with content stripped. So the obvious design — everyone uploads
their process metrics — is the one design this project exists to refuse. Rates
are aggregates, which feels safe, but a run also carries thread counts, day
spans, tempo quantiles and concurrency peaks, and that combination across a
small contributor pool is not obviously anonymous. We have not measured whether
it is.

**What would have to be true first.** A concrete re-identification analysis of
the *report* (not the corpus) at plausible cohort sizes. If that came back
survivable, a contribution format would have to be narrower than the report —
probably a handful of rates with coarsened denominators, no tempo quantiles at
all. Differential privacy is the obvious tool and is a real dependency, which
collides with stdlib-only. Most likely honest outcome: a documented refusal, or
a separate opt-in project that is not this one.

### Measuring the classifiers' own error

**What it would give.** Every headline percentage rests on four regex
classifiers, and the honest guidance is "trust direction plus your own
spot-check." Nobody knows their false-positive and false-negative rates on a
real corpus. Knowing them would turn several soft claims hard, and is the
precondition for confidence intervals meaning anything (see the argument against
bootstrap CIs above).

**Why there is no read.** Measuring requires a labelled sample of real operator
turns — which means a human reading their own content and judging it, turn by
turn. That is allowed (it is your own corpus, and content reaches the feature
layer at ingest already), but it cannot be automated without a model reading the
content, which would put a judgment nobody can audit inside the one place this
tool refuses to guess. And the labelling is tedious enough that it probably does
not happen.

**What would have to be true first.** A local labelling mode that shows you your
own turns, records only the label, and persists no content. Then a sample size
argument. Then the error rates published *per classifier and per corpus type*,
because the README already says the classifiers are weakest on mixed
personal-plus-coding corpora and that claim is itself unmeasured.

### Outcome-linked claims

**What it would give.** Everything the battery reports is descriptive: where
your intent arrives, who writes the code, how threads resume. The question
people actually want answered is comparative — does steering more mid-task
produce *better work*? Does deliberating first pay for itself? Without an
outcome variable, corpuslens can describe a process and never tell you whether
it is a good one.

**Why there is no read — and why this is the dangerous one.** An outcome
variable would have to come from outside the corpus: commits that survived,
tests that passed, revert rates, review outcomes. Some of that is reachable (the
repo is right there). But the moment a claim links process to quality, the claim
type changes shape: "this way of working produces better results" is a much
larger statement than "70% of your turns arrive mid-task", and the process-only
allowlist in `model.py` has nothing that represents it. It would also be an N=1
correlation over a corpus with no control, which is exactly the kind of finding
that reads as causal no matter how it is hedged.

**What would have to be true first.** A claim type that can carry an outcome
link without implying causation, and a denominator honest enough to make the
weakness visible in the number itself. If that cannot be designed, the right
answer is to refuse the feature rather than ship a hedged version of it — a
hedge in the docs does not survive the number being quoted.

### Metrics that stay comparable across tool versions

**What it would give.** `diff` makes trends possible. Multi-year trends are
where self-study actually pays off — but only if a number computed today means
the same thing as one computed two years ago.

**Why there is no read.** It already does not. `tempo` and `thread_span` did not
exist before 0.1.0. The injection filter has twice changed what counts as an
operator turn, both times correctly, and both times every rate downstream moved.
A user diffing across that boundary would see a process change that was really a
software change. The JSON carries `schema_version`, which covers the document
shape and says nothing about analyzer semantics.

**What would have to be true first.** Per-analyzer semantic versions, recorded
in the result, with `diff` refusing — or loudly annotating — a comparison across
a definition change. That is easy to state and tedious to maintain, and it only
works if every future change to a classifier or filter is correctly recognised
as a semantic change by the person making it.

### Process when the work is delegated

**What it would give.** The battery assumes one operator steering one machine.
That is already not how the work happens: this project's own session log had one
human thread and three subagent threads, and the adapter counted the model's
prompts to its own agents as the operator's until it was fixed
([BUGS.md](BUGS.md)). As delegation deepens, "where does your intent arrive"
gets harder to locate — your intent may arrive once, and be relayed four times.

**Why there is no read.** There is no settled definition of the operator's
process when the operator directs a director. Is a subagent prompt part of your
steering (you caused it) or the machine's work (you did not write it)? Both
answers are defensible and they produce different numbers from the same corpus.
Picking one silently is how the `subagents/` bug happened in the first place.

**What would have to be true first.** A stated model of delegated authorship,
probably a new `author_class` rather than a reuse of `AGENT`, and an explicit
decision about which questions in [GRADING.md](GRADING.md) still mean anything
when the work is nested. Likely a different instrument rather than more
analyzers here — but the question belongs to this tool's subject matter, so it
is listed rather than deferred.

### A lens that stays a lens

**What it would give.** Everything here is post-hoc: you read your logs after
the fact. A live signal — "you have been in a correction volley for forty
minutes" — would reach you while it still matters.

**Why there is no read.** That is not a lens, it is an intervention, and the two
have different ethics. An instrument that nudges is shaping the process it
claims to measure, and it can no longer honestly report on the thing it changed.
There is also a reflexivity problem the tool already has and has never
acknowledged: reading your own numbers changes your behaviour, so a corpus
measured after a first run is not the corpus of someone who never ran it. That
effect is presently unmeasured and unmentioned anywhere in the docs.

**What would have to be true first.** A decision about what corpuslens is for,
which is a values question rather than an engineering one. If the answer stays
"a lens", live feedback is a refusal and the reflexivity caveat should be
written into the README rather than left implicit. If the answer changes, that
is a different tool with a different name.

### Corpora that are not code

**What it would give.** The instruments generalise in principle: intent arrival,
deliberation, thread shape and tempo are not specific to programming. Writing,
research, and study sessions have the same shape and no equivalent tool.

**Why there is no read.** The classifiers are the problem. `CODE_REF` and
`AUTHORED` are the load-bearing half of `composition_mix` and mean nothing
outside a coding corpus, while the reference points are drawn from coding
populations. Running the current battery on a writing corpus would produce
numbers that look valid and are not — the worst failure mode this project has,
because nothing in the output would signal it.

**What would have to be true first.** Corpus-type detection honest enough to
refuse, so the tool says "these analyzers do not apply to this corpus" instead
of reporting 0.0% authored code for a novelist. That refusal is buildable today
and is arguably a near-term item; the analyzers that would *replace* them for
another domain are the stretch, and would need their own reference points
measured from scratch.
