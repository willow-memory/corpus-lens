"""Is the operator role a person? `authorship_mix` checks the assumption every
other analyzer in this registry inherits without checking it.

`steering_density`, `composition_mix`, `clarification_pull` and `thread_shape`
all read `AuthorClass.OPERATOR` and report on it as "you". Pointed at a corpus
where that role is not consistently a human — an automated dispatch loop, a
benchmark harness, a session that mixes a person's own turns with agent
prompts it dispatched — those analyzers still run and still produce a number
that reads like a person's. `authorship_mix` is not a fix for that (it cannot
rewrite what those analyzers already assumed); it is the number that tells you
whether their assumption held on the corpus you just ran.

This analyzer classifies TURNS, never people. See `corpuslens/authorship.py`
for the full account of what `classify_turn` does and does not do, the
evidence its two thresholds rest on, and why that evidence is this feature's
weakest part.
"""
from __future__ import annotations

from ..authorship import AGENT, AUTHORSHIP_VERSION, AGENT_MIN_WORDS, HUMAN, HUMAN_MAX_WORDS, UNKNOWN, classify_turn
from ..model import AuthorClass, DataType
from . import register, semantic_hash

# What this analyzer's number MEANS depends on `classify_turn`'s two
# thresholds (`corpuslens/authorship.py`) and on the marked-machine
# short-circuit ahead of them. Pin the threshold TEXT here exactly as
# `composition_mix`/`clarification_pull` pin classifier pattern text: an edit
# to either threshold in `authorship.py` changes what HUMAN/AGENT/UNKNOWN mean
# below, and `tests/test_analyzer_versions.py` recomputes this hash from the
# same live values, so a threshold edit with no version bump fails the suite.
_AUTHORSHIP_MIX_INPUTS = (str(HUMAN_MAX_WORDS), str(AGENT_MIN_WORDS), AUTHORSHIP_VERSION)
_AUTHORSHIP_MIX_HASH = "1224e305b904fed4"


@register("authorship_mix", claims=("authorship_mix",),
          denominator="operator-role turns (AuthorClass.OPERATOR prompt events)",
          version=1,
          grading_question=("none of GRADING.md's numbered questions directly — question 1 "
                             "('where does your intent arrive') presupposes the operator role is "
                             "a person; this analyzer checks that precondition rather than "
                             "answering a numbered question of its own"),
          semantic_hash=_AUTHORSHIP_MIX_HASH,
          semantic_inputs=_AUTHORSHIP_MIX_INPUTS)
def authorship_mix(events):
    """Share of operator-role turns `classify_turn` puts in each of HUMAN,
    AGENT and UNKNOWN. No adapter in this registry currently sets
    `marked_machine` for a surviving event (the claude-code adapter drops
    sidechain/compaction/whole-turn-machine records before an Event exists at
    all — see `ingest/claude_code.py`), so every turn here is classified on
    features alone; see `corpuslens/authorship.py` for exactly what that
    does and does not let this analyzer conclude.

    No refusal rule (unlike `composition_mix`/`clarification_pull`): a high
    `unknown_pct` is not an ambiguous zero to explain away, it is this
    analyzer's honest, expected majority outcome on a corpus that really is
    one person directing one machine — `UNKNOWN` is `classify_turn`'s default,
    not its failure mode. A LOW `unknown_pct` alongside a high `agent_pct` is
    the finding worth reading twice, not the reverse.
    """
    turns = [e.features for e in events
             if e.author_class is AuthorClass.OPERATOR and e.data_type is DataType.PROMPT]
    n = len(turns)
    if not n:
        return {"error": "no operator-role turns found"}
    counts = {HUMAN: 0, AGENT: 0, UNKNOWN: 0}
    for f in turns:
        # `marked_machine` stays False here for the reason given in this
        # function's own docstring: nothing in the current registry survives
        # ingest carrying that marker on an Event. A future adapter that keeps
        # (rather than drops) a marked record should pass its own signal
        # through instead of silently inheriting this False.
        counts[classify_turn(f, marked_machine=False)] += 1
    pct = lambda k: round(100 * counts[k] / n, 1)
    human_pct, agent_pct, unknown_pct = pct(HUMAN), pct(AGENT), pct(UNKNOWN)
    return {
        "headline": (f"Of your operator-role turns, {human_pct}% look human-authored, "
                     f"{agent_pct}% look agent-authored, and {unknown_pct}% are unresolved."),
        "n": n,
        "human_pct": human_pct,
        "agent_pct": agent_pct,
        "unknown_pct": unknown_pct,
        "human_n": counts[HUMAN],
        "agent_n": counts[AGENT],
        "unknown_n": counts[UNKNOWN],
        "reading": ("a high agent_pct on a corpus you believed was one person means the operator "
                    "role is not consistently you — an automated dispatch loop, a benchmark "
                    "harness, or a session mixing your own turns with agent prompts you "
                    "dispatched. A high unknown_pct is the expected default, not a warning sign: "
                    "this classifier is built to undercount rather than assert a label it cannot "
                    "support (see corpuslens/authorship.py). This is not, and cannot become, "
                    "a claim about WHICH person authored a turn."),
    }
