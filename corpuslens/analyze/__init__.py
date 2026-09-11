"""Analyzer base + registry. Every analyzer declares its claims (checked
against the allowlist by the Guard) and its denominator (raw counts without a
denominator are rejected at registration — verification rule 1)."""
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
