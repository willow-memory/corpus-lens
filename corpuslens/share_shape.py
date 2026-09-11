"""Share-payload shape assertion — the second, distinct check
`DESIGN-guard-extraction.md` (2a, "Share mode") names as still missing.

WHY THIS EXISTS, AND WHY IT IS NOT A DUPLICATE OF `Guard.scan_egress`.

`scan_egress` (both its literal and structural phases) operates on the
RENDERED TEXT of a report and asks "does a quarantined value, or the shape of
one, appear here?" Share mode's coarsening (`corpuslens/share.py`) never
touches the Quarantine at all — it bands numbers and drops fields on an
already-computed results dict — so `scan_egress` has nothing to say about
whether the coarsening itself was done correctly. That gap was not
hypothetical: the audit note in `DESIGN-guard-extraction.md` records that a
first implementation of share mode banded every analyzer's `n` correctly but
still published the corpus's exact `n_events` through the audit record, and
`scan_egress` passed the output cleanly the entire time, because an exact `n`
is neither a quarantined literal nor a recognizable structural shape (no
date, no path, no timezone) — it is just a number, and "is this number too
identifying" is not a question either phase of `scan_egress` can answer, or
was ever built to answer.

THE QUESTION THIS MODULE ANSWERS INSTEAD, WHICH IS DECIDABLE: not "is this
value too identifying" (unanswerable — this project explicitly does not
measure re-identification risk, see `share.py`'s docstring), but "is every
field in this payload one this project has reviewed and allowlisted, and
does every denominator in it read as a band rather than an exact count?"
Both halves are checked on STRUCTURE — key names and value types — never by
recognizing or comparing against real data. That is what makes the question
decidable where "is this too identifying" is not.

FAIL CLOSED, same posture as `share.coarsen_result` and `egress_shapes`: an
unrecognized key is a violation, not a silent pass. A future analyzer's new
field is, by construction, not on `share.RATE_FIELDS` or `ALLOWED_AUDIT_KEYS`
below until someone reviews it and adds it there — so it is caught here even
if `coarsen_result`'s own allowlist filter has a bug that let it through, and
even if a future edit adds a new key to the audit record's `as_dict()` without
updating this module. Two independent fail-closed filters checking the same
property is the point, not redundancy to trim.

WHAT THIS DOES **NOT** CLAIM. It verifies that the coarsening step RAN and
produced the expected SHAPE — every key allowlisted, every denominator a
band. It has no way to know, and does not claim to know, whether what remains
still fingerprints its owner: that question is explicitly unmeasured by this
project (see `share.py`). This module does not make share output safe,
anonymous, or de-identified, and nothing that reports its result may say
otherwise.

Mirrors `egress_shapes.find_structural_leaks` and `failure_classes.classify`:
a pure, side-effect-free function that returns a list of violation LABELS —
key names and field-shape descriptions, never a payload value — so its
result is always safe to put in an error, a log, or an audit record. The
enforcing caller (`Guard.scan_share_shape`, in `guard.py`) raises; this
module never does.
"""
from __future__ import annotations

import re

from .share import RATE_FIELDS

#: Fields `share.coarsen_result` itself may emit, beyond the reviewed rate
#: fields. `n` is deliberately ABSENT: coarsening always renames it to
#: `n_band`, so a bare `n` surviving into a share result is itself a
#: violation (checked explicitly below, not just by omission from this set).
_RESULT_META_FIELDS = frozenset({"denominator", "n_band", "headline", "error"})

#: Everything a share-mode analyzer result may carry. Adding to this is the
#: same deliberate, reviewable, one-line act `share.RATE_FIELDS` already is —
#: see that module's docstring for why the default is exclusion.
ALLOWED_RESULT_FIELDS: frozenset = _RESULT_META_FIELDS | RATE_FIELDS

#: Everything `guard.AuditRecord.as_dict()` may carry in share mode. Kept as
#: its own reviewed list rather than introspecting `AuditRecord` at runtime —
#: a field added to the dataclass without a matching review here must fail
#: closed, not pass because the dataclass happened to grow a slot for it.
ALLOWED_AUDIT_FIELDS: frozenset = frozenset({
    "profile", "adapter", "discovered_path", "granted", "denied",
    "analyzers_run", "analyzers_refused", "n_events", "n_dropped",
    "filters", "n_filtered", "subject", "subject_reason", "subject_consent",
    "sentence",
})

#: Keys whose value is a denominator-shaped count. Each MUST hold a band
#: string (`share.band_n`'s output shape) once coarsening has run — never an
#: exact int. `n` is included even though a correctly coarsened payload never
#: has it (see `_RESULT_META_FIELDS` above): if one appears, that is exactly
#: the "forgot to band" bug this module exists to catch, not an unrecognized
#: field to report as the softer violation.
_DENOMINATOR_FIELDS = frozenset({"n", "n_band", "n_events", "n_dropped", "n_filtered"})

#: The exact shape `share.band_n` produces. A value under a denominator field
#: that does not match this is a violation regardless of its type — an exact
#: int fails it, but so would a hand-written string that merely looks close.
_BAND_PATTERN = re.compile(r"^(?:<\d+|\d+-\d+|\d+\+|unknown)$")


def _is_band_string(value) -> bool:
    return isinstance(value, str) and bool(_BAND_PATTERN.match(value))


def _check_denominator_field(key: str, value, where: str, violations: list) -> None:
    if key == "n":
        violations.append(
            f"exact denominator field 'n' present in {where} — coarsening "
            "renames n to n_band; a bare 'n' surviving means it did not run"
        )
        return
    if not _is_band_string(value):
        kind = "an exact integer" if isinstance(value, int) and not isinstance(value, bool) else "not a band"
        violations.append(f"'{key}' in {where} is {kind}, not a coarsened band")


def _check_result_fields(name: str, result: dict, violations: list) -> None:
    where = f"share result for analyzer '{name}'"
    if not isinstance(result, dict):
        violations.append(f"{where} is not a mapping")
        return
    for key, value in result.items():
        if key in _DENOMINATOR_FIELDS:
            _check_denominator_field(key, value, where, violations)
            continue
        if key not in ALLOWED_RESULT_FIELDS:
            violations.append(f"unrecognized field '{key}' in {where}")
            continue
        if isinstance(value, dict):
            # A rate/meta field is a scalar by construction (share.coarsen_result
            # only ever keeps int/float/str leaves) — a nested mapping under an
            # otherwise-allowlisted key is not a shape this project reviewed.
            violations.append(f"'{key}' in {where} is a nested structure, not a scalar")


def _check_audit_fields(audit: dict, violations: list) -> None:
    where = "the coarsened audit record"
    if not isinstance(audit, dict):
        violations.append(f"{where} is not a mapping")
        return
    for key, value in audit.items():
        if key in _DENOMINATOR_FIELDS:
            _check_denominator_field(key, value, where, violations)
            continue
        if key not in ALLOWED_AUDIT_FIELDS:
            violations.append(f"unrecognized field '{key}' in {where}")


def find_shape_violations(results: dict, audit: dict) -> list[str]:
    """The structural check share mode was missing.

    `results` is `share.coarsen(...)`'s output (analyzer name -> coarsened
    result dict); `audit` is a coarsened `guard.AuditRecord.as_dict()`.
    Returns violation LABELS naming the field and what is wrong with its
    shape — never the value that was there, so the result is always safe to
    surface in an error or an audit trail. Empty list means every key present
    is allowlisted and every denominator reads as a band.

    Pure and side-effect free, like `egress_shapes.find_structural_leaks`;
    the enforcing caller is `Guard.scan_share_shape`, which raises.
    """
    violations: list = []
    if not isinstance(results, dict):
        violations.append("share results payload is not a mapping")
    else:
        for name, result in results.items():
            _check_result_fields(name, result, violations)
    _check_audit_fields(audit, violations)
    return violations
