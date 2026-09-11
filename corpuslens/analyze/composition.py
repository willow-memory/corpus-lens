"""Who writes the code, and do you deliberate on purpose?
(GRADING.md questions 2–3.) Feature-based; content never reaches here."""
from __future__ import annotations

import statistics

from ..ingest.claude_code import AUTHORED, CLARIFY, CODE_REF, DELIB
from ..model import AuthorClass, DataType
from . import register, semantic_hash

# What these two analyzers' numbers MEAN depends on the classifier regexes
# that set `code_authored`/`code_ref`/`delib`/`clarify` at ingest (only the
# claude-code adapter populates them; see corpuslens/ingest/claude_code.py) and
# on the >=12-char turn filter both apply. Pin the regex TEXT (not the compiled
# object) plus the thresholds: `tests/test_analyzer_versions.py` recomputes
# `semantic_hash(*inputs)` from these same live values and fails the moment one
# changes, so an editor of AUTHORED/CODE_REF/DELIB/CLARIFY is stopped and asked
# to bump `version` and paste the new hash below — see analyze/__init__.py.
_MIN_CHARS = "12"
_NEAR_BAND = "3.0"     # the "near" tie-band in `side()` below is part of the claim too
_COMPOSITION_MIX_INPUTS = (AUTHORED.pattern, CODE_REF.pattern, DELIB.pattern,
                          _MIN_CHARS, _NEAR_BAND)
_COMPOSITION_MIX_HASH = "5d66942a325be997"
_CLARIFICATION_PULL_INPUTS = (CLARIFY.pattern, _MIN_CHARS)
_CLARIFICATION_PULL_HASH = "3ebee7fb1a0e8bfc"

REFERENCE = {
    "wildchat_coding_population": {"authored_pct": 14.5, "read_ref_pct": 36.0, "delib_pct": 3.2},
    "wildchat_all": {"authored_pct": 3.0, "read_ref_pct": 12.3, "delib_pct": 6.6},
    "oasst_general_chat": {"delib_pct": 7.3},
    "measured_director_n1": {"authored_pct": 6.3, "read_ref_pct": 18.3, "delib_pct": 5.2},
}


@register("composition_mix", claims=("composition_mix",),
          denominator="operator prompt turns with >=12 characters (de-injected)",
          version=1, semantic_hash=_COMPOSITION_MIX_HASH,
          semantic_inputs=_COMPOSITION_MIX_INPUTS)
def composition_mix(events):
    turns = [e.features for e in events
             if e.author_class is AuthorClass.OPERATOR and e.data_type is DataType.PROMPT
             and e.features.get("char_count", 0) >= 12]
    n = len(turns)
    if not n:
        return {"error": "no operator prompts found"}
    pct = lambda k: round(100 * sum(1 for f in turns if f.get(k)) / n, 1)
    authored, ref, delib = pct("code_authored"), pct("code_ref"), pct("delib")
    pop = REFERENCE["wildchat_coding_population"]

    def side(mine, theirs):
        """Direction against a reference, with a band where the classifiers'
        error swamps the gap — 'near' is an honest answer, and a regex
        heuristic does not get to call a 2-point difference."""
        if abs(mine - theirs) < 3.0:
            return "near"
        return "above" if mine > theirs else "below"

    return {
        "headline": (f"You authored code in {authored}% of your prompts and referred to existing "
                     f"code in {ref}%; {delib}% deliberate before building."),
        "n": n,
        "vs_coding_population": (
            f"authored {authored}% vs {pop['authored_pct']}% ({side(authored, pop['authored_pct'])}), "
            f"code-ref {ref}% vs {pop['read_ref_pct']}% ({side(ref, pop['read_ref_pct'])}), "
            f"deliberation {delib}% vs {pop['delib_pct']}% ({side(delib, pop['delib_pct'])}) "
            f"— WildChat coding population"),
        "n_turns": n,
        "authored_code_pct": authored,
        "code_ref_pct": ref,
        "delib_pct": delib,
        "median_words": statistics.median(f["word_count"] for f in turns),
        "reference": REFERENCE,
        "reading": ("above the coding population on authored/read-ref = you bring the code to the "
                    "machine; well below it = the machine holds the code and you direct. "
                    "delib above your domain population = you summon the teaching surface on purpose."),
    }


@register("clarification_pull", claims=("clarification_pull",),
          denominator="machine response turns (>=12 chars)",
          version=1, semantic_hash=_CLARIFICATION_PULL_HASH,
          semantic_inputs=_CLARIFICATION_PULL_INPUTS)
def clarification_pull(events):
    ordered = {}
    for e in events:
        ordered.setdefault(e.thread_id, []).append(e)
    asst = forks = 0
    for turns in ordered.values():
        for i, e in enumerate(turns):
            if not (e.author_class is AuthorClass.MACHINE and e.data_type is DataType.RESPONSE):
                continue
            if e.features.get("char_count", 0) < 12:
                continue
            asst += 1
            if e.features.get("clarify") and e.features.get("question"):
                # a fork = the NEXT operator turn in the thread answers, even if
                # machine tool-result turns sit between (review fix — strict
                # adjacency missed forks whenever the assistant used a tool).
                nxt = next((turns[j] for j in range(i + 1, len(turns))
                            if turns[j].author_class is AuthorClass.OPERATOR), None)
                if nxt is not None:
                    forks += 1
    if not asst:
        return {"error": "no machine responses in corpus — this analyzer needs a claude-code "
                         "corpus; the cursor adapter is prompt-only (no assistant turns)"}
    fork_pct = round(100 * forks / asst, 2)
    return {"headline": (f"The machine asked a clarifying question you then answered in "
                         f"{fork_pct}% of its turns."),
            "n": asst,
            "assistant_turns": asst, "clarification_forks_pct": fork_pct,
            "reference": {"measured_cli": 3.4,
                          "measured_cursor_note": "2.47 — measured elsewhere; NOT computable here "
                          "(cursor logs carry no assistant turns), shown for context only"}}
