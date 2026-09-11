"""corpuslens.authorship — is an operator-role turn HUMAN, AGENT, or UNKNOWN?

WHAT THIS IS NOT. This classifies WHAT KIND OF THING authored a turn — never
WHICH human. It is not, and must never become, person attribution: there is no
path from here to "this is Alice's turn" or "this is not the account owner". A
turn that is not the account owner typing is scoped here as AGENT (a machine
process occupying the operator role), full stop — not routed toward identifying
who else it might be. Adding any such path would be the exact `life_partition`
kind of claim `model.py` keeps behind the capability gate, and this module
must stay out of that territory by construction, not by discipline alone: it
takes no name, no timestamp, no content, nothing but the same process features
`classifiers.py` already exposes everywhere else in this project.

WHY THIS EXISTS. corpuslens measures whatever occupies the operator role and
calls it "you". Pointed at SWE-agent trajectories it reported 88.6% mid-task —
a plausible-looking number describing an automated dispatch loop, not a
person. `steering_density`, `composition_mix` and every other analyzer that
reads AuthorClass.OPERATOR silently assume a human sits there. This module
lets a caller check that assumption on the corpus in front of it instead of
inheriting it.

NO CONTENT, EVER. `classify_turn` receives an `Event.features` dict — the same
booleans/counts every other analyzer in this project reasons about
(`word_count`, `char_count`, `code_ref`, `code_authored`, `delib`, `question`,
`injected_stripped`) — and nothing else. Do not add a token-level feature to
this module or to the dict it reads: `distinctive_tokens` is named-and-unbuilt
in the README precisely because that is where names and identities live, and
adding it here to sharpen this classifier would smuggle back in through the
one door this project has deliberately kept shut.

THE ONE RULE: IT MUST UNDERCOUNT. `UNKNOWN` is the return value absent
evidence, not a residual case reached only when both other branches fail to
match by accident — it is the code's actual default. A turn earns HUMAN or
AGENT only when its features clear a bar for that class, and the AGENT bar is
deliberately the higher of the two: a false AGENT on a real person is the
worst error this module can make (it erases a person from their own process
report), while a false HUMAN on an agent turn just re-inherits the status quo
bias this module exists to correct. Absent evidence, this module would rather
say "unknown" a hundred times than say "agent" once on a person.

THE EVIDENCE, STATED PLAINLY (measured once, on one operator's own corpus,
2026-09-11 — see NOTES-authorship.md for where to re-derive it). Comparing
that operator's own typed turns against the agent-dispatch prompts sent from
the same session:

    class    n    median words   min words   max words   code_ref
    human    18   9              3           27          0.0%
    agent    16   550            453         686         100.0%

Perfect separation exists at ANY word-count cutoff between 27 and 453 in this
one sample. **That gap is a single operator's verbose agent-dispatch style on
n<20 per side — the weakest part of this whole feature.** It is not a law of
nature: a terse dispatcher issuing short agent prompts, or a human pasting a
long brief (a spec, a stack trace, a design doc) into a real conversation,
collapses the gap from either side. The thresholds below are deliberately
picked with wide margins off the observed floor/ceiling BECAUSE of that
fragility, and AGENT additionally requires a second, independent signal
(`code_ref`) rather than word count alone — precisely so a long, code-free
human message (the "pasting a long brief" collapse case named above) lands in
UNKNOWN rather than AGENT. It still cannot be shown to generalize past this
one operator's dispatch style, and nobody should cite it as more than that
until it is re-measured on a second corpus (see NOTES-authorship.md).

CHECKED AGAINST A SECOND, ADVERSARIAL SOURCE — `examples/styles-corpus/`, six
invented operators written specifically to break the reasoning above rather
than confirm it: a rambler (turns up to 112 words), a numbered-spec writer (up
to 119 words), someone who pastes tracebacks and short code (code_ref true at
word counts as low as 21), a rapid one-line questioner, a second-language
speaker, and the reverse case — a machine that dispatches in five-word
commands (`terse_dispatcher`, true author AGENT, 3-7 words a turn). That
corpus's own README states plainly what it can and cannot show: it can
FALSIFY (calling one of the five human personas AGENT would be a real defect,
because people who write like that exist) and it CANNOT VALIDATE (every
persona was imagined by one author, whose blind spots it exists to expose —
passing it is not a measured error rate). `tests/test_authorship.py`'s
`StylesCorpusFalsifierTests` runs exactly that check, over real `Event`
objects produced by the actual claude-code ingest path, and it currently
holds: no human persona in that corpus is ever classified AGENT, because the
`AGENT_MIN_WORDS`-and-`code_ref` conjunction rejects every one of them (the
longest, most code-heavy human turns in that corpus — 119 words, or 25 words
with `code_ref` true — clear neither bar on their own). The cost of that
conjunction is paid on the other side and is accepted on purpose:
`terse_dispatcher`'s real machine turns are never classified AGENT either
(most read HUMAN, a few read UNKNOWN) — this feature set cannot see a machine
that dispatches as tersely as a person types, and a marked-machine signal
(the `marked_machine` parameter) is the only thing that could catch it. That
is this design choosing, deliberately, to under-catch AGENT rather than
risk over-catching it on a real person — see "THE ONE RULE" above.

THRESHOLDS.

  * `HUMAN_MAX_WORDS = 30` — the human sample's observed max was 27 words; 30
    gives a 3-word margin so the classifier is not tuned to reject the exact
    corpus it was measured on. Chosen close to the floor of the gap (27) is
    deliberate: HUMAN gets the lower, more permissive bar per the rule above.
  * `AGENT_MIN_WORDS = 400` — the agent sample's observed min was 453 words;
    400 sits ~50 words below that floor, so a slightly terser dispatch prompt
    than any observed still clears it. This is the ONLY word-count number in
    this module set close to its evidence edge, and it is not suffient by
    itself — see the next point.
  * AGENT requires `word_count >= AGENT_MIN_WORDS` **and** `code_ref` true —
    both, not either. The agent sample was 100% code_ref; requiring it as a
    second, structurally different signal (not just a bigger word-count
    cutoff) is what keeps a long code-free human paste out of AGENT. This
    conjunction is a design choice this module makes BEYOND what the raw
    numbers alone would justify, in the undercounting direction on purpose.
  * HUMAN requires `word_count <= HUMAN_MAX_WORDS` **and** `not code_ref` —
    matching the human sample's own 0.0% code_ref exactly, so a short message
    that happens to reference code (plausible for a real person: "fix
    foo.py") is denied HUMAN and falls to UNKNOWN rather than being asserted
    either way.
  * Everything between the two word-count bands, and every combination that
    does not satisfy one side's conjunction, is UNKNOWN. This includes the
    exact case IDEAS.md's evidence note warns about — a terse dispatch prompt
    with no `code_ref`, or a long human message with no `code_ref` — both
    ambiguous under this feature set, and both correctly refuse to guess.

CHANGING A THRESHOLD IS A SEMANTIC CHANGE, exactly as for the regex
classifiers in `classifiers.py`. `AUTHORSHIP_VERSION` below tags this
module's semantics as a whole (`corpuslens.analyze.authorship_mix` pins a
`semantic_hash` over these same threshold literals, per
`corpuslens/analyze/__init__.py`); moving either threshold requires bumping
both `AUTHORSHIP_VERSION` and the analyzer's own `version`/`semantic_hash`, on
purpose, so a quiet threshold edit cannot silently move every downstream
number the way an un-versioned regex edit could.
"""
from __future__ import annotations

HUMAN = "human"
AGENT = "agent"
UNKNOWN = "unknown"

#: Tags the semantics of `classify_turn` as a whole (both thresholds below,
#: and the marked-machine short-circuit). Bump this, and re-derive
#: `corpuslens.analyze.authorship_mix`'s pinned `semantic_hash`, any time
#: either threshold moves or the branch logic changes what a HUMAN/AGENT/
#: UNKNOWN return means — see the module docstring above and
#: `corpuslens/analyze/__init__.py` on why a version nobody bumps is worse
#: than none.
AUTHORSHIP_VERSION = "authorship/1"

#: See "THRESHOLDS" in the module docstring for where each number comes from.
HUMAN_MAX_WORDS = 30
AGENT_MIN_WORDS = 400


def classify_turn(features: dict, marked_machine: bool = False) -> str:
    """Return HUMAN, AGENT or UNKNOWN for one operator-role turn.

    `features` is an `Event.features` dict — process-derived booleans and
    counts only (`word_count`, `char_count`, `code_ref`, `code_authored`,
    `delib`, `question`, `injected_stripped`); no content is passed in and
    none may be added to this function's inputs (see the module docstring).

    `marked_machine` is True when ingest already identified this turn by a
    DETERMINISTIC marker — an enumerated wrapper tag (`ingest/injection.py`),
    `isSidechain`, or a compaction summary — rather than by these heuristic
    thresholds. A marked turn is AGENT with certainty: ingest is not guessing
    there, it read the runtime's own marking of its own traffic, which is
    strictly stronger evidence than anything word-count-shaped below. This
    function still takes the flag explicitly (rather than assuming the caller
    pre-filters) so a marked turn's certainty is visible at the one place that
    turns evidence into a label, not buried in a filter upstream. As of this
    version, no shipped adapter actually sets this for a surviving event — the
    claude-code adapter DROPS sidechain/compaction/whole-turn-machine records
    before an Event exists at all (see `ingest/claude_code.py`), so they never
    reach this function today. The parameter exists for the adapters and
    ingest paths that do not drop them, and callers should not assume it is
    exercised by the current default registry — see NOTES-authorship.md.

    This function classifies what kind of thing authored a turn. It is never
    "which human", and adding any feature that could answer that question
    (a name, a token, a fingerprint) does not belong here or anywhere behind
    this signature — see the module docstring's "WHAT THIS IS NOT".
    """
    if marked_machine:
        return AGENT

    word_count = features.get("word_count")
    if word_count is None:
        # No evidence at all (not even a word count) is not the same as a
        # genuine zero-length turn — treat a missing feature as no evidence,
        # never as evidence of anything. UNKNOWN is the only honest answer.
        return UNKNOWN
    code_ref = bool(features.get("code_ref"))

    if word_count >= AGENT_MIN_WORDS and code_ref:
        return AGENT
    if word_count <= HUMAN_MAX_WORDS and not code_ref:
        return HUMAN
    return UNKNOWN
