# NOTES — extending `label`/`score` to grade authorship

This branch (`claude/expand-authorship-score`) extends `corpuslens label` and
`corpuslens score` to grade the sibling `corpuslens/authorship.py` classifier
(contract: `HUMAN`/`AGENT`/`UNKNOWN`, `classify_turn(features,
marked_machine=False) -> str`), which **does not exist in this worktree yet**.
Per CONTRIBUTING.md ("change the claim in the same PR as the code"), README.md
and IDEAS.md should be updated once `corpuslens/authorship.py` lands for real
— this file is the doc diff that PR should carry, written now so it isn't
lost. I did not edit either file myself, per instructions.

## Why this doesn't fit the existing shape (context for the doc text below)

The four regex classifiers are each one yes/no question, graded with one
precision/recall pair. Authorship is a single classifier but **three-valued**
(human/agent/unknown), and UNKNOWN is the classifier declining to answer, not
a wrong guess — a classifier that says UNKNOWN on every turn must not look
like it has perfect precision. The scoring here handles that by treating each
class as its own one-vs-rest problem (true==C vs predicted==C): an
always-UNKNOWN classifier never predicts either class, so it shows **0%
recall on both** and "not computable" precision on both — the arithmetic
itself surfaces the uselessness, rather than a bolted-on special case. Each
class's false negatives are further split into `fn_wrong` (confidently
predicted the other class) and `fn_declined` (predicted unknown), because
those are different failure modes and the output must not let them collapse
into one indistinguishable number.

The ground truth question put to the labeller is binary and answerable on
their own corpus — "was this turn actually typed by a person, or did a
machine produce/relay it" — because the labeller witnessed it; it does not
ask them to guess at the classifier's own three-valued distinction.

## README.md — "Grading the classifiers against your own judgment"

Add a paragraph after the existing description of `label`/`score` (currently
ends "...It refuses the rest rather than guessing at their content shape."):

> `label` also asks one more question per eligible turn, independent of the
> four regex classifiers above: **"was this turn actually typed by a person,
> or did a machine produce or relay it"** — grading
> `corpuslens.authorship.classify_turn`'s three-valued HUMAN/AGENT/UNKNOWN
> judgment, tied to its own `AUTHORSHIP_VERSION` rather than the regex
> classifiers' `CLASSIFIER_SET_VERSION` (the two change on independent
> schedules, and a mismatch on either axis refuses rather than silently
> comparing). `score` then reports **precision and recall per class** (human,
> agent), not a single pair — a three-valued answer does not reduce to one —
> and reports how often the classifier **declined to answer** (UNKNOWN)
> alongside those numbers, because a classifier that always declines has
> perfect precision and is useless, and the report is built so that shows up
> rather than reads as a good score. If the authorship classifier is not
> installed, `label` skips its question and `score` skips its section; the
> four regex classifiers are unaffected either way.

## IDEAS.md — "A local labelling mode"

Add a dated note under the existing *Shipped 0.2.0* entry:

> *2026-09-11 (later the same day): extended to grade the authorship
> classifier (`corpuslens/authorship.py`) alongside the four regex
> classifiers — see the entry this displaces below, "Process when the work is
> delegated," for the question this closes part of.* Authorship did not fit
> the existing binary shape (one yes/no, one precision/recall pair): it is
> three-valued, and UNKNOWN needed to be scored as a decline rather than
> folded into "wrong" so that an always-UNKNOWN classifier reads as useless
> (0% recall, not 100%) rather than as flattering. The store gained a second,
> independent version axis (`authorship_version`, separate from
> `classifier_version`) rather than overloading the existing one, since the
> two classifiers change on different schedules. Persists nothing new: still
> only a label (now a string, "human"/"agent", not a bool — a three-valued
> judgment does not survive `bool()`), the opaque hash, and the two versions.

### A note for "Process when the work is delegated" (line ~551)

That entry asks whether a subagent's prompt is the operator's steering or the
machine's work, and says "probably a new `author_class`... but the question
belongs to this tool's subject matter." Worth a cross-reference once
authorship ships: the authorship classifier answers a related but distinct
question — not "whose steering is this" (an `author_class` question) but "did
a human being's fingers actually produce this specific turn" (an authorship
question) — and `marked_machine` in its contract is explicitly the corpus's
OWN `author_class` claim, passed in as a hint the classifier is free to
override. It is evidence toward answering the delegated-authorship question,
not a replacement for the stated model that entry says still needs deciding.

## What I built vs. what I stubbed

- Built for real: everything in `corpuslens/label.py` and `corpuslens/cli.py`
  under "authorship" — the store shape, the two version axes, the per-class
  scoring math (`_three_valued_scores`, `score_authorship`), the CLI wiring
  in `label`/`score`, and the rendering.
- Stubbed, in tests only (`tests/test_authorship_score.py`): a fake
  `corpuslens.authorship` module (`_make_stub`, `_always_unknown_stub`)
  installed via `sys.modules` for the duration of one test — a simple
  word-count/marked_machine rule, not a real classifier. This repo does not
  ship a stub `corpuslens/authorship.py`; the module is genuinely absent, and
  `corpuslens/label.py` imports it lazily (`authorship_contract()`) precisely
  so that absence never breaks the existing regex-classifier tests or the
  four-classifier `label`/`score` flows.
