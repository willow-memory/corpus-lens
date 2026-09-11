"""Adapter: Cursor's on-disk chat store — a tree of `store.db` SQLite files.

This is the corpus the `cursor` adapter cannot see. Cursor keeps each chat in
its own directory under `~/.cursor/chats/<workspace>/<agent-id>/`, holding
`store.db` plus a sibling `meta.json`. Point this adapter at the tree; it walks
`**/store.db`, one database per thread.

WHAT IS IN THERE (reverse-engineered from the store itself, 2026-09-07 — Cursor
publishes no schema, so every rule below is a read of real bytes, not a spec):

  * `blobs(id, data)` is a content-addressed heap holding two different things.
  * A blob whose first byte is `{` is **plain JSON**: `{"role", "content"}`,
    optionally `id` / `providerOptions`. Roles seen: user, assistant, tool,
    system. This is the conversation — and it carries NO timestamp.
  * Every other blob is **protobuf** (no schema shipped, so it is walked on the
    wire format alone). Inside, field 2 holds step records; a step carries
    field 57 (a call id), field 59 (start, ms epoch) and field 60 (end, ms).
    These are the only per-event clocks in the store, and they are tool steps.
  * `meta` (one hex-encoded JSON row) and the sibling `meta.json` carry
    `createdAt` / `createdAtMs` — the thread's own start.

THE HONEST CONSEQUENCE, STATED PLAINLY: this store does not timestamp the
operator's turns. It timestamps tool steps. So a prompt is dated by the last
LOGGED moment at or before it — the thread's start, or the most recent tool
step above it in insertion order — and its `delta_prev_s` is **None**, always.
Interpolating a plausible clock for a prompt would be inventing time, and time
is exactly what the wall exists to govern; a fabricated tempo would be
indistinguishable from a measured one downstream. Tool steps, which do carry a
real clock, get real deltas. `tempo` over this corpus therefore describes the
machine's step rate, never the operator's typing rhythm.

Provenance rule, same as every adapter here: dates come from log fields only —
`meta.json`'s `createdAtMs` and the protobuf step clocks — never from a date
found inside message content.

Robustness, same discipline: every blob that cannot become an Event is COUNTED
toward `dropped`, never silently discarded; a malformed blob, an encrypted one
(the store's `meta` names a `blobEncryptionKey`; encrypted payloads simply fail
to decode and are counted), an unreadable or non-SQLite file degrades to counted
drops and the walk continues. The database is opened READ-ONLY (`mode=ro`), so
pointing the lens at a live Cursor never mutates it.

Thread identity is the store's path RELATIVE TO THE ROOT, so two chats under
different workspaces stay distinct. `meta.json`'s `title` and `cwd` are read but
never emitted — a chat title is content and a cwd is a filesystem identity;
neither belongs on an Event.
"""
from __future__ import annotations

import datetime
import json
import sqlite3
from pathlib import Path

from ..model import AuthorClass, CoarseTime, DataType, Event, Quarantine, Surface
from . import register, register_default_path
from ..classifiers import _features, _hash
from .injection import authored_text

#: Plausible ms-epoch window. A varint outside it is not a clock — it is a
#: length, an enum, or a token count that happens to be large.
_MS_LO = 1_500_000_000_000   # 2017-07
_MS_HI = 2_000_000_000_000   # 2033-05

#: Protobuf field numbers, named from what the bytes actually hold.
_F_STEPS = 2       # outer: repeated step record
_F_CALL_ID = 57    # step: provider call id
_F_START_MS = 59   # step: start, ms epoch
_F_END_MS = 60     # step: end, ms epoch

_ROLES = {
    "user": (AuthorClass.OPERATOR, DataType.PROMPT),
    "assistant": (AuthorClass.MACHINE, DataType.RESPONSE),
}


# ── protobuf wire format (stdlib only; no schema, no dependency) ─────────────

def _varint(b: bytes, i: int) -> tuple[int, int]:
    r = s = 0
    while i < len(b):
        c = b[i]
        i += 1
        r |= (c & 0x7F) << s
        if not c & 0x80:
            return r, i
        s += 7
        if s > 70:
            raise ValueError("varint too long")
    raise ValueError("truncated varint")


def _fields(b: bytes):
    """Yield (field_no, wiretype, value) over one protobuf message.

    Raises on anything malformed; callers count the raise as a drop. Groups
    (wiretypes 3/4) are deliberately unsupported — they are deprecated, and a
    message using them is not one of ours.
    """
    i, end = 0, len(b)
    while i < end:
        key, i = _varint(b, i)
        fn, wt = key >> 3, key & 7
        if fn == 0:
            raise ValueError("field number 0")
        if wt == 0:
            v, i = _varint(b, i)
        elif wt == 1:
            v, i = b[i:i + 8], i + 8
        elif wt == 2:
            n, i = _varint(b, i)
            if i + n > end:
                raise ValueError("length overruns message")
            v, i = b[i:i + n], i + n
        elif wt == 5:
            v, i = b[i:i + 4], i + 4
        else:
            raise ValueError(f"unsupported wiretype {wt}")
        if wt in (1, 5) and len(v) < (8 if wt == 1 else 4):
            raise ValueError("truncated fixed-width field")
        yield fn, wt, v


def _step_clocks(data: bytes) -> list[int]:
    """Every step start-time (ms) in one protobuf blob, ascending.

    Returns [] for a blob that is not a step container — including one that
    fails to parse, which the caller counts.
    """
    out: list[int] = []
    try:
        top = list(_fields(data))
    except Exception:
        return out
    for fn, wt, v in top:
        if fn != _F_STEPS or wt != 2:
            continue
        try:
            step = list(_fields(v))
        except Exception:
            continue
        if not any(f == _F_CALL_ID and w == 2 for f, w, _ in step):
            continue
        for f, w, val in step:
            if f == _F_START_MS and w == 0 and _MS_LO < val < _MS_HI:
                out.append(val)
    out.sort()
    return out


# ── the store ────────────────────────────────────────────────────────────────

def _thread_start_ms(db: Path, con) -> int | None:
    """The thread's own start, from a log field. `meta.json` first (it is the
    file Cursor maintains beside the store), then the store's `meta` row."""
    try:
        o = json.loads((db.parent / "meta.json").read_text(encoding="utf-8"))
        v = o.get("createdAtMs")
        if isinstance(v, (int, float)) and _MS_LO < v < _MS_HI:
            return int(v)
    except Exception:
        pass
    try:
        for (val,) in con.execute("SELECT value FROM meta"):
            try:
                raw = bytes.fromhex(val).decode("utf-8") if isinstance(val, str) else val
                v = json.loads(raw).get("createdAt")
            except Exception:
                continue
            if isinstance(v, (int, float)) and _MS_LO < v < _MS_HI:
                return int(v)
    except sqlite3.DatabaseError:
        pass
    return None


def _turn_text(o: dict) -> str:
    """Message text from a JSON blob. `content` is a string, or a list of
    blocks of which only the text ones are the message."""
    c = o.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts = []
        for b in c:
            if isinstance(b, dict) and isinstance(b.get("text"), str):
                parts.append(b["text"])
            elif isinstance(b, str):
                parts.append(b)
        return " ".join(parts)
    return ""


def _read_store(db: Path, rel: str):
    """One store.db -> (turns, dropped).

    A turn is (ms, role, text, real_ref). `ms` is the last LOGGED moment at or
    before the turn: the thread start, advanced by each tool step passed in
    insertion order. Rows come back in rowid order, which is insertion order —
    the store's own record of sequence, and the only ordering it offers.
    """
    dropped = 0
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    except sqlite3.Error:
        return [], 1
    try:
        try:
            rows = con.execute("SELECT data FROM blobs ORDER BY rowid").fetchall()
        except sqlite3.DatabaseError:
            return [], 1          # not a readable store: one counted drop
        start_ms = _thread_start_ms(db, con)
        if start_ms is None:
            return [], len(rows) or 1   # undatable thread: nothing invented
        turns = []
        clock = start_ms
        for n, (data,) in enumerate(rows):
            if not isinstance(data, (bytes, bytearray)) or not data:
                dropped += 1
                continue
            data = bytes(data)
            if data[:1] == b"{":
                try:
                    o = json.loads(data)
                except Exception:
                    dropped += 1
                    continue
                if not isinstance(o, dict):
                    dropped += 1
                    continue
                if o.get("role") not in _ROLES:      # tool / system / unknown
                    dropped += 1
                    continue
                turns.append((clock, o["role"], _turn_text(o), f"{rel}:blob{n}"))
                continue
            clocks = _step_clocks(data)
            if not clocks:
                dropped += 1                          # opaque, encrypted, or not ours
                continue
            for ms in clocks:
                turns.append((ms, "tool", "", f"{rel}:blob{n}"))
            clock = max(clock, clocks[-1])
        return turns, dropped
    finally:
        con.close()


@register_default_path("cursor-store", "~/.cursor/chats")
@register("cursor-store", source="dir", pattern="store.db")
def ingest(path: str, corpus_id: str = "corpus"):
    root = Path(path)
    if root.exists() and not root.is_dir():
        raise NotADirectoryError(
            f"the cursor-store adapter takes a directory of **/store.db, not a file: {path}")

    by_thread: dict[str, list] = {}
    dropped = 0
    for db in sorted(root.rglob("store.db")):
        rel = db.relative_to(root).as_posix()
        try:
            turns, d = _read_store(db, rel)
        except Exception:
            dropped += 1                              # never abort the walk
            continue
        dropped += d
        if turns:
            by_thread[rel] = turns

    if not by_thread:
        return [], Quarantine(), dropped

    def _day(ms: int) -> datetime.date:
        return datetime.datetime.fromtimestamp(ms / 1000.0, datetime.timezone.utc).date()

    base = min(_day(t[0]) for turns in by_thread.values() for t in turns)

    events: list[Event] = []
    ref_map: dict = {}
    for rel, turns in by_thread.items():
        sid = _hash(corpus_id, rel)
        prev_ms = None
        prev_day = None
        for ms, role, text, real_ref in turns:
            day_offset = (_day(ms) - base).days
            if role == "tool":
                author, dtype, stripped = AuthorClass.MACHINE, DataType.TOOL_EVENT, False
                # A tool step has a real clock, so it earns a real delta —
                # censored across a day boundary, which would pin the hour.
                delta = ((ms - prev_ms) / 1000.0
                         if prev_ms is not None and prev_day == day_offset else None)
                prev_ms, prev_day = ms, day_offset
                feats = _features("", False)
            else:
                if role == "user":
                    text, stripped = authored_text(text)
                else:
                    stripped = False
                if not text.strip():
                    dropped += 1
                    continue
                author, dtype = _ROLES[role]
                # No clock of its own: the store does not time operator or
                # assistant turns. None is the truth; a computed value would be
                # a guess wearing a measurement's clothes.
                delta = None
                feats = _features(text, stripped)
            opaque = _hash(sid, real_ref)
            ref_map[opaque] = real_ref
            events.append(Event(
                event_id=opaque, corpus_id=corpus_id, adapter_id="cursor-store/1",
                source_ref=opaque, thread_id=sid, surface=Surface.IDE,
                author_class=author, data_type=dtype,
                time=CoarseTime(day_offset=day_offset, delta_prev_s=delta),
                features=feats))
    return events, Quarantine(base_date_iso=base.isoformat(), ref_map=ref_map), dropped
