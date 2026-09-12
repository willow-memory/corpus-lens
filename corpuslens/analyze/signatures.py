"""Does the operator role show more than one authoring signature?

WHAT THIS ANSWERS. An owner may run a corpus that is not one human directing
one machine — a human plus an orchestrating agent, several automations that
all write into the same "operator" role, or (see the refusal below) a shape
this tool must not try to read at all. `signature_plurality` reports an
**opaque count** of distinct authoring signatures found in operator-role
turns, plus each signature's *shape* (share of turns, typical length band).
It never says who or what a signature is.

THE ETHICAL BOUNDARY THIS MODULE SITS ON, STATED PLAINLY: the same statistical
move that separates "agent A" from "agent B" by how their turns are shaped
also separates "person A" from "person B" — that is exactly the
re-identification mechanism GRADING.md question 9 exists to warn about (a
custody schedule read from keystroke timing alone, no content read). A
clustering routine with no idea what it is clustering will happily split
whatever variance it is given, including two people's handwriting. This
module is built so that it CANNOT do that, by construction, not by good
intentions:

  1. **No content, no tokens, ever.** Only `Event.features`
     (`word_count`, `char_count`, the ingest-time booleans) and the
     `authorship.py` contract's own verdict feed this analyzer. `README.md`
     names `distinctive_tokens` as unbuilt for exactly this reason — that
     feature is where names and identities live — and this module never
     reaches for it.
  2. **Relative time is available and deliberately UNUSED as a clustering
     axis.** `CoarseTime` is process-safe to emit (that is the wall's whole
     design), but *clustering turns by their timing signature* is the one
     operation this project's own founding observation says re-identifies a
     person from metadata alone. Using it here — even to separate two
     machines — would exercise the same capability this tool exists to warn
     other tools away from. So timing plays no role in which bucket a turn
     falls into, only length does. This is a refusal, not an oversight: a
     tempo-based signature split was considered and rejected for this reason.
  3. **The one categorical firewall: never split what the authorship
     contract calls HUMAN.** Every operator-role turn is first classified
     `HUMAN` / `AGENT` / `UNKNOWN` by `corpuslens.authorship.classify_turn`
     (a sibling contract — see the import fallback below). Turns the
     contract calls `HUMAN` are always exactly ONE signature, no matter how
     much their length or shape varies internally. This is true even when it
     is wrong: a corpus that (out of scope, per README's owner == subject
     rule) actually holds two humans typing into the operator role gets
     reported as one signature for that role's human-classified share,
     because this module does not attempt — structurally cannot attempt —
     to tell two humans apart. Undercounting a real second party is the
     acceptable error; inventing one, or splitting a real one into two
     imagined people, is not the kind of error this project allows itself.
  4. **Splitting happens only inside the AGENT-classified bucket, and only
     by one coarse, fixed length band** (`short` / `medium` / `long` word
     counts — see `_length_band`), never a general similarity search over
     the full feature vector. A candidate sub-signature must clear both a
     floor share and a floor count of the agent-classified turns before it
     is allowed to exist; anything under the floor is folded into the
     largest surviving band rather than discarded or given its own
     signature (undercount by construction, matching this project's rule
     that classifiers undercount, never overclaim).
  5. **UNKNOWN turns never spawn a signature.** They are reported as a
     coverage percentage only. Treating ambiguity as evidence of a new
     source would manufacture a party from noise.
  6. **The output carries no attribution.** There is no per-turn, per-thread,
     or per-event mapping back to a signature anywhere in this result — only
     a corpus-level count and a list of `{index, share_of_turns_pct,
     typical_length_band}` records. A reader cannot ask "which signature
     wrote this turn" from this analyzer's output, because that question is
     not answered here even in opaque-index form.
  7. **No label, no rank.** A signature's `index` is assigned by sorting an
     internal key alphabetically — not by share, not by turn count, not by
     which was seen first — so the order carries no claim about which
     signature came first or which is "the real one." The output never
     writes `human` or `agent` next to a specific signature; the contract's
     HUMAN/AGENT split is used only internally, as the gate described in
     point 3, never surfaced per-entry.
  8. **Refuses below `SMALL_N`,** and refuses outright if the authorship
     contract cannot confidently classify *any* eligible turn, rather than
     report a count built on zero confident labels.

WHAT WAS REFUSED OUTRIGHT (asked for by the framing, not built): anything
that would let a reader recover *which* turns, threads, or stretches of the
corpus belong to a given signature; any CLI flag or capability that would
increase the resolution of the split; and, most importantly, any attempt to
distinguish multiple humans. If a corpus genuinely contains more than one
person typing into the operator role, this analyzer's correct behavior is to
be blind to that fact — that corpus is out of scope for this whole project
(README: "owner == subject"), and an analyzer that quietly worked anyway
would be the guardian-consent tool IDEAS.md names as deliberately unbuilt,
arrived at by accident through a side door.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from ..model import AuthorClass, DataType
from . import SMALL_N, register

# `corpuslens/authorship.py` is a SIBLING deliverable — HUMAN/AGENT/UNKNOWN and
# classify_turn(features, marked_machine) — built elsewhere, not rebuilt here
# (see the task boundary this module was written against). It may not exist
# in every tree that imports this module. The except branch below is NOT a
# stand-in for that classifier: it is a minimal, deliberately under-confident
# fallback that exists only so this module's own tests can run standalone
# before the real contract lands. It leans UNKNOWN whenever it is not certain
# a turn was machine-marked, which is the safe direction here — an UNKNOWN
# turn never creates a signature (see module docstring, point 5) — rather
# than guessing HUMAN or AGENT with no basis. Nothing below this import
# should need to change when the real `authorship.py` arrives; only this
# `try` should stop taking the `except` path.
try:
    from ..authorship import AGENT, HUMAN, UNKNOWN, classify_turn  # noqa: F401
except ImportError:  # pragma: no cover — exercised via the stub in tests
    HUMAN, AGENT, UNKNOWN = "human", "agent", "unknown"

    def classify_turn(features: dict, marked_machine: bool = False) -> str:
        return AGENT if marked_machine else UNKNOWN


# What `authoring_plurality`'s number MEANS: eligibility is operator prompt
# turns with >=12 characters (the same de-injection floor every other
# analyzer here uses); a turn's length band is fixed word-count cutoffs, not
# quantiles of this corpus, so the same turn gets the same band in any
# corpus; an agent-classified sub-signature must hold at least
# `_BAND_MIN_COUNT` turns AND at least `_BAND_FLOOR_SHARE` of the
# agent-classified bucket before it is allowed to exist, and splitting is
# attempted at all only once the agent-classified bucket reaches
# `_AGENT_SPLIT_MIN_N` turns. Move any of these and "N distinct signatures"
# counts a different partition under the same name.
_MIN_CHARS = 12
_SHORT_MAX_WORDS = 5  # word_count <= this -> "short"
_LONG_MIN_WORDS = 40  # word_count > this -> "long"; between the two -> "medium"
_BAND_FLOOR_SHARE = 0.15
_BAND_MIN_COUNT = 5
_AGENT_SPLIT_MIN_N = SMALL_N

_SIGNATURE_INPUTS = (
    str(_MIN_CHARS),
    str(_SHORT_MAX_WORDS),
    str(_LONG_MIN_WORDS),
    str(_BAND_FLOOR_SHARE),
    str(_BAND_MIN_COUNT),
    str(_AGENT_SPLIT_MIN_N),
)
_SIGNATURE_HASH = "94f4f8624a39e8fd"


def _length_band(word_count: int) -> str:
    if word_count <= _SHORT_MAX_WORDS:
        return "short"
    if word_count > _LONG_MIN_WORDS:
        return "long"
    return "medium"


def _majority_band(feats: list) -> str:
    bands = [_length_band(f.get("word_count", 0)) for f in feats]
    return Counter(bands).most_common(1)[0][0]


@register(
    "signature_plurality",
    claims=("authoring_plurality",),
    denominator="operator prompt turns with >=12 characters (de-injected), classified by "
    "the authorship contract (authorship.py)",
    version=1,
    grading_question=(
        "none of GRADING.md's numbered questions — the rubric's ten questions "
        "assume one operator directing one machine (see IDEAS.md, 'Process "
        "when the work is delegated'); this analyzer checks that precondition "
        "rather than answering a numbered question, and is scoped to say "
        "nothing about people — only how many distinct operator-role "
        "signatures produced the corpus"
    ),
    semantic_hash=_SIGNATURE_HASH,
    semantic_inputs=_SIGNATURE_INPUTS,
)
def signature_plurality(events):
    """Count distinct authoring signatures in the operator role.

    See the module docstring for the full ethical design — in short: turns
    the authorship contract classifies HUMAN are always one signature, never
    split; only the AGENT-classified bucket may split, and only by a coarse
    length band that clears a floor share and count; UNKNOWN turns never
    create a signature; nothing here maps a signature back to a turn, thread,
    or time. `SMALL_N` and "the contract found nothing confident" both refuse
    rather than report a manufactured count.
    """
    turns = [
        e.features
        for e in events
        if e.author_class is AuthorClass.OPERATOR
        and e.data_type is DataType.PROMPT
        and e.features.get("char_count", 0) >= _MIN_CHARS
    ]
    total = len(turns)
    if total < SMALL_N:
        return {
            "error": (
                f"only {total} eligible operator turn(s) — below the {SMALL_N}-turn "
                "floor this tool uses everywhere a small sample would read as a finding "
                "instead of noise. Clustering a handful of turns into 'signatures' would "
                "manufacture a result, so this refuses instead of reporting one."
            )
        }

    human_feats, agent_feats, unknown_feats = [], [], []
    for f in turns:
        marked_machine = bool(f.get("injected_stripped"))
        label = classify_turn(dict(f), marked_machine=marked_machine)
        if label == HUMAN:
            human_feats.append(f)
        elif label == AGENT:
            agent_feats.append(f)
        else:
            unknown_feats.append(f)

    if not human_feats and not agent_feats:
        return {
            "error": (
                f"{total} eligible operator turns, and the authorship contract could "
                "not confidently classify any of them as human- or machine-authored — "
                "every one came back UNKNOWN. Reporting a signature count built on zero "
                "confident labels would be a guess wearing a number, so this refuses."
            )
        }

    # sort_key -> (share_of_all_turns, typical_length_band). The key is used
    # ONLY to fix a deterministic, non-meaningful order below (point 7 in the
    # module docstring) — it is never part of the returned result.
    found: dict = {}

    if human_feats:
        # Deliberately no internal split — see module docstring, point 3.
        found["human"] = (len(human_feats) / total, _majority_band(human_feats))

    if agent_feats:
        n_agent = len(agent_feats)
        by_band = defaultdict(list)
        for f in agent_feats:
            by_band[_length_band(f.get("word_count", 0))].append(f)
        qualifying = sorted(
            (band, members)
            for band, members in by_band.items()
            if len(members) >= _BAND_MIN_COUNT and len(members) / n_agent >= _BAND_FLOOR_SHARE
        )
        if len(qualifying) >= 2:
            covered = sum(len(members) for _, members in qualifying)
            leftover = (
                n_agent - covered
            )  # non-qualifying bands, folded away — never their own signature
            largest = max(range(len(qualifying)), key=lambda i: len(qualifying[i][1]))
            for i, (band, members) in enumerate(qualifying):
                count = len(members) + (leftover if i == largest else 0)
                found[f"agent:{band}"] = (count / total, band)
        else:
            found["agent"] = (n_agent / total, _majority_band(agent_feats))

    ordered = [found[k] for k in sorted(found)]  # alphabetical key only: no rank implied
    count = len(ordered)
    unclassified_pct = round(100 * len(unknown_feats) / total, 1)
    signatures = [
        {"index": i, "share_of_turns_pct": round(100 * share, 1), "typical_length_band": band}
        for i, (share, band) in enumerate(ordered)
    ]

    return {
        "headline": (
            f"This corpus's operator-role turns show {count} distinct authoring "
            f"signature{'s' if count != 1 else ''} (opaque index only — this does not "
            f"say which one is you, and it never distinguishes between two humans)."
        ),
        "n": total,
        "signature_count": count,
        "signatures": signatures,
        "unclassified_turns_pct": unclassified_pct,
        "reading": (
            "1 signature = this corpus's operator role reads as one uniform authoring "
            "process. More than 1 means it is not — it stopped after the first split it "
            "was confident about, so treat this count as a floor, never a ceiling: a real "
            "third or fourth source can hide inside a signature this analyzer merged away, "
            "but it will never invent one that is not there. It does not and cannot say "
            "whether an extra signature is a second agent or a second person — that "
            "question is out of scope for this tool by design (README: owner == subject)."
        ),
    }
