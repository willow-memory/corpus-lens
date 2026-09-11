"""corpuslens.label — a local labelling mode for the classifiers' own error.

Spec: IDEAS.md, "A local labelling mode" (Near). The classifiers (CODE_REF,
AUTHORED, DELIB, CLARIFY in `ingest/claude_code.py`) are regex heuristics the
README says to "trust direction plus your own spot-check". Nobody has ever
measured their precision/recall on a real corpus, because doing so needs a
human to read their own turns and judge them — a model must never do this
(that would put an unauditable judgment exactly where this tool refuses to
guess), and it must never persist content (that would defeat the wall for no
reason: the judgment is a yes/no, not a document).

This module holds everything that does NOT need a terminal, so it can be unit
tested without one: what is eligible to sample, the fixed-seed sample itself,
the label-store shape and its version discipline, and the precision/recall
math. `cli.py` owns the interactive loop (the part that calls `input()`) and
the non-tty refusal.

WHAT THE STORE MAY CONTAIN (rule 3, non-negotiable): a label store is a JSON
object holding ONLY the label values, the opaque `source_ref` hash the `Event`
already carries, and the classifier version that was graded. Never content,
never a filename, never a timestamp, never a day offset. `save_store` writes
exactly that shape and nothing else.

AUTHORSHIP (added after the sibling `corpuslens/authorship.py` classifier —
HUMAN / AGENT / UNKNOWN, see that module's docstring for the contract this
file grades but does not reimplement) does NOT fit the shape above and is kept
visibly separate rather than shoehorned into `labels`/`classifier_version`:

  * it is ONE three-valued judgment per turn ("who actually wrote this"), not
    a family of independent yes/no classifiers, so it gets its own list
    (`authorship_labels`) instead of a `classifier` key in `labels`;
  * its ground-truth label is the STRING "human" or "agent" (the contract's
    HUMAN/AGENT constants), never a bool — a three-valued judgment is not
    naturally yes/no, and forcing it into `bool()` (as `save_store` already
    does for the four regex classifiers) would silently coerce "agent" to
    `True` and lose the distinction this whole feature exists to keep;
  * it is tied to `AUTHORSHIP_VERSION`, a SEPARATE version axis from
    `CLASSIFIER_SET_VERSION` — the regex classifiers and the authorship
    classifier are different code, will change on different schedules, and a
    store must never let one's version stand in for the other's.

Still nothing new leaves the wall: `authorship_labels` holds only
`{source_ref, label}` pairs, same opaque hash, no content.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from .classifiers import CLASSIFIER_SET_VERSION
from .model import AuthorClass, DataType

#: Fixed so the SAME corpus with the SAME --sample-size yields the SAME sample
#: on a rerun (the point being: you can label a bit today, close the terminal,
#: and pick up later without corpuslens re-shuffling what you already saw). It
#: is not a cryptographic seed and not a claim about randomness quality — just
#: a reproducibility knob, like the SEED that would back a bootstrap CI if this
#: project ever built one (it does not; see README/IDEAS on bootstrap CIs).
SEED = 20260607

#: This project's sample-size CONVENTION for a labelling run, same status as
#: `render.SMALL_N`: a number someone picked, not a power analysis. IDEAS.md
#: ("A local labelling mode") is explicit that the sample-size argument stays
#: in Stretch — nothing here computes how large a sample would need to be for
#: a given confidence, and the CLI help text says so rather than implying it.
DEFAULT_SAMPLE_SIZE = 50

#: Which classifiers apply to which author class, and the yes/no question that
#: measures each one. Order matters only for display.
CLASSIFIERS_BY_AUTHOR = {
    AuthorClass.OPERATOR: ("code_authored", "code_ref", "delib"),
    AuthorClass.MACHINE: ("clarify",),
}

QUESTIONS = {
    "code_authored": ("Did the OPERATOR author or paste code in this turn "
                       "(not just refer to code that already exists)?"),
    "code_ref": ("Does this turn refer to EXISTING code — a file, function, symbol, "
                 "error, or traceback — without the operator pasting new code?"),
    "delib": ("Is the operator asking to deliberate or think through options here "
              "(not just naming a choice they already made)?"),
    "clarify": ("Does this response read as the machine asking a clarifying question "
                "— something it wants the operator to pick, confirm, or resolve?"),
}

#: The ONE question that grades `corpuslens.authorship.classify_turn` — asked
#: for every eligible turn, operator prompt or machine response alike, in
#: addition to whichever QUESTIONS above apply to that turn's author_class.
#: Worded so the labeller (the corpus owner, reading their own turn) can
#: actually answer it: "did a person type this" is a fact they witnessed,
#: not a guess about intent, deliberation, or code style like the questions
#: above. It deliberately does NOT ask "is this turn logged as operator or
#: machine" — the whole point of grading authorship is to check whether the
#: classifier gets it right independent of, and sometimes despite, how the
#: source logged it (see authorship.py's module docstring).
AUTHORSHIP_QUESTION = (
    "Regardless of how this turn happens to be logged: was it actually typed by a "
    "person, as opposed to a machine (an AI, an agent, an automated script) "
    "producing or relaying it?"
)


def classifiers_for(author_class) -> tuple:
    """Which classifier keys apply to a turn of this author_class. Empty tuple
    for anything that is neither an operator prompt's nor a machine response's
    author class — callers should not sample those turns at all."""
    return CLASSIFIERS_BY_AUTHOR.get(author_class, ())


def eligible_pool(events) -> list:
    """The turns `corpuslens label` may sample: operator prompts and machine
    responses with >=12 characters — the SAME threshold `composition_mix` and
    `clarification_pull` use, so a labelled sample's `n` describes the same
    population those analyzers' rates are drawn from, not a looser one."""
    pool = []
    for e in events:
        if e.features.get("char_count", 0) < 12:
            continue
        if e.author_class is AuthorClass.OPERATOR and e.data_type is DataType.PROMPT:
            pool.append(e)
        elif e.author_class is AuthorClass.MACHINE and e.data_type is DataType.RESPONSE:
            pool.append(e)
    return pool


def authorship_eligible_pool(events) -> list:
    """The turns eligible for an authorship judgment. Currently the SAME pool
    as `eligible_pool` — every turn worth showing a labeller for the regex
    questions is also one they can answer "did a person type this" for,
    including a machine turn (the labeller knows whether they dictated a
    reply verbatim or the agent produced it). Kept as its own name rather
    than a bare alias so the two pools can diverge later without every call
    site guessing which one it meant."""
    return eligible_pool(events)


class AuthorshipUnavailable(RuntimeError):
    """Raised when `corpuslens.authorship` — the sibling module that defines
    HUMAN/AGENT/UNKNOWN and `classify_turn(features, marked_machine=False)`
    — is not importable in this build. This file grades that classifier; it
    does not reimplement it (see the module docstring's AUTHORSHIP section),
    so authorship labelling/scoring is a graceful no-op with a clear message
    until the sibling module ships, never a crash and never a silent stub."""


def authorship_contract():
    """Import `corpuslens.authorship` lazily and return the module, or raise
    `AuthorshipUnavailable` with a ready-to-print message. LAZY on purpose:
    importing `label` itself (and every test that only exercises the four
    regex classifiers) must keep working whether or not the authorship
    classifier has landed yet — a top-level `from . import authorship` would
    make this whole module unimportable in the meantime."""
    try:
        from . import authorship as mod
    except ImportError as e:
        raise AuthorshipUnavailable(
            "the authorship classifier (corpuslens/authorship.py — HUMAN/AGENT/UNKNOWN, "
            "classify_turn(features, marked_machine=False)) is not available in this build. "
            "Authorship labelling/scoring needs it; the four regex classifiers are unaffected."
        ) from e
    return mod


def sample_events(events, n: int = DEFAULT_SAMPLE_SIZE, seed: int = SEED) -> list:
    """A fixed-seed sample of up to `n` eligible turns. The pool is sorted by
    its own opaque `source_ref` hash before sampling — never by anything that
    would make the sample depend on filesystem iteration order or the corpus's
    real dates — so the SAME corpus yields the SAME sample every time, which is
    the whole point of a fixed seed."""
    pool = sorted(eligible_pool(events), key=lambda e: e.source_ref)
    if not pool:
        return []
    rng = random.Random(seed)
    return rng.sample(pool, min(n, len(pool)))


# ── the label store ──────────────────────────────────────────────────────────

def empty_store() -> dict:
    return {"classifier_version": None, "labels": [],
            "authorship_version": None, "authorship_labels": []}


def load_store(path) -> dict:
    """The store at `path`, or an empty one if it does not exist yet. Never
    raises on a missing file — a first `corpuslens label` run creates it.
    `authorship_version`/`authorship_labels` default to None/[] for a store
    written before this feature existed — an old store is still a valid,
    empty-on-authorship store, not a malformed one."""
    p = Path(path)
    if not p.exists():
        return empty_store()
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "labels" not in data:
        raise ValueError(f"{path} does not look like a corpuslens label store "
                          f"(expected an object with a 'labels' list)")
    return {"classifier_version": data.get("classifier_version"),
            "labels": list(data.get("labels", [])),
            "authorship_version": data.get("authorship_version"),
            "authorship_labels": list(data.get("authorship_labels", []))}


def save_store(path, store: dict) -> None:
    """Writes {classifier_version, labels: [{source_ref, classifier, label}, ...]}
    plus, ONLY when authorship has ever been used on this store,
    {authorship_version, authorship_labels: [{source_ref, label}, ...]} — a
    store that never touched authorship round-trips with exactly the two
    original keys, so this change is invisible to a store from before
    authorship existed. Nothing else is ever added to either dict on the way
    out, so a future field cannot smuggle content in by accident. Note the
    authorship `label` is a STRING ("human"/"agent"), never coerced through
    `bool()` like the regex classifiers' labels are — that coercion is
    exactly what a three-valued judgment cannot survive."""
    labels = [{"source_ref": r["source_ref"], "classifier": r["classifier"],
               "label": bool(r["label"])} for r in store["labels"]]
    out = {"classifier_version": store.get("classifier_version"), "labels": labels}
    authorship_labels = store.get("authorship_labels") or []
    if store.get("authorship_version") is not None or authorship_labels:
        out["authorship_version"] = store.get("authorship_version")
        out["authorship_labels"] = [{"source_ref": r["source_ref"], "label": str(r["label"])}
                                     for r in authorship_labels]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, sort_keys=True)
        f.write("\n")


def check_version(store: dict, current: str = CLASSIFIER_SET_VERSION) -> str | None:
    """None if `store` is compatible with the installed classifiers (empty, or
    already graded against `current`); otherwise an error message to print and
    refuse on. A label set is tied to the classifier version it graded — this
    is the one check standing between that rule and a silent wrong comparison."""
    v = store.get("classifier_version")
    if v is None or v == current:
        return None
    return (f"this label store was graded against classifier version {v!r}, but the "
            f"installed classifiers are {current!r}. Scoring (or adding new labels) "
            f"against a different version is refused, not silently compared — start a "
            f"fresh --store file if the classifiers changed on purpose.")


def check_authorship_version(store: dict, current: str) -> str | None:
    """The same refusal as `check_version`, on the SEPARATE `authorship_version`
    axis — `current` is `corpuslens.authorship.AUTHORSHIP_VERSION`, passed in
    rather than defaulted, because getting it at all requires the caller to
    have already handled `AuthorshipUnavailable` (see `authorship_contract`).
    None if `store` has no authorship judgments yet, or was graded against
    `current`; otherwise a message to print and refuse on — grading (or
    adding) authorship labels against a different version than they were
    recorded under is refused, never silently compared, exactly like the
    regex classifiers' own version discipline."""
    v = store.get("authorship_version")
    if v is None or v == current:
        return None
    return (f"this label store's authorship judgments were graded against authorship "
            f"version {v!r}, but the installed authorship classifier is {current!r}. "
            f"Scoring (or adding new authorship labels) against a different version is "
            f"refused, not silently compared — clear authorship_labels (or start a fresh "
            f"--store file) if the authorship classifier changed on purpose. The regex "
            f"classifiers' own labels in this store are unaffected.")


def already_labelled(store: dict) -> set:
    return {(r["source_ref"], r["classifier"]) for r in store["labels"]}


def add_label(store: dict, source_ref: str, classifier: str, label: bool,
              version: str = CLASSIFIER_SET_VERSION) -> None:
    store["classifier_version"] = version
    store["labels"].append({"source_ref": source_ref, "classifier": classifier,
                            "label": bool(label)})


def already_labelled_authorship(store: dict) -> set:
    """Source refs that already have an authorship judgment. Unlike
    `already_labelled`, this is not keyed by (source_ref, classifier) — there
    is exactly one authorship question per turn, not a family of them."""
    return {r["source_ref"] for r in store.get("authorship_labels", [])}


def add_authorship_label(store: dict, source_ref: str, label: str, version: str) -> None:
    """Record the human's ground-truth authorship judgment for one turn.
    `label` must be the contract's HUMAN or AGENT string constant (never a
    bool — see this module's docstring); `version` must be the installed
    `corpuslens.authorship.AUTHORSHIP_VERSION`, fetched by the caller through
    `authorship_contract()` so this function never needs to import the
    sibling module itself."""
    store["authorship_version"] = version
    store.setdefault("authorship_labels", []).append(
        {"source_ref": source_ref, "label": str(label)})


# ── scoring ──────────────────────────────────────────────────────────────────

def score(events, store: dict) -> dict:
    """Precision, recall and n per classifier, re-running the classifiers over
    `events` (already-ingested, feature-bearing Events — never content) and
    comparing to the human labels in `store`. Returns
    {classifier: {n, tp, fp, fn, tn, precision_pct, recall_pct, ...} | {"error": ...}},
    plus a top-level "missing" count: labels whose source_ref is no longer in
    this corpus (the corpus changed since labelling) — counted, never silently
    dropped, matching this project's drop-accounting rule everywhere else."""
    by_ref = {e.source_ref: e for e in events}
    pairs_by_classifier: dict = {}
    missing = 0
    for rec in store["labels"]:
        e = by_ref.get(rec["source_ref"])
        if e is None:
            missing += 1
            continue
        classifier = rec["classifier"]
        y_true = bool(rec["label"])
        y_pred = bool(e.features.get(classifier, False))
        pairs_by_classifier.setdefault(classifier, []).append((y_true, y_pred))

    results = {}
    for classifier, pairs in sorted(pairs_by_classifier.items()):
        results[classifier] = _precision_recall(pairs)
    return {"classifiers": results, "missing": missing,
            "total_labels": len(store["labels"])}


def _precision_recall(pairs: list) -> dict:
    n = len(pairs)
    tp = sum(1 for t, p in pairs if t and p)
    fp = sum(1 for t, p in pairs if (not t) and p)
    fn = sum(1 for t, p in pairs if t and (not p))
    tn = sum(1 for t, p in pairs if (not t) and (not p))
    predicted_pos = tp + fp
    actual_pos = tp + fn
    precision = round(100 * tp / predicted_pos, 1) if predicted_pos else None
    recall = round(100 * tp / actual_pos, 1) if actual_pos else None
    out = {
        "n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision_pct": precision,
        "precision_denominator": "labelled turns the classifier predicted positive (tp+fp)",
        "recall_pct": recall,
        "recall_denominator": "labelled turns a human marked positive (tp+fn)",
    }
    if precision is None:
        out["precision_note"] = "not computable: the classifier never predicted positive in this sample"
    if recall is None:
        out["recall_note"] = "not computable: no labelled turn in this sample was marked positive"
    return out


# ── authorship scoring (three-valued: human / agent / unknown) ─────────────
#
# THE SHAPE PROBLEM. The four regex classifiers above are each a single
# yes/no question graded with one precision and one recall. Authorship is
# not that shape twice over:
#
#   1. It is THREE-VALUED, not binary. `classify_turn` answers human, agent,
#      or unknown — there is no single "positive" class to build one
#      precision/recall pair around, so this reports precision and recall
#      PER CLASS (human, agent) the way a multiclass classifier is normally
#      graded, rather than forcing a three-valued answer through the
#      two-valued `_precision_recall` above.
#
#   2. UNKNOWN IS A DECLINE, NOT A WRONG ANSWER. A classifier that answers
#      UNKNOWN on every turn is never wrong in the sense of "said agent when
#      the truth was human" — it never says either. Folded naively into a
#      binary positive/negative count, that reads as flawless precision,
#      which is exactly backwards: it is a classifier that never commits.
#      The fix here is not a separate "abstention score" bolted on after the
#      fact; it falls out of the per-class math itself. Each class C is
#      scored one-vs-rest (true==C vs predicted==C), so a prediction of
#      UNKNOWN is simply "not C" for BOTH classes — it can never contribute
#      a true positive to either, only to the "actual positive but not
#      predicted" side (recall's denominator). An always-UNKNOWN classifier
#      therefore shows 0% recall on BOTH human and agent (every true
#      instance of each class went unpredicted) and "not computable"
#      precision on both (it never predicted either) — the exact opposite of
#      a flattering number, surfaced by the same arithmetic that grades a
#      real answer, not a special case for a bad one.
#
#   3. "SAID UNKNOWN" AND "SAID THE OTHER CLASS" ARE DIFFERENT FAILURES, so a
#      declined turn and a confidently wrong one must not collapse into one
#      undifferentiated "fn" count the way the binary classifiers' `fn`
#      does. Each class's `fn` here is split into `fn_declined` (predicted
#      UNKNOWN) and `fn_wrong` (confidently predicted the OTHER class) —
#      reported separately, summed for `fn` only where the existing
#      precision/recall math needs a single denominator. A classifier that
#      hedges (mostly `fn_declined`) and one that is confidently miscalibrated
#      (mostly `fn_wrong`) look identical on recall alone; they must not look
#      identical in this output.
#
# `unknown_pct` is the headline coverage number precisely so nobody has to
# reconstruct "how often did it even try" by hand from two per-class blocks.


def score_authorship(events, store: dict) -> dict | None:
    """Per-class (human, agent) precision/recall for
    `corpuslens.authorship.classify_turn`, re-run over `events` and compared
    to the ground truth in `store["authorship_labels"]`. Returns None if the
    store has no authorship judgments at all — same convention as `score`
    leaving a classifier out of `results` when nobody has labelled it, so a
    store that never touched authorship renders no authorship section rather
    than an empty or misleading one.

    Raises `AuthorshipUnavailable` if the store DOES have authorship
    judgments but `corpuslens.authorship` cannot be imported — there is no
    honest number to report without the classifier that would produce the
    predictions, and reporting ground truth alone would silently look like a
    result. Callers (the CLI) are expected to have already surfaced that
    error via `authorship_contract()` before reaching here; this function
    calls it too so it stays correct when used directly (as the tests do).

    `marked_machine`, passed to `classify_turn`, is derived from the Event's
    OWN `author_class` — the log's say-so about who wrote the turn. That is
    the exact quantity this whole feature exists to check the classifier
    against, independently, rather than trust: see corpuslens/authorship.py
    for why a turn's own logged author_class is a hint, not ground truth."""
    labels = store.get("authorship_labels") or []
    if not labels:
        return None
    mod = authorship_contract()
    by_ref = {e.source_ref: e for e in events}
    pairs = []
    missing = 0
    for rec in labels:
        e = by_ref.get(rec["source_ref"])
        if e is None:
            missing += 1
            continue
        y_true = rec["label"]
        marked_machine = e.author_class is AuthorClass.MACHINE
        y_pred = mod.classify_turn(dict(e.features), marked_machine=marked_machine)
        pairs.append((y_true, y_pred))
    result = _three_valued_scores(pairs, human=mod.HUMAN, agent=mod.AGENT, unknown=mod.UNKNOWN)
    result["missing"] = missing
    result["total_labels"] = len(labels)
    return result


def _three_valued_scores(pairs: list, human: str, agent: str, unknown: str) -> dict:
    """The per-class math described above. `pairs` is a list of
    (y_true, y_pred) where y_true is always `human` or `agent` (the ground
    truth a labeller can always give) and y_pred is `human`, `agent`, or
    `unknown` (the classifier's three-valued answer, including a decline)."""
    n = len(pairs)
    n_unknown = sum(1 for _, p in pairs if p == unknown)
    out = {
        "n": n,
        "unknown_n": n_unknown,
        "unknown_pct": round(100 * n_unknown / n, 1) if n else None,
    }
    if n == 0:
        out["unknown_note"] = ("not computable: no authorship-labelled turn in this "
                                "sample was found in the corpus")

    for name, this_class, other_class in (("human", human, agent), ("agent", agent, human)):
        tp = sum(1 for t, p in pairs if t == this_class and p == this_class)
        fp = sum(1 for t, p in pairs if t == other_class and p == this_class)
        fn_wrong = sum(1 for t, p in pairs if t == this_class and p == other_class)
        fn_declined = sum(1 for t, p in pairs if t == this_class and p == unknown)
        fn = fn_wrong + fn_declined
        tn = sum(1 for t, p in pairs if t == other_class and p != this_class)
        predicted_pos = tp + fp
        actual_pos = tp + fn
        precision = round(100 * tp / predicted_pos, 1) if predicted_pos else None
        recall = round(100 * tp / actual_pos, 1) if actual_pos else None
        cls = {
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "fn_wrong": fn_wrong, "fn_declined": fn_declined,
            "precision_pct": precision,
            "precision_denominator": f"labelled turns the classifier predicted {name} (tp+fp)",
            "recall_pct": recall,
            "recall_denominator": (f"labelled turns a human marked {name} (tp+fn — fn split "
                                    f"into predicted-{other_class} vs declined-unknown below)"),
        }
        if precision is None:
            cls["precision_note"] = f"not computable: the classifier never predicted {name} in this sample"
        if recall is None:
            cls["recall_note"] = f"not computable: no labelled turn in this sample was marked {name}"
        out[name] = cls
    return out
