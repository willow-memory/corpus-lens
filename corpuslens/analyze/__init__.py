"""Analyzer base + registry. Every analyzer declares its claims (checked
against the allowlist by the Guard) and its denominator (raw counts without a
denominator are rejected at registration — verification rule 1).

THE RESULT CONTRACT. An analyzer returns a dict of its numbers, and SHOULD
also return three presentation fields so a reader gets a finding rather than a
JSON dump:

  * `headline` — one sentence stating the result in words, in the second
    person. A statement of what was measured, never a verdict on the person:
    "70.0% of your prompt turns arrive mid-task", not "you are a good
    director". It must be readable without the table under it.
  * `n` — the count its denominator actually resolved to. The renderer uses it
    to mark a small sample, so this must be the SAME number the denominator
    string describes, not a larger one that happens to be handy.
  * `reading` — the direction guidance (which way is which), already present on
    most analyzers.

An analyzer that cannot compute returns `{"error": "<why>"}` and the renderer
says so in plain language rather than printing an empty section. Interpretation
lives HERE, beside the computation that knows what the denominator means, not
in the renderer — a renderer that knew each analyzer by name would have to be
edited every time one is added, and would drift from the filter it describes.

VERSION VS SCHEMA_VERSION — two different questions, easy to conflate:

  * `render.SCHEMA_VERSION` answers "what shape is the JSON document?" — the
    keys of the envelope (`schema_version`, `audit`, `results`, `caveat`) and
    of the audit record. It changes when the *document* changes shape.
  * `Analyzer.version` answers "what does THIS NUMBER mean?" — the classifiers,
    thresholds and filters this analyzer's semantics depend on. Two runs can
    share a `schema_version` (same document shape) and still be incomparable,
    because `composition_mix` version 1 measured "code-shaped line matches
    AUTHORED regex X" and version 2 measures it against a rewritten regex. The
    document didn't change; the number's meaning did. `corpuslens diff` (see
    `cli.py`) refuses to subtract two runs whose analyzer versions disagree,
    for exactly this reason — see IDEAS.md, "Metrics that stay comparable
    across tool versions".

  Bump `version` whenever a change to an analyzer's own code changes what a
  reader should infer from the number it already published — a classifier
  regex, a threshold (`BURST_S`, the 12-character floor, a day-gap bucket
  edge), or the shape of the filter feeding it. Do NOT bump it for a change
  that only affects presentation (`headline` wording, `reading` prose) or that
  fixes a bug in a way that makes the number CORRECT (the fixed number always
  wins; but if this run is compared against numbers computed before the fix,
  that comparison is exactly the "software changed, not you" case `diff` must
  catch — so bump it anyway).

MAINTENANCE DISCIPLINE: A version number nobody remembers to bump is worse
than no version number, because it *looks* like a real comparability
guarantee. `semantic_hash()` below exists to make forgetting loud instead of
silent: an analyzer module computes a hash of the literal patterns and
constants its number depends on (regex `.pattern` strings, thresholds, as
plain text) and pins that hash as a literal beside `version` in its
`register(...)` call. `tests/test_analyzer_versions.py` recomputes the hash
from the SAME live inputs and fails if it no longer matches the pinned
literal — which happens exactly when a classifier or threshold changed. The
fix for a failing test is a decision, not a keystroke: bump `version`,
recompute the hash, and paste the new value in — the test cannot make that
decision for you, it only refuses to let the decision go unmade.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable

_REGISTRY: list = []


def semantic_hash(*parts: str) -> str:
    """Stable, short hash of the literal strings an analyzer's semantics
    depend on (a classifier's `.pattern`, a threshold rendered as text). Order-
    sensitive and NUL-separated so two inputs can't collide by concatenation.

    This is not a security hash — 16 hex chars is plenty to catch an
    accidental drift and cheap to eyeball in a diff. Deliberately not memoized:
    it is meant to be recomputed by hand (or by the pinned test) whenever the
    inputs might have moved, never cached across a change.
    """
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


@dataclass(frozen=True)
class Analyzer:
    name: str
    claims: tuple                     # claim types this analyzer emits
    denominator: str                  # what every rate is out of — named, always
    run: Callable                     # (events) -> dict of results
    version: int = 1                  # ANALYZER SEMANTICS version — see module docstring
    semantic_hash: str = ""           # pinned hash of this version's classifiers/thresholds
    semantic_inputs: tuple = field(default_factory=tuple)   # the live inputs the hash covers


def register(name: str, claims: tuple, denominator: str, version: int,
             semantic_hash: str = "", semantic_inputs: tuple = ()):
    """`version` is required, on purpose — an analyzer's author has to make a
    deliberate choice rather than inherit a silent default. `semantic_hash` and
    `semantic_inputs` are optional (an analyzer with no classifier/threshold
    dependency, like `thread_span`, can leave them empty), but when either is
    given the other should be too — see `tests/test_analyzer_versions.py`."""
    if not denominator or not denominator.strip():
        raise ValueError(f"analyzer {name!r} names no denominator — raw counts are rejected")
    def deco(fn):
        _REGISTRY.append(Analyzer(name=name, claims=claims, denominator=denominator, run=fn,
                                  version=version, semantic_hash=semantic_hash,
                                  semantic_inputs=tuple(semantic_inputs)))
        return fn
    return deco


def all_analyzers() -> list:
    return list(_REGISTRY)


from . import steering, composition, tempo  # noqa: E402,F401
