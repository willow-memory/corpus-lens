# NOTES-authorship.md — doc changes this branch needs, not made here

Per the task's constraint, `README.md` and `IDEAS.md` were not edited on
`claude/expand-authorship`. This file says exactly what should change in each,
so a maintainer (or a follow-up PR) can apply it deliberately rather than
inherit it as an oversight.

## What landed

- `corpuslens/authorship.py` — `classify_turn(features, marked_machine=False)
  -> HUMAN | AGENT | UNKNOWN`. No content in, no content out; documented at
  length in its own module docstring (evidence, thresholds, what it is not).
- `corpuslens/analyze/authorship_mix.py` — registers the `authorship_mix`
  analyzer/claim: share of operator-role turns in each of the three classes.
- `model.PROCESS_CLAIM_TYPES` gained `"authorship_mix"`.
- `share.RATE_FIELDS` gained `human_pct` / `agent_pct` / `unknown_pct` (plain
  rates over `authorship_mix`'s own denominator, same status as
  `composition_mix`'s three `_pct` fields).
- `tests/test_authorship.py` — unit tests for `classify_turn` and the
  analyzer, the pinned-hash threshold-version-discipline tests, and
  `StylesCorpusFalsifierTests`, which runs the classifier over
  `examples/styles-corpus` (see below) through the real claude-code ingest
  path and asserts no human persona is ever classified AGENT.
- `examples/styles-corpus/` — cherry-picked from a sibling branch
  (`claude/expand-authorship-score`, commit `429187a`) rather than built here;
  see "Where the adversarial corpus came from" below.

## README.md

1. **"The battery (v0)" line** (currently lists six analyzers) should add the
   seventh:

   > The battery (v0): `steering_density`, `thread_shape`, `composition_mix`,
   > `clarification_pull`, `tempo`, `thread_span`, **`authorship_mix`** — each
   > with a named denominator...

2. **"Status: spine (0.2.0, on PyPI)"** (now presumably a later version per
   `CHANGELOG.md` — check before editing) says "six analyzers with
   per-analyzer semantic versions"; bump to seven.

3. **A new short subsection is worth adding**, near "Two things the
   claude-code adapter deliberately does not count as you" (the
   `subagents/`/`<task-notification>` passage) — this is the same finding
   generalized. Suggested placement: right after that passage, since it is
   the same shape of problem one layer up:

   > **A third thing worth checking: is the operator role even a person on
   > this corpus?** The two filters above assume everything left after they
   > run is a human — but pointed at SWE-agent trajectories, this tool once
   > reported 88.6% mid-task, a plausible-looking number describing an
   > automated dispatch loop, not a person. `corpuslens analyzers` now
   > includes `authorship_mix`, which classifies each operator-role turn as
   > HUMAN, AGENT, or UNKNOWN from process features alone (word count,
   > `code_ref`) — never content, never "which person", only "what kind of
   > thing". Its two thresholds rest on one operator's own corpus (human
   > turns 3-27 words; that operator's own agent-dispatch prompts 453-686)
   > and were checked, not just asserted, against a second, adversarial
   > corpus (`examples/styles-corpus/`) of six invented operators built
   > specifically to break them — a rambler, a numbered-spec writer, someone
   > who pastes tracebacks, a rapid questioner, a second-language speaker,
   > and the reverse case, a machine dispatching in five-word commands. No
   > human persona in that corpus is ever classified AGENT; the terse
   > machine persona is — accepted on purpose — mostly missed. See
   > `corpuslens/authorship.py`'s module docstring for the full account, and
   > its README-analog stated limits: **`UNKNOWN` is the default, not a
   > residual case**, and the adversarial corpus can falsify this classifier
   > but never validate it (everyone in it was imagined by one author).

4. **Honesty about the numbers** section could gain one sentence: the
   `authorship_mix` thresholds are the newest and least-tested numbers in the
   tool — checked against one real operator's own corpus and one synthetic
   adversarial corpus, never yet against a second *real* corpus of someone
   else's turns.

## IDEAS.md

1. **"Process when the work is delegated"** (Further out, and harder) is now
   partly addressed and should say so, without claiming the section is
   closed:

   - `authorship_mix` answers a narrower question than that section poses: it
     labels *whether* an operator-role turn was likely a person, not *how* to
     account for a person directing a director once delegation is confirmed
     (the section's "is a subagent prompt part of your steering, or the
     machine's work?" question is untouched — that is still a modeling choice
     nobody has made).
   - It deliberately does NOT introduce a new `AuthorClass` value, per the
     contract it was built against — it works entirely from `Event.features`
     plus a `marked_machine` bool, both already representable. The section's
     suggestion of "probably a new `author_class`" is still open; this module
     took the narrower, already-available-data path instead.
   - Worth a forward pointer: "`corpuslens/authorship.py` (added
     `authorship_mix`/0.x) answers a precondition question for this one —
     whether the operator role is a person at all — without resolving the
     deeper delegated-authorship modeling question this section poses."

2. **"Measuring the classifiers' own error"** (Stretch) is scoped to the four
   regex classifiers (`CODE_REF`, `AUTHORED`, `DELIB`, `CLARIFY`) via
   `corpuslens label`/`score`. `classify_turn` has exactly the same problem —
   its two thresholds were derived from n=18/n=16 and checked against a
   synthetic adversarial corpus that can falsify but not validate — and
   `label.py`'s `CLASSIFIERS_BY_AUTHOR`/`QUESTIONS` do not cover it. A real
   precision/recall number needs a human labelling their own turns "was this
   me or something I dispatched" the same way `label` already asks
   "did you author this code" — worth its own bullet under that heading, or
   a short addendum: extending `label`/`score` to grade `authorship_mix`
   against a real operator's own judgment is unbuilt.

3. Consider a one-line mention in **"A corpus with no clock is refused
   whole"** / the corpus-refusal section (if one exists under a different
   heading by the time this lands — the exact section named in the task
   brief was not found verbatim in this branch's `IDEAS.md`; the closest
   existing material is "Refuse a corpus the classifiers cannot read"): a
   corpus where `authorship_mix` reports a very high `agent_pct` might be a
   candidate for the same kind of refusal treatment `composition_mix` applies
   when its own classifiers go silent — not built here, since the contract
   was a classifier and one analyzer, not a refusal rule, but worth a
   pointer.

## Where the adversarial corpus came from

`examples/styles-corpus/` was not authored on this branch. Partway through
this work, a message (relayed from the orchestrating session, sourced from a
sibling agent working the same overall project under branch
`claude/expand-authorship-score`, commit `429187a`) reported that the
word-count evidence this classifier's thresholds rest on leaves a 426-word gap
with no data in it, and supplied a synthetic six-persona corpus built to
exploit exactly that gap. That commit shares this repository's base commit
with `claude/expand-authorship`, so it was cherry-picked onto this branch
rather than rebuilt, to keep its authorship and message intact.

**What it changed here:** nothing about the design, as it turned out. The
already-chosen conjunction rule (AGENT requires both `word_count >=
AGENT_MIN_WORDS` **and** `code_ref`, rather than a bare word-count cutoff) was
independently sufficient to pass the falsifier — none of the five human
personas reach 400 words, and the two personas whose short turns do carry
`code_ref` (`paster`, `spec_writer`) are correctly held to UNKNOWN rather than
asserted HUMAN or AGENT. What it added: the falsifier test itself
(`StylesCorpusFalsifierTests`, `tests/test_authorship.py`) and the expanded
module docstring section "CHECKED AGAINST A SECOND, ADVERSARIAL SOURCE" in
`corpuslens/authorship.py`, so this check is pinned in the suite going
forward rather than a one-time manual finding. Also fixed along the way:
`classify_turn({})` (a features dict missing `word_count` entirely, as
opposed to a genuine zero-length turn) now returns UNKNOWN rather than
silently defaulting the missing key to `0` and calling it HUMAN — a real
`Event.features` dict always carries `word_count`, so this only matters for a
malformed caller, but "missing evidence" and "evidence of zero" are different
claims and the code was conflating them.

**What it did not change:** the two threshold *values* (`HUMAN_MAX_WORDS =
30`, `AGENT_MIN_WORDS = 400`) are unchanged from the first draft. The
adversarial corpus is a falsifier, not a tuning set — per its own README, it
can show a defect but cannot certify an absence of one, since all six personas
were imagined by the same author whose blind spots it exists to expose. If it
had found a false AGENT on a human persona, the fix would have been to the
classifier's logic (very likely tightening the conjunction further, per the
coordinating message's suggestion that feature-based AGENT should be "very
hard to reach, possibly unreachable on word count alone"), not to the test or
the corpus.

## What I am least sure of, restated here for visibility

Same list as the module docstring's own admissions, gathered in one place:

1. **The word-count thresholds are two numbers from one operator's n=18/n=16
   sample**, now additionally checked against one synthetic adversarial
   corpus (which can only falsify, never validate). Neither is a population
   estimate. A second *real* corpus — anyone else's own turns plus their own
   agent-dispatch prompts — has not been run through this yet.
2. **`marked_machine` is currently always False in practice.** Every adapter
   in this registry that recognizes a deterministic machine marker
   (`isSidechain`, a compaction summary, an enumerated wrapper tag) drops
   that record before an `Event` exists, rather than keeping it and setting
   the flag. The parameter is real and tested directly
   (`classify_turn(..., marked_machine=True)` always returns AGENT), but no
   shipped code path exercises it end-to-end today.
3. **The terse-dispatcher blind spot is real and permanent under this
   feature set.** A machine that dispatches in short, code-free commands
   reads as HUMAN or UNKNOWN, never AGENT, unless `marked_machine` is wired
   up for it. This is the accepted cost of keeping the AGENT bar high enough
   to protect real people — not a bug to be quietly fixed by loosening the
   threshold, which would reopen the false-AGENT risk the whole design
   exists to close.
