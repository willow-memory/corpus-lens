# NOTES-subject.md

Doc changes this branch (`claude/expand-subject`) needs but does not make
itself, per instructions: it does not edit `README.md` or `IDEAS.md`. Written
so whoever merges this alongside `corpuslens/authorship.py` can fold both in
one pass instead of two.

## What this branch actually built

- `corpuslens/subject.py` — `infer_subject(results) -> (subject, reason)`.
  Derives one of `human` / `agent` / `mixed` / `unknown` from
  `results["authorship_mix"]`, never from a flag. Threshold: **0.80** of
  classified operator-role turns for a "predominant" call (`DOMINANT_FRAC`),
  and `unknown` outright if more than **0.50** of classified turns landed in
  the classifier's own `unknown` bucket (`MAX_UNCLASSIFIED_FRAC`), or if fewer
  than `SMALL_N` (30, the same convention `render.py`/`composition.py` already
  use) turns were classified at all. Both are round, disclosed conventions —
  same posture as `SMALL_N` itself — not a power analysis.
- `guard.AuditRecord` gained `subject`/`subject_reason` fields and a new
  clause in `sentence()`/`as_dict()` stating what the run BELIEVES the
  operator role is and that the belief can be wrong. `guard.py` does not
  import `corpuslens.subject` or `corpuslens.authorship` — it only carries
  and discloses whatever `cli.run()` sets.
- `cli.run()` calls `subject.infer_subject(results)` right after the analyzer
  loop and always sets `guard.audit.subject`/`.subject_reason` (never leaves
  it `None` on a real run).
- `render.py` gained the "subject lens" (`_apply_subject_lens`,
  `_depersonalize`, `_lens_active`), applied once in the `render()` dispatch
  function: whenever `audit.subject` is set and is not `"human"`, every
  analyzer's `headline`/`reading`/`vs_coding_population` text has
  `you`/`your`/`You`/`Your`/`YOU`/`YOUR` swapped for `the operator role`/
  `the operator role's` (etc.), every analyzer's `reference` block is deleted
  and replaced with a `reference_withheld` string naming why, and the two
  report-wide constants `RUBRIC_SCOPE_NOTE` and `CAVEAT` get the same pronoun
  swap. `markdown()`/`json_report()` called directly (bypassing `render()`)
  are unaffected — this project's own tests call them that way extensively,
  and the lens has nothing to correct without a subject to correct it toward.
- `model.PROCESS_CLAIM_TYPES` gained `"authorship_mix"` so the Guard will
  admit an analyzer declaring that claim once one is registered.
- Tests: `tests/test_subject.py`, `tests/test_subject_disclosure.py`,
  `tests/test_subject_integration.py` — all stub the shape of an
  `authorship_mix` result directly (see "The shape this branch assumed"
  below); none of them import or require `corpuslens.authorship`.

## The shape this branch assumed for `authorship_mix`'s result

Nothing pins this down elsewhere yet, so `corpuslens/subject.py`'s module
docstring states the assumption plainly and this note repeats it for
visibility. `infer_subject()` reads, from `results["authorship_mix"]`:

```
{"n": <int, classified operator-role turns>,
 "human_pct": <float 0-100>, "agent_pct": <float 0-100>, "unknown_pct": <float 0-100>}
```
(or `{"error": "..."}`, like every other analyzer here). **Reconcile this
against whatever `corpuslens/authorship.py`'s `authorship_mix` analyzer
actually returns when that branch lands** — if the field names differ,
`infer_subject()` silently reads zeros and calls everything `unknown`
(fails closed, not loudly) rather than crashing, which is the right
fail-closed default but means a naming mismatch would not announce itself
without running `tests/test_subject_integration.py` against the real
analyzer. Consider a follow-up: run `tests/test_subject_integration.py`'s scenarios
against the real `corpuslens.authorship` module (once it exists) instead of
only a hand-built stub, and/or have `infer_subject` assert the keys it needs
are present and correctly typed, so a naming mismatch fails loudly as a bug
rather than silently reading as `unknown`.

## A default worth flagging explicitly: "not registered" == `unknown`

Until `corpuslens/authorship.py` and its `authorship_mix` analyzer land,
`all_analyzers()` never includes `authorship_mix`, so **every real run's
subject is `unknown`** — not because a classifier looked and wasn't sure, but
because nothing looked at all. This branch treats that identically to "ran
but not enough evidence": pronouns drop to "the operator role" and every
reference point is withheld, even for the overwhelmingly common case (a solo
human running `corpuslens` on their own Claude Code logs).

This is a **deliberate, disclosed** choice, not an oversight: assuming
`human` by default when there is no evidence either way would be the exact
silent assumption this task exists to remove, merely moved one layer down.
The cost is real — until the classifier merges, the shipped report reads
noticeably more impersonal than 0.2.0's — and it is temporary by
construction: the moment `authorship_mix` is registered and correctly reads a
real human corpus as predominantly human, every headline's pronoun and every
reference point return automatically, with no further code change.

If whoever reviews this disagrees with that trade — e.g. wants "the analyzer
is not registered at all" to keep legacy `you`/`your` wording while only "ran,
but genuinely inconclusive" drops it — that is a small, localized change: give
`infer_subject()`'s first branch (`if not res:`) a distinct third state (e.g.
`SUBJECT_NOT_EVALUATED`) instead of folding it into `SUBJECT_UNKNOWN`, and
treat that state as inactive in `render._lens_active()`. Left as `unknown`
here on the reasoning above, but flagged because it is the single most
debatable call in this branch.

## Known, disclosed rough edge: verb agreement in a few `reading` strings

`render._depersonalize()` is a plain word substitution, not a parser: it does
not reconjugate the verb after a bare `you` used as a present-tense
grammatical subject. Every `your`/`You <past-tense-verb>` occurrence in this
codebase today reads correctly after the swap (English does not conjugate
possessives or past tense for person/number), but three `reading` strings use
present tense with a bare subject and read as mildly ungrammatical once
"you" becomes "the operator role":

- `composition.py`'s `composition_mix` reading: "you bring/direct/summon..."
  -> "the operator role bring/direct/summon..." (missing the third-person -s)
- `tempo.py`'s `tempo` reading: "you steer... you leave... and return"
  -> "the operator role steer... leave... and return"
- `tempo.py`'s `thread_span` reading: "you keep... and return to them"
  -> "the operator role keep... and return to them"

A stdlib-only tool has no parser to fix this generally, and a hand-maintained
phrase-override table would silently go stale the moment one of those
`reading` strings is edited without a matching table entry — worse than the
disclosed rough edge it would paper over. The trade made on purpose:
correctness of REFERENT (never claim a person wrote it) over polish of PROSE
(a mildly awkward but unambiguous sentence). If this is worth fixing
properly, the actual fix is rewording those three `reading` strings in
`composition.py`/`tempo.py` to avoid a bare present-tense "you VERB"
construction in the first place (the way `CAVEAT` was reworded in this
branch, "before you cite" -> "before citing them", to sidestep the exact same
problem) — not a smarter regex.

## README.md changes needed (not made here)

1. **"Honesty about the numbers"** section (currently: "The reference is one
   person...") needs a new paragraph after it, something like:

   > **The reference assumes a human.** Every reference point in the battery
   > — the measured N=1 director, WildChat, OASST — is a human corpus.
   > `corpuslens` now infers this run's SUBJECT (human / agent / mixed /
   > unknown) from an `authorship_mix` classifier over the operator role's own
   > turns, states its belief and its own fallibility in the audit sentence,
   > and drops the second-person wording and withholds every reference point
   > the moment that belief is not `human` — printing "your prompts" over a
   > SWE-agent trajectory would be a true statement about turns and a false
   > statement about a person. See `corpuslens/subject.py`.

2. **"Which of the ten questions this actually answers"** section: note that
   `authorship_mix` itself answers none of GRADING.md's ten numbered
   questions — it is a precondition for trusting the pronouns and reference
   points in the other sections, not a rubric answer of its own, the same
   status this section already gives `tempo`/`clarification_pull`.

3. **The battery list** ("The battery (v0): `steering_density`,
   `thread_shape`, `composition_mix`, `clarification_pull`, `tempo`,
   `thread_span`...") should add `authorship_mix` once
   `corpuslens/authorship.py` lands, with the same "reference points from
   measured N=1 + population aggregates" caveat qualified: those references
   do not apply to `authorship_mix` itself, and do not apply to ANY analyzer
   the moment `authorship_mix` says the subject is not human.

4. **Quickstart / adoption note**: worth one sentence warning that, until
   `authorship_mix` is registered, every run's subject reads `unknown` and the
   report is written impersonally by default (see "A default worth flagging
   explicitly" above) — otherwise a reader on this branch alone, before the
   classifier merges, will reasonably think something broke.

## IDEAS.md changes needed (not made here)

1. **"The harder finding: 'operator' was not a person, and nothing noticed"**
   (referenced in this task's prompt, not found verbatim in the current
   `IDEAS.md` — it may already have moved, or the phrasing may need to be
   added as its own entry) should be updated from a named problem to a
   **shipped** entry, in the same style as "A local labelling mode" or "Say
   whose corpus the reference is": what it gives (the subject inference, the
   pronoun/reference lens), why there was no read before now (nothing ever
   asked who filled the operator role), and what stays open (see "A default
   worth flagging explicitly" and "Known, disclosed rough edge" above — both
   are exactly the kind of thing this file already records rather than
   quietly fixing without a trace).

2. **"Process when the work is delegated"** (Stretch) is closely related but
   NOT the same question and should say so explicitly once this lands: that
   entry asks whether a subagent's prompt to itself counts as the operator's
   steering or the machine's own work — a question about attributing
   NESTED authorship within a single corpus. `authorship_mix`/`subject.py`
   answer a coarser, prior question — is the operator role, corpus-wide,
   filled by a human at all — and answering the coarse question does not
   resolve the nested one. Cross-reference the two entries.

3. New entry, or a note on an existing one, for the reconciliation task named
   above under "The shape this branch assumed": once `corpuslens/authorship.py`
   lands, `corpuslens/subject.py`'s assumed result shape
   (`n`/`human_pct`/`agent_pct`/`unknown_pct`) needs to be checked against
   the real analyzer's actual output and reconciled if they differ.
