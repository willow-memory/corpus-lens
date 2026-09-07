"""Adapter registry. An adapter ingests one corpus format and returns
(events, quarantine, dropped). Raw absolute timestamps are consumed INSIDE the
adapter to compute day offsets and deltas, then discarded — they never leave on
an Event. Content is consumed to derive process features, then discarded.

Each adapter also declares the KIND of source it reads via `register(..., source=)`:
  * "dir" — a directory tree of session files (claude-code, cursor)  [default]
  * "file" — a single file, e.g. a SQLite .db (sqlite)
  * "dsn"  — a connection string, not a filesystem path (postgres)
The CLI reads this to validate the argument correctly instead of assuming a
directory, so a DB corpus (a file, or a DSN) is not rejected as "not a dir"."""
from __future__ import annotations

from ..model import Event, Quarantine

_REGISTRY: dict = {}
_SOURCE: dict = {}


def register(name: str, source: str = "dir"):
    def deco(fn):
        _REGISTRY[name] = fn
        _SOURCE[name] = source
        return fn
    return deco


def get(name: str):
    if name not in _REGISTRY:
        raise KeyError(f"no adapter {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def source_of(name: str) -> str:
    """'dir' | 'file' | 'dsn' — the kind of argument this adapter expects."""
    return _SOURCE.get(name, "dir")


def available() -> list[str]:
    return sorted(_REGISTRY)


from . import claude_code, cursor, cursor_store, sqlite, postgres  # noqa: E402,F401  (registration side effects)
