"""Structural egress scan — the second gate at the output door.

WHY THIS EXISTS, AND WHY IT IS NOT A DUPLICATE OF `Guard.scan_egress`.

`Guard.scan_egress` checks the rendered report for quarantined LITERALS: the
exact `base_date_iso`, the exact `local_tz`, the exact filenames in `ref_map`.
That is precise and cheap, and it has a structural blind spot that this
project has now been bitten by three times (see BUGS.md and
`tests/test_wall.py::DiscoveredPathStructuralGuardTests`): **a value that was
never quarantined cannot be in the literal list**, so the literal scan cannot
see it. The shipped `discovered_path` leak put the owner's real username one
clause away from the words "no filename left the wall", and the literal scan
was looking straight at it.

The fix that shipped for that bug was a `__setattr__` guard on one field. This
module is the general form of the same idea: instead of asking "is this the
value we hid?", it asks **"is this the SHAPE of something the wall promises is
not here?"** — a home-directory path, an email address, a calendar date, a
weekday name, an IANA timezone, a wall-clock time. A field invented by a
future analyzer is, by construction, not in any quarantine — but if it carries
one of these shapes, this catches it.

Borrowed from redential-cli's `src/secret-scan.ts` (Apache-2.0, same license
as this repo), which scans its FINAL serialized bundle rather than its inputs,
and whose two load-bearing details are kept here:

  1. The caller cannot accidentally ignore the result — `Guard.scan_egress`
     raises rather than returning a verdict to be discarded.
  2. **The report names the pattern, never the matched text.** A gate that
     echoed what it caught would itself become the leak — the same rule
     `tests/test_wall.py::test_error_never_echoes_the_leaked_value` already
     holds the literal scan to.

WHAT THIS DOES NOT CLAIM. It is a regression net for shapes the wall already
promises are absent, not a general-purpose PII detector, and not a second wall.
A leak that looks like none of these shapes passes it. It exists so that the
NEXT never-quarantined value does not have to be found by an auditor reading
the code; it does not make the output safe on its own, and no docstring, help
string, or audit sentence may say that it does.

GRANT-AWARENESS. Three of these shapes are exactly what a released capability
legitimately puts in the report, so they are gated the same way the literal
scan is: under `calendar_time` a real date, weekday, and clock time may appear;
under `local_tz` a timezone may. A home path and an email address are gated by
NOTHING — no capability in `KNOWN_CAPABILITIES` grants them, so they are
refused on every path, in every profile.
"""
from __future__ import annotations

import re

#: (label, gating capability or None, pattern). A shape whose gating capability
#: was released this run is allowed through; `None` means never allowed.
#:
#: Kept deliberately narrow and low-noise: every pattern here should be
#: impossible in correct process-only output, so a hit is a bug and not a
#: judgement call. Adding one is a deliberate, reviewable act — and adding one
#: that CAN fire on honest output would train readers to ignore the gate.
STRUCTURAL_SHAPES: list[tuple[str, str | None, re.Pattern]] = [
    # A resolved home directory carries the owner's real username. This is the
    # exact shape of the `discovered_path` bug. The declared, unexpanded `~/...`
    # convention the audit record permits does not match any of these.
    ("home directory path", None, re.compile(r"(?:/home/|/Users/|[A-Za-z]:\\Users\\)[^/\\\s\"']+")),
    # No report field holds an address; the corpus's own content never reaches
    # an analyzer, so one appearing here means content or identity crossed.
    ("email address", None, re.compile(r"\b[^\s@\"']+@[^\s@\"']+\.[A-Za-z]{2,}\b")),
    # The absolute calendar anchor, in the three shapes it actually takes.
    ("calendar date", "calendar_time", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    (
        "weekday name",
        "calendar_time",
        re.compile(
            r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",
            re.IGNORECASE,
        ),
    ),
    # Wall-clock time. The README discloses that a long thread's cumulative
    # span loosely BOUNDS local time-of-day; it promises no clock hour is
    # printed, and this holds that promise to the letter.
    ("wall-clock time", "calendar_time", re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")),
    # Matched against real IANA top-level areas rather than a generic
    # `Word/Word`, so an adapter or analyzer name with a slash in it cannot
    # trip the gate.
    (
        "IANA timezone",
        "local_tz",
        re.compile(
            r"\b(?:Africa|America|Antarctica|Arctic|Asia|Atlantic|Australia|Europe|Indian|Pacific|Etc)"
            r"/[A-Za-z][A-Za-z_+\-]*"
        ),
    ),
]


def find_structural_leaks(text: str, released_caps: frozenset | set = frozenset()) -> list[str]:
    """LABELS of the shapes present in `text` that no released capability
    accounts for — never the matched text itself, so the return value of this
    function is safe to put in an error, a log, or an audit record.

    Pure and side-effect free, so it is testable on its own; the enforcing
    caller is `Guard.scan_egress`, which raises.
    """
    return [
        label
        for label, cap, pattern in STRUCTURAL_SHAPES
        if (cap is None or cap not in released_caps) and pattern.search(text)
    ]
