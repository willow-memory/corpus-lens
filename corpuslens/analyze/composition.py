"""Who writes the code, and do you deliberate on purpose?
(GRADING.md questions 2–3.) Feature-based; content never reaches here.

The code classifiers this module leans on (`CODE_REF`, `AUTHORED` — see
`corpuslens/classifiers.py`) are English-and-Python shaped: `CODE_REF` knows nine
file extensions and Python's own traceback line, `AUTHORED` knows a handful of
languages' block syntax (Python/JS/TS/Java/C#/shell/SQL). A corpus in a
language they don't recognize — a different programming language's block
syntax, or prose in a language other than English for `DELIB`/`CLARIFY` —
looks IDENTICAL, from these regexes' point of view, to a corpus with no code
in it at all: both score 0.0%. `composition_mix` and `clarification_pull`
refuse rather than report that zero once the sample is large enough to make
"detected nothing" mean something (see `SMALL_N` in `analyze/__init__.py`) —
see each function's docstring for the exact two readings the refusal names."""
from __future__ import annotations

import statistics

from ..classifiers import AUTHORED, CLARIFY, CODE_REF, DELIB
from ..model import AuthorClass, DataType
from . import SMALL_N, register, semantic_hash

# What these two analyzers' numbers MEAN depends on the classifier regexes
# that set `code_authored`/`code_ref`/`delib`/`clarify` at ingest (they live in
# top-level corpuslens/classifiers.py, shared by every adapter) and
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
          version=1,
          grading_question=("question 2 (authored_code_pct / code_ref_pct, against the domain "
                             "population — GRADING.md's stated method exactly); and part of "
                             "question 3 for delib_pct — it reports the discussion-channel share "
                             "but not whether those prompts pull longer, more structured "
                             "responses, which question 3 also asks for"),
          semantic_hash=_COMPOSITION_MIX_HASH,
          semantic_inputs=_COMPOSITION_MIX_INPUTS)
def composition_mix(events):
    """See the module docstring for why the two code classifiers this
    function reports on (`code_authored`, `code_ref`) can go silent on a
    corpus that has nothing wrong with it.

    Refusal rule: past `SMALL_N` turns, "zero matches from two independent
    regex families" stops being sampling noise and starts being a signal
    worth naming — but the classifiers cannot tell you WHICH of two signals:
    a corpus with no code in it, or a coding corpus in a shape they don't
    parse (an unlisted extension, a language `AUTHORED` has no block-syntax
    branch for). Claiming to know which would be a new overclaim on top of
    the one this refusal exists to avoid, so the error names both and picks
    neither. Below `SMALL_N`, zero matches is business as usual — most
    corpora have long stretches with no code turn — so no refusal fires.

    `delib_pct` is dropped from the refusal along with `authored`/`ref`, even
    though `DELIB` is a wholly separate regex that may well have matched:
    this analyzer's one headline and one reference table bundle deliberation
    together with code authorship as a `wildchat_coding_population`
    comparison, and once the code classifiers are refused we no longer know
    whether that reference population applies at all — WildChat's own
    `delib_pct` differs between its "coding" (3.2%) and "all" (6.6%) slices,
    so reporting `delib_pct` here without knowing which one this corpus is
    would smuggle the very ambiguity this refusal exists to name back in
    through one field. A deliberation-only reading, decoupled from code
    composition and its population choice, is worth a future analyzer of its
    own (see NOTES-corpus-refusal.md) — not a quiet exception carved into
    this one's error path.
    """
    turns = [e.features for e in events
             if e.author_class is AuthorClass.OPERATOR and e.data_type is DataType.PROMPT
             and e.features.get("char_count", 0) >= 12]
    n = len(turns)
    if not n:
        return {"error": "no operator prompts found"}
    authored_n = sum(1 for f in turns if f.get("code_authored"))
    ref_n = sum(1 for f in turns if f.get("code_ref"))
    if n > SMALL_N and authored_n == 0 and ref_n == 0:
        return {"error": (
            f"{n} operator turns, and the code classifiers (CODE_REF, AUTHORED) matched none of "
            "them. Two readings fit this equally well and this analyzer cannot tell them apart: "
            "either this is not a coding corpus, or it is one these regexes cannot read — they are "
            "English-and-Python shaped (CODE_REF knows nine file extensions; AUTHORED knows a "
            "handful of languages' block syntax), so an unrecognized language or file type looks "
            "identical to no code at all. Reporting 0.0% here would pick one of those readings "
            "without evidence, so this refuses instead."
        )}
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
          version=1,
          grading_question=("none of GRADING.md's numbered questions directly — closest is "
                             "question 3, but question 3 is about YOUR prompts opening a "
                             "discussion channel; this measures the machine asking and you "
                             "answering, the reverse direction, which GRADING.md does not pose "
                             "as a question"),
          semantic_hash=_CLARIFICATION_PULL_HASH,
          semantic_inputs=_CLARIFICATION_PULL_INPUTS)
def clarification_pull(events):
    """See the module docstring: `CLARIFY` is a list of English phrases
    ("do you mean", "would you like", "just to confirm", …), so it goes silent
    on a non-English corpus exactly the way `CODE_REF`/`AUTHORED` go silent on
    an unrecognized language — indistinguishably from a corpus where the
    machine genuinely never asked a clarifying question. Past `SMALL_N`
    machine turns with not one `CLARIFY` match, this refuses rather than
    report 0.0% for the same reason `composition_mix` does: the two readings
    are equally consistent with the evidence, and picking one would overclaim.
    """
    ordered = {}
    for e in events:
        ordered.setdefault(e.thread_id, []).append(e)
    asst = forks = clarify_hits = 0
    for turns in ordered.values():
        for i, e in enumerate(turns):
            if not (e.author_class is AuthorClass.MACHINE and e.data_type is DataType.RESPONSE):
                continue
            if e.features.get("char_count", 0) < 12:
                continue
            asst += 1
            if e.features.get("clarify"):
                clarify_hits += 1
                if e.features.get("question"):
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
    if asst > SMALL_N and clarify_hits == 0:
        return {"error": (
            f"{asst} machine response turns, and CLARIFY never matched one of them. Two readings "
            "fit this equally well and this analyzer cannot tell them apart: either the machine "
            "never asked a clarifying question in this corpus, or CLARIFY cannot read it — it is a "
            "list of English phrases (\"do you mean\", \"would you like\", \"just to confirm\", …), "
            "so a non-English corpus looks identical to one with no clarifying questions at all. "
            "Reporting 0.0% here would pick one of those readings without evidence, so this refuses "
            "instead."
        )}
    fork_pct = round(100 * forks / asst, 2)
    return {"headline": (f"The machine asked a clarifying question you then answered in "
                         f"{fork_pct}% of its turns."),
            "n": asst,
            "assistant_turns": asst, "clarification_forks_pct": fork_pct,
            "reference": {"measured_cli": 3.4,
                          "measured_cursor_note": "2.47 — measured elsewhere; NOT computable here "
                          "(cursor logs carry no assistant turns), shown for context only"}}
