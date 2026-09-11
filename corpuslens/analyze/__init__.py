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
edited every time one is added, and would drift from the filter it describes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

_REGISTRY: list = []


@dataclass(frozen=True)
class Analyzer:
    name: str
    claims: tuple           # claim types this analyzer emits
    denominator: str        # what every rate is out of — named, always
    run: Callable           # (events) -> dict of results


def register(name: str, claims: tuple, denominator: str):
    if not denominator or not denominator.strip():
        raise ValueError(f"analyzer {name!r} names no denominator — raw counts are rejected")
    def deco(fn):
        _REGISTRY.append(Analyzer(name=name, claims=claims, denominator=denominator, run=fn))
        return fn
    return deco


def all_analyzers() -> list:
    return list(_REGISTRY)


from . import steering, composition, tempo  # noqa: E402,F401
