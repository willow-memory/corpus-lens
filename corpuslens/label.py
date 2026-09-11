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
    return {"classifier_version": None, "labels": []}


def load_store(path) -> dict:
    """The store at `path`, or an empty one if it does not exist yet. Never
    raises on a missing file — a first `corpuslens label` run creates it."""
    p = Path(path)
    if not p.exists():
        return empty_store()
    with p.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "labels" not in data:
        raise ValueError(f"{path} does not look like a corpuslens label store "
                          f"(expected an object with a 'labels' list)")
    return {"classifier_version": data.get("classifier_version"),
            "labels": list(data.get("labels", []))}


def save_store(path, store: dict) -> None:
    """Writes exactly {classifier_version, labels: [{source_ref, classifier,
    label}, ...]} — nothing else is ever added to this dict on the way out,
    so a future field cannot smuggle content in by accident."""
    labels = [{"source_ref": r["source_ref"], "classifier": r["classifier"],
               "label": bool(r["label"])} for r in store["labels"]]
    out = {"classifier_version": store.get("classifier_version"), "labels": labels}
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


def already_labelled(store: dict) -> set:
    return {(r["source_ref"], r["classifier"]) for r in store["labels"]}


def add_label(store: dict, source_ref: str, classifier: str, label: bool,
              version: str = CLASSIFIER_SET_VERSION) -> None:
    store["classifier_version"] = version
    store["labels"].append({"source_ref": source_ref, "classifier": classifier,
                            "label": bool(label)})


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
