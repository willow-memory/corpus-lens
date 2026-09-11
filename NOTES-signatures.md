# NOTES — `signature_plurality` (operator-role authoring signatures)

This branch (`claude/expand-signatures`) adds one analyzer,
`corpuslens/analyze/signatures.py` (`signature_plurality`, claim type
`authoring_plurality`), plus a placeholder `corpuslens/authorship.py`. The task
that produced this branch asked for `README.md` and `IDEAS.md` not to be
edited directly; this file is the diff those two documents need, written out
so a maintainer can apply it (or reject parts of it) deliberately.

## Why a notes file instead of editing README/IDEAS directly

Per the task boundary: this feature sits on the same ethical line the whole
project is built around (owner == subject; process claims only), and the
instructions for it were explicit that the documentation changes should be
reviewable rather than silently folded into the wall's own founding documents
in the same pass that built the feature.

## `corpuslens/authorship.py` — status, for whoever reads this next

**This file does not exist for real yet.** A sibling deliverable defines its
contract (`HUMAN`, `AGENT`, `UNKNOWN`, `AUTHORSHIP_VERSION`,
`classify_turn(features, marked_machine=False) -> str`) and is responsible for
building it — this branch does not rebuild it. `corpuslens/analyze/signatures.py`
imports it defensively (`try`/`except ImportError`) and falls back to a
minimal, deliberately under-confident stand-in (leans `UNKNOWN`, never
`HUMAN`, on any input) purely so this branch's own tests can run standalone.
**Do not ship the fallback as the real classifier.** When the real
`authorship.py` lands, delete nothing from `signatures.py` — the `try` import
should simply stop taking the `except` path.

## README.md — suggested changes

1. **The battery list** (currently: "The battery (v0): `steering_density`,
   `thread_shape`, `composition_mix`, `clarification_pull`, `tempo`,
   `thread_span`") needs `signature_plurality` appended, and the sentence
   after it ("each with a named denominator, dropped-event counts reported...")
   still holds, so no other wording there needs to change.

2. **"Status: spine" section** — "six adapters ... six analyzers with
   per-analyzer semantic versions" becomes seven analyzers. (`render.py`'s
   `RUBRIC_SCOPE_NOTE` has already been updated in this branch to say "three
   of the battery's seven analyzers... answer none of the ten numbered
   questions" — the corresponding prose in README's own "Which of the ten
   questions this actually answers" section, currently "two of its six
   analyzers answer none," needs the same correction so the two documents
   don't disagree.)

3. **A new subsection is worth adding**, parallel in spirit to "Sharing a
   reading without the fingerprint" — something like:

   > ### Is your operator role one signature or several?
   >
   > `signature_plurality` counts distinct authoring signatures among
   > operator-role turns — useful when a corpus might be one human plus an
   > orchestrating agent, or several automations writing into the same role,
   > rather than one person alone. It reports an **opaque count** and each
   > signature's **share of turns and typical length band** — nothing that
   > maps a signature back to a specific turn, thread, or time, and no label
   > beyond an index.
   >
   > **What it will not do, on purpose:** it will never tell you that a
   > corpus contains more than one *human*. Turns the (separately shipped)
   > authorship classifier calls human-authored are always reported as one
   > signature, however much they vary — this project's scope rule is
   > owner == subject, and an analyzer that could distinguish two people
   > would be the guardian-consent tool IDEAS.md names as deliberately
   > unbuilt, arrived at sideways. Splitting is refused there categorically;
   > only the machine-classified share of the corpus may ever split into more
   > than one signature, and only by a coarse length band, never by content
   > or by timing. Below the small-sample floor (30 turns, same convention as
   > everywhere else in this tool), or when the classifier could not
   > confidently label anything, it refuses rather than report a count.
   >
   > Share mode (`--share`) drops this analyzer's count and shape fields
   > entirely, the same way it drops thread counts and tempo quantiles — a
   > signature count is a shape statistic, not a plain rate, and share mode's
   > allowlist excludes anything not explicitly reviewed onto it.

4. **The "Named and deliberately unbuilt" list** should note that the
   authorship classifier itself (`authorship.py`) is, like the four regex
   classifiers, an unmeasured heuristic — nobody has run a `label`/`score`
   equivalent against it yet. Worth a line there rather than letting a reader
   assume it is any more validated than `CODE_REF`/`AUTHORED`/etc.

## IDEAS.md — suggested changes

1. **"Say which rubric question each analyzer answers"** currently says "two
   of the six analyzers answer **none** of the numbered questions." That is
   now three of seven (`signature_plurality` joins `tempo` and
   `clarification_pull`). Small, but IDEAS.md's own credibility rests on
   numbers like this staying current.

2. **"Process when the work is delegated"** should get a follow-up note: this
   branch answers a narrower question than the one that section poses. It
   never assigns intent, never decides whether a subagent's prompt is "your"
   steering or the machine's own work (the open question that section names),
   and does not touch `steering_density`, `composition_mix`, or any other
   existing analyzer's counting rules. It only adds a new, independent
   number — how many distinct signatures the operator role shows — and that
   number should not be read as progress toward "a stated model of delegated
   authorship." The delegated-authorship question stays exactly as open as it
   was.

3. **"The guardian-consent model (owner ≠ subject)"** is worth a one-line
   cross-reference: a request that could plausibly have drifted into that
   territory ("tell me which agent or person wrote which turn") arrived and
   was built in its narrowest defensible form instead — an opaque count with
   no attribution, no ordering, and a structural inability to split
   human-classified turns. That is not progress toward guardian-consent
   (a different consent object entirely, per the README) and should not be
   cited as if it were.

4. **A refusal worth recording explicitly, so nobody re-attempts it as an
   improvement:** clustering operator-role turns by *timing* (inter-turn
   deltas, burst shape) in addition to length was considered, for
   `signature_plurality`, and rejected. Relative time is safe to *emit*
   (that's the whole point of the wall), but *clustering by it* is the exact
   move GRADING.md question 9 and the README's founding observation warn
   about — a timing signature is what re-identified a person from a corpus
   with no content read at all. Using it here, even only to separate two
   machines, would exercise that capability rather than merely disclose it.
   If a future contributor wants to add timing-based splitting to this
   analyzer, that is the objection they need to answer first, not a detail
   they can quietly improve past.

5. **New unmeasured-heuristic entry, alongside the existing "classifiers are
   regex heuristics" caveat:** `corpuslens/authorship.py`'s `classify_turn` is
   also an unmeasured heuristic once it lands for real. `label`/`score`
   currently grade `CODE_REF`/`AUTHORED`/`DELIB`/`CLARIFY` against the
   owner's own judgment; extending that to `classify_turn` (a fifth
   classifier to hand-label) is a small, clearly-scoped Near item once the
   real `authorship.py` exists, and would let `signature_plurality`'s count
   be graded rather than merely trusted.
