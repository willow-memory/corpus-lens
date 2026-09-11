"""corpuslens.subject — derives this run's SUBJECT from the authorship mix.

THE PROBLEM THIS EXISTS TO FIX. Every headline in the battery is worded in
the second person ("88.6% of your prompt turns arrive mid-task"), and every
analyzer's reference table compares the reader to `measured_director` — a
human's own corpus. That is a true statement about turns and a false
statement about a person the moment the corpus's OPERATOR ROLE is filled by
something other than a human — a SWE-agent trajectory, a fleet's own
traffic, a benchmark harness. Nothing upstream of this module ever asked.

THE CONTRACT THIS CONSUMES, NOT BUILDS. `corpuslens/authorship.py` (per the
project's own design notes) defines `HUMAN`/`AGENT`/`UNKNOWN`,
`AUTHORSHIP_VERSION`, and `classify_turn(features, marked_machine=False)`,
and registers an `authorship_mix` analyzer reporting the share of
OPERATOR-ROLE turns in each class. That module and analyzer may not exist in
this build — this module never imports `corpuslens.authorship` and never
classifies a single turn itself. It only reads whatever shape
`results.get("authorship_mix")` already has, exactly the way `render.py`
already reads any other analyzer's result dict without knowing which
analyzer produced it.

THE SHAPE THIS MODULE EXPECTS from that analyzer's result dict, when it did
run and did not error (documented here because nothing else in this
worktree pins it down — see NOTES-subject.md for what to reconcile once
`corpuslens/authorship.py` lands):
    n            -- int, total operator-role turns actually classified
    human_pct    -- float, 0-100, share of those n classified authorship.HUMAN
    agent_pct    -- float, 0-100, share classified authorship.AGENT
    unknown_pct  -- float, 0-100, share classified authorship.UNKNOWN
(human_pct + agent_pct + unknown_pct should sum to ~100.0 of `n`.) An
analyzer that could not compute returns `{"error": "..."}` like every other
analyzer here, and this module treats that identically to the analyzer not
existing at all: not enough evidence, never a guess.

WHAT THIS MODULE NEVER DOES: it never claims a corpus IS human or agent. It
reports what corpuslens BELIEVES, from a classifier that can be wrong, and
"not enough evidence" is `unknown`, never a coin flip resolved in either
direction. See `guard.AuditRecord.sentence()` for where that belief — and
its own fallibility — gets said out loud to the reader.
"""
from __future__ import annotations

from .analyze import SMALL_N

SUBJECT_HUMAN = "human"
SUBJECT_AGENT = "agent"
SUBJECT_MIXED = "mixed"
SUBJECT_UNKNOWN = "unknown"

SUBJECTS = (SUBJECT_HUMAN, SUBJECT_AGENT, SUBJECT_MIXED, SUBJECT_UNKNOWN)

# THE THRESHOLD, AND WHY. "Predominantly" has to mean more than a bare
# majority before this module lets a report drop "you"/"your" or withhold a
# reference point on the strength of it — both of those are consequential,
# visible changes to the report, and the classifier behind `human_pct`/
# `agent_pct` is a heuristic that CAN be wrong (same posture this project
# already takes toward CODE_REF/AUTHORED/DELIB/CLARIFY in classifiers.py).
# 0.80 is chosen for the same reason SMALL_N=30 and composition.py's 3.0-point
# "near" tie-band are chosen: a round, defensible, DISCLOSED convention, not a
# power analysis. A corpus at 60% agent / 40% human is exactly the case this
# module must call `mixed`, not `agent` — calling it `agent` would silently
# erase the 40% and both drop their "you" and lose their own reference point.
DOMINANT_FRAC = 0.80

#: Minimum turns supporting the leading class before a categorical call. See
#: the long note in `infer_subject` for why this is not SMALL_N.
_LEADER_MIN = 20

# If the classifier itself could not place more than this share of turns in
# EITHER class, the classified remainder's split is not trustworthy enough to
# make a categorical call from — `unknown` PER TURN already means "not enough
# evidence for this turn"; too much of that corpus-wide means "not enough
# evidence for this corpus," independent of how the classified remainder
# leans. Same conservative-by-construction posture as DOMINANT_FRAC.
MAX_UNCLASSIFIED_FRAC = 0.50


def infer_subject(results: dict, small_n: int = SMALL_N,
                   dominant_frac: float = DOMINANT_FRAC,
                   max_unclassified_frac: float = MAX_UNCLASSIFIED_FRAC,
                   leader_min: int = _LEADER_MIN) -> tuple[str, str]:
    """Derive this run's SUBJECT from `results["authorship_mix"]` — never from
    a flag, per `cli.py`'s standing claim that there is no CLI switch for a
    capability-shaped decision like this one. Returns `(subject, reason)`:
    `subject` is one of `SUBJECTS`, `reason` is a short, human-readable
    sentence fragment (no trailing period) suitable for splicing into the
    audit sentence — it names the evidence, or names its absence, but never
    asserts the call is certain.

    `results` is a `run`-shaped `{analyzer_name: result_dict}` mapping — the
    same dict `cli.run()` already builds and passes to the renderer. Missing
    key, an `{"error": ...}` result, too few classified turns, or too much of
    the classified mass landing in `unknown` all fall through to
    `SUBJECT_UNKNOWN` — never a guess resolved toward `human` by default,
    which would just be today's unstated assumption wearing a variable name.
    """
    res = results.get("authorship_mix") if results else None
    if not res:
        return SUBJECT_UNKNOWN, ("no authorship classification ran this build (the "
                                  "authorship_mix analyzer is not registered) — not enough "
                                  "evidence to call the operator role human or agent")
    if "error" in res:
        return SUBJECT_UNKNOWN, (f"authorship_mix could not compute a classification "
                                  f"({res['error']}) — not enough evidence to call the "
                                  "operator role human or agent")
    n = res.get("n")
    if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
        return SUBJECT_UNKNOWN, ("authorship_mix reported no classified operator-role turns "
                                  "— not enough evidence to call the operator role human or agent")
    # The floor is on the turns SUPPORTING the leading class, not on corpus size.
    #
    # It used to be `n < small_n`, borrowed from SMALL_N, and that made the rule
    # incoherent: SMALL_N exists so a PERCENTAGE is not read to a decimal on a
    # thin sample, which is a different question from whether a two-way
    # categorical call is supported. Under the old rule a 30-turn corpus split
    # 24 human / 6 agent passed, while a 24-turn corpus that was 24/24
    # unanimously human was refused — rejecting strictly stronger evidence than
    # it accepted. Found by running the merged build on this project's own
    # corpus, where 24 unanimous human turns returned "undetermined"; both real
    # corpora available at the time failed the floor, so the feature never fired
    # at all in practice.
    #
    # `_LEADER_MIN` is a convention like every other number here, not a power
    # analysis, and it is deliberately the same 20 either way rather than tuned
    # per class. What it is NOT is a claim that 20 supporting turns make a call
    # safe — only that fewer than 20 is where this tool stops guessing.

    def _pct(key: str) -> float:
        v = res.get(key, 0.0)
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0

    human_pct, agent_pct, unknown_pct = _pct("human_pct"), _pct("agent_pct"), _pct("unknown_pct")

    if unknown_pct / 100.0 > max_unclassified_frac:
        return SUBJECT_UNKNOWN, (f"the classifier could not place {unknown_pct}% of {n} "
                                  "classified operator-role turns in either class — too little "
                                  "evidence for a categorical call")
    leader_pct = max(human_pct, agent_pct)
    leader_turns = int(round(n * leader_pct / 100.0))
    if leader_turns < leader_min:
        return SUBJECT_UNKNOWN, (f"only {leader_turns} of {n} classified operator-role turn(s) "
                                  f"support the leading class, below the {leader_min}-turn "
                                  "convention this tool uses before making a categorical call "
                                  "— not enough evidence")
    if human_pct / 100.0 >= dominant_frac:
        return SUBJECT_HUMAN, (f"{human_pct}% of {n} classified operator-role turns read as "
                                f"human (>= the {int(dominant_frac * 100)}% threshold for a "
                                "predominant call)")
    if agent_pct / 100.0 >= dominant_frac:
        return SUBJECT_AGENT, (f"{agent_pct}% of {n} classified operator-role turns read as "
                                f"agent (>= the {int(dominant_frac * 100)}% threshold for a "
                                "predominant call)")
    return SUBJECT_MIXED, (f"neither class reaches the {int(dominant_frac * 100)}% threshold "
                            f"({human_pct}% human, {agent_pct}% agent of {n} turns) — this "
                            "run's operator role mixes both")
