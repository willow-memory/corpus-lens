# Notes for the README/IDEAS merge (rubric mapping + whose corpus)

Branch `claude/expand-rubric`. I did not edit `README.md` or `IDEAS.md` per
instructions (parallel agents). This is the exact set of sentences that need
to change once this branch lands, quoted old → new, so whoever reconciles the
docs doesn't have to re-derive it.

## What this branch built, in one paragraph

Every registered `Analyzer` now carries a required `grading_question: str`
(`corpuslens/analyze/__init__.py`; `register()` raises `ValueError` if it is
blank, the same discipline as `denominator`). Each of the six analyzers
declares one, checked against GRADING.md's actual wording rather than assumed
from the analyzer's name — see the per-analyzer mapping and how it was
checked in my final report to the orchestrator, and inline in each
`@register(...)` call. `cli.py` merges `grading_question` into every result
dict (`run`) and into the `analyzers` listing. `render.py` prints it under
each section's headline (and in the not-computable branch), and prints a new
`RUBRIC_SCOPE_NOTE` once, right after the audit sentence. A review pass caught
the first draft of that note overclaiming — it opened "this report's battery
answers GRADING.md's first four questions", which reads stronger than the
per-section mapping underneath it (question 1 and 2 in full, 3 and 4 only
partly, two analyzers answering none). Reworded to lead with the true shape
— fully answers two, partly answers two more, two analyzers answer none and
are reported as supporting signal — before naming questions 5-8 and 9-10 as
not corpus-measurable at all.

Separately, `render.py._section()` now renders each analyzer's `reference`
dict in prose (previously it only appeared inside the raw JSON dump): rows
naming a public population aggregate (WildChat, OASST, SWE-bench/tau-bench —
matched by substring, so this doesn't need to know analyzer names) print as
given; every other row — `measured_director`, `measured_director_n1`,
`measured_cli`, `measured_cursor_note`, all of which are the same one
person's corpus — gets "— the author's own corpus (N=1); a gap from this
reference is a gap from one person, not a population." appended, plus one
sentence (once per section, not once per row) pointing at `corpuslens label`
+ `corpuslens score` as the way to find out how much of that gap is the
operator and how much is the classifier's own error. `reference` and
`grading_question` were added to `_SHOWN` so they don't ALSO get dumped
verbatim in the JSON code block under the section (same treatment as
`headline`/`reading`); the JSON renderer (`--format json`) is untouched and
still carries both fields verbatim, so no `SCHEMA_VERSION` bump — the
envelope's keys (`schema_version`/`audit`/`results`/`caveat`) didn't change,
only fields inside individual analyzer results, which already vary by
analyzer.

`examples/EXAMPLE.md` is updated to stay byte-for-byte accurate (its "## The
whole report" section is a literal paste of `corpuslens run
examples/sample-corpus --adapter claude-code`, which now includes the rubric
scope note) and its annotated per-analyzer sections gained a one-line
GRADING.md mapping note and, where relevant, a note on the N=1 labelling.

14 new tests in `tests/test_render.py` (`RubricScopeTests`,
`ReferenceProvenanceTests`) plus 3 in `tests/test_cli_surface.py`. Full suite:
302 tests, all passing.

## README.md

**"Status: spine" section, the battery description.** No sentence describes
per-analyzer rubric mapping today, so nothing to correct — this is a new
claim, not a fix to an old one. Suggest adding one sentence to the paragraph
that lists the battery:

Old:
> The battery (v0): `steering_density`, `thread_shape`, `composition_mix`,
> `clarification_pull`, `tempo`, `thread_span` — each with a named denominator,
> dropped-event counts reported (never hidden), and reference points from one
> measured N=1 operator corpus plus WildChat/OASST population aggregates.

New (one clause added, nothing removed):
> The battery (v0): `steering_density`, `thread_shape`, `composition_mix`,
> `clarification_pull`, `tempo`, `thread_span` — each with a named denominator,
> dropped-event counts reported (never hidden), a declared mapping to the
> question of [GRADING.md](GRADING.md) it answers (in full, or named "part
> of" when it only partly does — two of the six answer none of the ten
> numbered questions directly, and say so), and reference points from one
> measured N=1 operator corpus plus WildChat/OASST population aggregates.

**"The rubric this instruments" line**, near the top:

Old:
> The rubric this instruments: [GRADING.md](GRADING.md)
> (ten questions to grade your own system).

New (state the scope up front, matching what the report itself now says —
and matching it precisely: an earlier draft of this note said "answers the
first four, in full or in part," which a review correctly flagged as
stronger than the truth, since two of the four are only partly answered and
two of the six analyzers answer none of the ten directly):
> The rubric this instruments: [GRADING.md](GRADING.md) (ten questions to
> grade your own system) — this tool's battery fully answers two of the ten,
> partly answers two more, and two of its six analyzers answer none of the
> ten numbered questions directly (reported as supporting signal instead);
> questions 5-8 (a system's honesty machinery) and 9-10 (fingerprinting,
> continuity) are not corpus-measurable from session logs at all. The
> rendered report says all of this plainly rather than leaving the other six
> questions as an implied promise.

**"Honesty about the numbers" section** — the N=1 caveat already exists here
in general form but doesn't mention that the *rendered report* now repeats it
beside every comparison. Consider appending one sentence:

Old:
> The classifiers are regex heuristics: trust direction plus your own
> spot-check, never raw percentages. The reference N=1 was verified by
> re-derivation from raw and corrected five times in one session — the
> reference table inherits those corrections, not the first drafts.

New:
> The classifiers are regex heuristics: trust direction plus your own
> spot-check, never raw percentages. The reference N=1 was verified by
> re-derivation from raw and corrected five times in one session — the
> reference table inherits those corrections, not the first drafts. The
> rendered report says this beside every N=1 comparison, not just here: each
> such reference row is labelled "the author's own corpus (N=1)", kept
> visibly distinct from the named WildChat/OASST population rows, with a
> pointer to `corpuslens label` + `corpuslens score` as the way to find out
> how much of any gap is the operator and how much is the classifier.

## IDEAS.md

Both entries under "Near" describe exactly what got built; mark them done
rather than leaving them as open ideas, and correct one implementation detail
each so the entry matches the shipped shape.

**"### Say which rubric question each analyzer answers"**

Old:
> [GRADING.md](GRADING.md) poses ten questions; the battery instruments the first
> four. Questions 5–8 are about a system's honesty machinery and 9–10 about
> continuity — mostly not derivable from session logs at all.
>
> The report could name the question each section answers, and state plainly that
> the rest are not corpus-measurable. That stops the rubric reading like a promise
> the tool did not keep, and costs almost nothing.

New (mark built, and correct "the battery instruments the first four" — two
of the six analyzers, `tempo` and `clarification_pull`, checked against
GRADING.md's actual wording, answer none of the ten numbered questions
directly; only four of the six do, and two of those four only partly):

> **Built.** [GRADING.md](GRADING.md) poses ten questions; checked one by one
> against each analyzer's actual filter, four of the six analyzers answer one
> of the first four (`steering_density` → question 1; `composition_mix` →
> question 2 in full, part of question 3; `thread_shape` and `thread_span` →
> part of question 4 each), and two (`tempo`, `clarification_pull`) answer
> none of the ten numbered questions directly — despite `clarification_pull`'s
> name suggesting question 3, it measures the machine asking and the operator
> answering, the reverse of what question 3 poses, and says so rather than
> claiming the number. Every `Analyzer` declares this via a required
> `grading_question` field (`corpuslens/analyze/__init__.py`); the rendered
> report shows it per section and states once, up front, that questions 5-8
> and 9-10 are not corpus-measurable at all — naming which those are.

**"### Say whose corpus the reference is"**

Old:
> Every reading in the report is "you versus the measured director", and the
> measured director is the author. The analyzers label it `measured_director_n1`
> and GRADING.md says "one measured operator", which is honest, but a reader
> skimming the findings list sees a percentage beside a reference and reads a
> population. Cheap fix: the reference rows say "the author's own corpus (N=1)"
> in the rendered report, and the reading sentence for each analyzer says that a
> gap from it is a gap from one person. The population aggregates keep their
> names. This is a wording change, and it belongs with the labelling mode above,
> because until the classifiers' error is measured nobody can say how much of
> that gap is the operator and how much is the regex.

New (mark built; note the key spelling is not actually uniform across
analyzers, which the fix had to account for):

> **Built.** Every reading in the report is "you versus the measured
> director", and the measured director is the author — but the key spelling
> varies (`measured_director`, `measured_director_n1`, `measured_cli`,
> `measured_cursor_note`), so the fix detects the population aggregates by
> name (WildChat, OASST, SWE-bench/tau-bench) instead of hard-coding the N=1
> key. Every reference row not naming one of those now reads "— the author's
> own corpus (N=1); a gap from this reference is a gap from one person, not a
> population." in the rendered report, and one sentence per section (not per
> row) points at `corpuslens label` + `corpuslens score` — built and shipped
> since this entry was written — as the way to learn how much of a gap is the
> operator and how much is the regex. The population aggregates keep their
> names and are never relabelled.

## Decisions confirmed by review (2026-09-11)

The coordinator checked every per-analyzer mapping against GRADING.md's own
wording independently and confirmed all six hold as declared, including that
`tempo` and `clarification_pull` answering **none** of the ten numbered
questions is correct as-is — forcing either onto a number would be exactly
the small overclaim this project exists not to make, so that stays.

Two implementation calls were explicitly endorsed and are recorded here
rather than left implicit in the diff:

- **Not renaming the reference-dict keys** (`measured_director` in
  `steering.py` vs `measured_director_n1` in `composition.py` vs
  `measured_cli`/`measured_cursor_note` in `clarification_pull`) — a
  consumer-visible schema change, out of scope for a wording pass. The N=1
  labelling in the renderer detects population aggregates by name instead of
  requiring a canonical individual-corpus key, so the inconsistency needed no
  fix to be handled correctly.
- **Keeping `RUBRIC_SCOPE_NOTE` out of the JSON envelope** — no
  `SCHEMA_VERSION` bump needed, since the envelope's keys
  (`schema_version`/`audit`/`results`/`caveat`) didn't change.

One correction came out of that same review: `RUBRIC_SCOPE_NOTE`'s first
draft opened "this report's battery answers GRADING.md's first four
questions," which is stronger than what the per-section declarations under it
actually say (two full, two partial, two analyzers answering none) — a
summary must never promise more than the detail under it delivers, which is
this project's one rule applied to the note's own placement, not just its
content. Reworded (see `render.py::RUBRIC_SCOPE_NOTE` and the corresponding
block in `examples/EXAMPLE.md`) to lead with the true shape before naming
questions 5-8 and 9-10 as out of scope. The README suggestion above was
updated to match, since it had inherited the same overclaim from the first
draft.

## What I deliberately did not touch

- `GRADING.md` itself — the task was to make the *report* honest about the
  rubric, not to edit the rubric.
- The `reference` dict *keys* inside the analyzers — see "Decisions confirmed
  by review" above.
- `fingerprint.py` / `timing_fingerprint()` — already cites GRADING.md
  question 9 in its own docstring and is deliberately not a registered
  analyzer (see its module docstring), so it never reaches
  `all_analyzers()` and has no `grading_question` to declare.
