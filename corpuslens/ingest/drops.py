"""Closed vocabulary of drop reasons, and `DropCounts` — the third element of
an adapter's return tuple.

WHY THIS EXISTS (BUGS.md, Open #1, now Fixed). `doctor` used to warn whenever
more than half of all records read were dropped, with no distinction between
two very different things: a record that was never a turn BY DESIGN (tool
traffic, a thinking block, an attachment, harness bookkeeping) and a record
that SHOULD have been a turn and failed (an unparseable line, a record with
no usable timestamp, an unrecognised role, an empty turn). On a modern agentic
corpus the first bucket dwarfs the second, so the old single `int` made a
93.7%-dropped, nothing-wrong corpus look identical to a genuinely broken run.

THE CONTRACT CHANGE. `ingest/__init__.py`'s adapter contract widens its third
element from a bare `int` to this module's `DropCounts` — still always the
same 3-tuple `(events, quarantine, drops)` for every adapter, every call
(never a 4-tuple, never a flag that changes the shape). `DropCounts` is a
small stdlib dataclass, not a bigger object graph, and it keeps a `.total`
property so any code that only ever needed the old aggregate number still has
one line to get it — the widening is additive, not a silent behavior change
to code that only wants "how many records vanished". Code that wants the new
distinction reads `.structural` / `.malformed` / `.as_dict()` instead.

CLOSED, ENUMERATED REASONS, ON PURPOSE (same discipline as `taxonomy.json`
and `share.RATE_FIELDS`). A reason is always one of the fixed strings below,
chosen by an adapter because it recognises a SHAPE (a block type, a record
kind, a role string) — never a string read out of the corpus itself. That
matters for two reasons: it keeps the vocabulary small enough for a human to
read at a glance, and it means a per-reason breakdown can be published (even
banded, in share mode) without smuggling corpus content through a "reason"
field. Adding a reason is a deliberate, reviewable, one-line act, same as
adding to `RATE_FIELDS`; the default for anything an adapter cannot place is
`UNKNOWN_REASON`, never a guess and never the raw value that triggered it.

TWO CLASSES, one question each:
  * STRUCTURAL — "not a turn by design". Normal. No reason to distrust
    anything computed from the turns that were kept.
  * MALFORMED  — "should have been a turn and failed". This is the number a
    reader should judge a corpus by; `doctor` warns on this share, not on the
    combined total (see `cli._diagnose`).

An adapter that cannot distinguish a drop's reason more precisely than "not a
turn" or "should have been a turn but wasn't" reports `NOT_A_TURN_RECORD` or
`UNKNOWN_REASON` respectively — under-claiming the reason beats guessing one,
the same rule this project applies to classifiers (CONTRIBUTING.md)."""
from __future__ import annotations

from dataclasses import dataclass, field

STRUCTURAL = "structural"    # not a turn by design
MALFORMED = "malformed"      # should have been a turn and failed

# ── the closed vocabulary ────────────────────────────────────────────────────
TOOL_TRAFFIC = "tool_traffic"                 # tool_use/tool_result blocks or roles
THINKING = "thinking"                         # a thinking / redacted_thinking block
ATTACHMENT = "attachment"                     # an image/document block, or an
                                              # attachment-typed record
HARNESS_BOOKKEEPING = "harness_bookkeeping"   # ai-title, atis-latch, last-prompt,
                                              # queue-operation, mode, session
                                              # metadata, and similar harness state
SUBAGENT = "subagent"                         # dispatched/sidechain traffic — the
                                              # model's own delegate, not the owner
COMPACTION_SUMMARY = "compaction_summary"     # the runtime's own précis of the
                                              # thread so far, handed back as a turn
NOT_A_TURN_RECORD = "not_a_turn_record"       # a recognised non-turn record kind an
                                              # adapter cannot name any more precisely
                                              # than "this ledger/store kind is not a
                                              # turn" (e.g. a checkpoint ledger's
                                              # `seal`/`reject_*` lines, a protobuf
                                              # tool-step blob, a non-`user` role in an
                                              # adapter that only extracts operator text)

UNREADABLE_FILE = "unreadable_file"           # the file/db/store could not be opened
                                              # or read at all
UNPARSEABLE_LINE = "unparseable_line"         # a line/row/blob did not decode into the
                                              # shape this adapter expects
MISSING_TIMESTAMP = "missing_timestamp"       # no usable date/clock on an otherwise
                                              # turn-shaped record
UNRECOGNIZED_ROLE = "unrecognized_role"       # a role/type string outside this
                                              # adapter's closed role vocabulary
EMPTY_TURN = "empty_turn"                     # turn-shaped, dated, correctly roled —
                                              # and empty after de-injection
UNKNOWN_REASON = "unknown_reason"             # the adapter genuinely cannot tell
                                              # structural from malformed here; honest
                                              # under-claim, never a guess

STRUCTURAL_REASONS = (
    TOOL_TRAFFIC, THINKING, ATTACHMENT, HARNESS_BOOKKEEPING, SUBAGENT,
    COMPACTION_SUMMARY, NOT_A_TURN_RECORD,
)
MALFORMED_REASONS = (
    UNREADABLE_FILE, UNPARSEABLE_LINE, MISSING_TIMESTAMP, UNRECOGNIZED_ROLE,
    EMPTY_TURN, UNKNOWN_REASON,
)
REASONS = STRUCTURAL_REASONS + MALFORMED_REASONS

_REASON_CLASS = {r: STRUCTURAL for r in STRUCTURAL_REASONS}
_REASON_CLASS.update({r: MALFORMED for r in MALFORMED_REASONS})


def reason_class(reason: str) -> str:
    """STRUCTURAL | MALFORMED for a known reason; raises for an unknown one —
    fail closed, the same posture as `Guard.release` on an unknown capability."""
    if reason not in _REASON_CLASS:
        raise ValueError(f"unknown drop reason {reason!r} — add it to "
                         f"ingest/drops.py deliberately, it is a closed vocabulary")
    return _REASON_CLASS[reason]


@dataclass
class DropCounts:
    """Every dropped record for one adapter call, tallied by CLOSED reason.
    This is the third element of an adapter's return 3-tuple, replacing the
    bare `int` the contract used to require — see this module's docstring for
    why, and `ingest/__init__.py` for the contract statement itself.

    Construct with `DropCounts()` and accumulate via `.add(reason, n)`, or
    combine two adapters' counts (a per-file loop feeding a shared assembler,
    e.g. `_rows.assemble`) via `.merge(other)`. Both fail closed on an
    unrecognised reason string, exactly like `Guard.release` on an unknown
    capability — a typo in a reason name must be loud, not silently counted
    under a reason nobody asked for."""
    by_reason: dict = field(default_factory=dict)

    def add(self, reason: str, n: int = 1) -> None:
        reason_class(reason)   # raises on an unrecognised reason; discards nothing
        if n:
            self.by_reason[reason] = self.by_reason.get(reason, 0) + n

    def merge(self, other: "DropCounts") -> "DropCounts":
        for reason, n in other.by_reason.items():
            self.add(reason, n)
        return self

    @property
    def total(self) -> int:
        """The old single number, for any reader that only ever wanted the
        aggregate — `len(events) + drops.total` still answers "how many
        records did this adapter see in total"."""
        return sum(self.by_reason.values())

    @property
    def structural(self) -> int:
        """Not a turn by design. Normal; no reason to distrust anything."""
        return sum(n for r, n in self.by_reason.items() if _REASON_CLASS[r] == STRUCTURAL)

    @property
    def malformed(self) -> int:
        """Should have been a turn and failed. The number `doctor` warns on."""
        return sum(n for r, n in self.by_reason.items() if _REASON_CLASS[r] == MALFORMED)

    def as_dict(self) -> dict:
        """{reason: count}, omitting reasons with a zero count — stable key
        set (the enumerated vocabulary above), safe to serialize as-is and,
        in share mode, to band value-by-value (see `share.band_dropped_by_reason`)."""
        return dict(self.by_reason)

    def __bool__(self) -> bool:
        return self.total > 0
