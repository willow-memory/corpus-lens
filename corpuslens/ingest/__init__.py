"""Adapter registry. An adapter ingests one corpus format and returns
(events, quarantine, drops) — ALWAYS this exact 3-tuple, for every call.
Raw absolute timestamps are consumed INSIDE the adapter to compute day
offsets and deltas, then discarded — they never leave on an Event. Content is
consumed to derive process features, then discarded.

`drops` is a `drops.DropCounts` (see `ingest/drops.py`), not a bare `int` —
this is a deliberate widening of the contract (BUGS.md, Open #1, now Fixed).
The old single number conflated two different things: a record that was
never a turn BY DESIGN (tool traffic, a thinking block, an attachment,
harness bookkeeping) and a record that SHOULD have been a turn and failed
(an unparseable line, a missing timestamp, an unrecognised role, an empty
turn). On a modern agentic corpus the first bucket dwarfs the second, so a
single "93.7% dropped" number told a reader nothing was trustworthy when in
fact every drop was correct. `DropCounts` keeps that distinction (`.structural`
/ `.malformed`) plus a full reason breakdown (`.as_dict()`), while still
exposing `.total` so a caller that only ever wanted the old aggregate number
has one line to get it back (`drops.total`, in place of the old bare
variable) — the widening is additive to what a 3-tuple carries, never a
change in how many elements it has, and never a keyword that changes its
shape. A DATACLASS was chosen over widening the tuple to 4 elements (events,
quarantine, structural, malformed) because a 4-tuple would still need a
reason breakdown for `doctor` and for share-mode banding, which means either
a 5th element or a nested structure inside one of the four anyway — better to
keep the tuple's arity exactly as documented and put the new richness inside
the one element whose job this always was. Every adapter below constructs one
`DropCounts` and returns it as the tuple's third element; an adapter that
cannot tell a drop's reason apart from another reports the closed-vocabulary
`NOT_A_TURN_RECORD` (structural) or `UNKNOWN_REASON` (malformed) bucket rather
than inventing a label — see `ingest/drops.py`'s module docstring for the
full vocabulary and why it is closed.

Each adapter also declares the KIND of source it reads via `register(..., source=)`:
  * "dir" — a directory tree of session files (claude-code, cursor)  [default]
  * "file" — a single file, e.g. a SQLite .db (sqlite)
  * "dsn"  — a connection string, not a filesystem path (postgres)
The CLI reads this to validate the argument correctly instead of assuming a
directory, so a DB corpus (a file, or a DSN) is not rejected as "not a dir".

A "dir" adapter also declares the FILE PATTERN it walks (`pattern=`), because
they are not all `*.jsonl`: cursor-store walks a tree of `store.db` files. The
CLI counts matches of that pattern so "no files found under X" names the thing
it actually looked for, instead of reporting a `*.jsonl` count for an adapter
that never wanted one.

A THIRD registry (`register_default_path` / `default_path_of` / `discoverable`)
holds each "dir" adapter's CONVENTIONAL location on a real machine — e.g.
claude-code's session logs live at `~/.claude/projects` unless the user says
otherwise. This is what `corpuslens run` with no arguments reads to find a
first corpus: it is declared here, per adapter, precisely so that adding a
new directory adapter that knows where it conventionally lives never means
editing the CLI's discovery logic — the adapter says where to look, the CLI
just asks every adapter that has an answer. An adapter with no conventional
location (e.g. `cursor`, whose sessions live wherever the user happens to
keep them) simply never calls `register_default_path` and is not offered for
discovery; that is a fact about the adapter, not a special case in the CLI.

A FOURTH registry (`register_unmeasurable` / `unmeasurable_of`) lets an
adapter DECLARE, by name and with a reason, the analyzers its corpus cannot
feed with a meaningful number — not "cannot compute" (an analyzer already
returns `{"error": ...}` for that) but "computes a number that measures
nothing here": a corpus of checkpoints has no opening prompt, so
`steering_density`'s mid-task share is 100% by construction. `cli.run`
refuses a declared analyzer before it runs and names it in the audit
sentence, and `doctor` lists it, because a plausible number over a corpus
that cannot mean it is the `subagents/` bug (BUGS.md) again — this is that
lesson taken at the adapter's door. The declaration is per adapter and
never per run: a CLI flag that turned it off would be a flag that turned a
refusal into a finding.

A SEPARATE, smaller registry (`register_label_text` / `get_label_text` /
`text_capable_of`) holds label-text lookups: a differently-shaped function,
`label_text(path, ...) -> LabelCorpus`, that `corpuslens label` uses to get a
turn's own text to show a human — never written to disk, never on an `Event`.
It is deliberately NOT a mode of `register()`/`get()`: the main adapter
contract above must always return the same 3-tuple no matter what a caller
asks for, so a keyword can never change its shape (that shape-changes-under-a-
flag mistake is exactly what this split avoids — see `claude_code.ingest` vs.
`claude_code.label_text`). Only `claude-code` registers a label-text function
today; `label` refuses loudly on any adapter that has not, rather than
guessing at a text-extraction convention nobody has implemented or tested."""
from __future__ import annotations

from ..model import Event, Quarantine

_REGISTRY: dict = {}
_SOURCE: dict = {}
_PATTERN: dict = {}
_LABEL_TEXT: dict = {}
_DEFAULT_PATH: dict = {}
_UNMEASURABLE: dict = {}


def register(name: str, source: str = "dir", pattern: str = "*.jsonl"):
    def deco(fn):
        _REGISTRY[name] = fn
        _SOURCE[name] = source
        _PATTERN[name] = pattern
        return fn
    return deco


def get(name: str):
    if name not in _REGISTRY:
        raise KeyError(f"no adapter {name!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def source_of(name: str) -> str:
    """'dir' | 'file' | 'dsn' — the kind of argument this adapter expects."""
    return _SOURCE.get(name, "dir")


def pattern_of(name: str) -> str:
    """The filename glob a 'dir' adapter walks (meaningless for file/dsn)."""
    return _PATTERN.get(name, "*.jsonl")


def available() -> list[str]:
    return sorted(_REGISTRY)


def register_label_text(name: str):
    """Registers `fn` as the `label_text(path, corpus_id=...) -> LabelCorpus`
    function for adapter `name`, used only by `corpuslens label`. This is its
    own registry rather than a flag on `register()` above, on purpose: the
    general adapter contract (`get(name)(path, ...)` -> a 3-tuple) must never
    change shape depending on what a caller passes, and a label-text lookup
    needs a different, richer shape (see `LabelCorpus` in `claude_code.py`) —
    so it gets its own function and its own registry instead."""
    def deco(fn):
        _LABEL_TEXT[name] = fn
        return fn
    return deco


def get_label_text(name: str):
    if name not in _LABEL_TEXT:
        raise KeyError(f"adapter {name!r} has no label-text support; "
                       f"available: {sorted(_LABEL_TEXT)}")
    return _LABEL_TEXT[name]


def text_capable_of(name: str) -> bool:
    """True iff `corpuslens label` can show turn text for this adapter (i.e.
    a `label_text` function is registered for it)."""
    return name in _LABEL_TEXT


def register_default_path(name: str, path: str):
    """Declares the CONVENTIONAL location adapter `name` (a "dir" adapter)
    reads from on a real machine, e.g. `~/.claude/projects` for claude-code.
    Used only by `corpuslens run` with no arguments to find a first corpus —
    it never changes what `get(name)` does or what argument it expects.

    A decorator, like `register()` and `register_label_text()` above, so an
    adapter module can declare it right next to the `ingest()` function it
    describes:

        @register_default_path("claude-code", "~/.claude/projects")
        @register("claude-code")
        def ingest(path, ...): ...

    `path` is stored as written (with the leading `~`, unexpanded) — the CLI
    expands and validates it at discovery time, against the actual `$HOME` of
    the machine it is running on, never against this module's import-time
    environment."""
    def deco(fn):
        _DEFAULT_PATH[name] = path
        return fn
    return deco


def default_path_of(name: str) -> str | None:
    """The conventional path registered for `name`, or None if it declared
    none (e.g. `cursor`, which has no fixed on-disk home)."""
    return _DEFAULT_PATH.get(name)


def register_unmeasurable(name: str, analyzers: dict):
    """Declares `{analyzer_name: why}` for adapter `name`: analyzers whose
    result over this corpus would be a number that measures nothing (see the
    module docstring). A decorator, declared beside the `ingest()` it
    describes. `why` is printed verbatim in the audit sentence, so write it
    for a reader who does not know the corpus."""
    def deco(fn):
        _UNMEASURABLE[name] = {str(k): str(v) for k, v in dict(analyzers).items()}
        return fn
    return deco


def unmeasurable_of(name: str) -> dict:
    """`{analyzer_name: why}` for adapter `name`; `{}` when it declared none."""
    return dict(_UNMEASURABLE.get(name, {}))


def discoverable() -> list[str]:
    """Adapters `corpuslens run` (no arguments) can look for on its own,
    sorted so discovery order is deterministic and independent of module
    import order."""
    return sorted(_DEFAULT_PATH)


from . import claude_code, cursor, cursor_store, gemini_cli, sqlite, postgres, forge  # noqa: E402,F401  (registration side effects)
