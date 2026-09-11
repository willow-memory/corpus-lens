"""Shared row→Event assembly for database-sourced adapters (sqlite, postgres).

DB adapters differ from the file adapters ONLY in how rows are fetched. The
moment a row is normalized to (date, epoch|None, session_key, role, text,
real_ref), the wall logic is identical to `claude_code.py` — relative day
offsets from a quarantined base date, within-day tempo deltas with
cross-midnight censoring, injection-stripped operator text, opaque hashed refs
whose real locator lives only in the quarantine `ref_map`, and every unusable
row COUNTED as a drop, never hidden. A re-derivation of that logic per backend
is exactly where a wall bug would hide, so it lives here once and the proven
`_features`/`_hash` helpers are reused verbatim.

Nothing host-specific reaches an Event: the connection string / db path (which
can embed a username or home dir, like a filename embeds dates) is NEVER used
as a `real_ref`, `session_key`, or `corpus_id`. A row's locator is
`"<table>:row<n>"` — an addressable, host-free ordinal — and even that is
hashed before it reaches the Event, mirroring how filenames are quarantined.
"""
from __future__ import annotations

import datetime
import re

from ..model import AuthorClass, CoarseTime, DataType, Event, Quarantine
from ..classifiers import _features, _hash  # shared by every adapter, owned by none
from .injection import authored_text

# ── role mapping ─────────────────────────────────────────────────────────────
# A generic corpus table's role column carries arbitrary values. Map only the
# conventional ones; an UNRECOGNIZED role is NOT guessed — the row is dropped
# (and counted), because mislabeling who authored a turn corrupts every
# composition/steering/tempo number downstream. Under-counting beats over-
# claiming, the same rule the file adapters live by.
OPERATOR_ROLES = frozenset({"user", "operator", "human", "prompt", "you", "me"})
MACHINE_ROLES = frozenset({"assistant", "machine", "agent", "ai", "model",
                           "response", "bot", "system", "tool"})


def classify_role(raw_role) -> str | None:
    """'operator' | 'machine' | None (unknown → caller counts a drop)."""
    if not isinstance(raw_role, str):
        return None
    r = raw_role.strip().lower()
    if r in OPERATOR_ROLES:
        return "operator"
    if r in MACHINE_ROLES:
        return "machine"
    return None


# ── column resolution (alias-based, like willow-mcp's schema adaptation) ──────
TS_ALIASES = ("ts", "timestamp", "created_at", "created", "time", "date",
              "datetime", "inserted_at", "event_time", "occurred_at", "at")
ROLE_ALIASES = ("role", "author", "author_class", "sender", "type", "speaker",
                "direction", "kind", "who")
CONTENT_ALIASES = ("content", "text", "message", "body", "prompt", "value",
                   "data", "msg", "payload")
SESSION_ALIASES = ("session", "session_id", "thread", "thread_id",
                   "conversation_id", "conversation", "chat_id", "chat",
                   "thread_key", "dialog_id")


def resolve_columns(columns) -> dict:
    """Map the four roles we need onto actual column names, case-insensitively.
    `session` is optional (its absence collapses the corpus to one thread);
    `ts`, `role`, `content` are required and a caller validates their presence."""
    lower = {c.lower(): c for c in columns}

    def pick(aliases):
        for a in aliases:
            if a in lower:
                return lower[a]
        return None

    return {"ts": pick(TS_ALIASES), "role": pick(ROLE_ALIASES),
            "content": pick(CONTENT_ALIASES), "session": pick(SESSION_ALIASES)}


def require_columns(mapping: dict, table: str, columns) -> None:
    missing = [k for k in ("ts", "role", "content") if not mapping.get(k)]
    if missing:
        raise ValueError(
            f"table {table!r} is missing a resolvable column for: "
            f"{', '.join(missing)}. Looked for (case-insensitive) — "
            f"ts∈{TS_ALIASES}, role∈{ROLE_ALIASES}, content∈{CONTENT_ALIASES}. "
            f"Found columns: {sorted(columns)}.")


# ── timestamp parsing (DB-tolerant; naive → UTC for reproducibility) ──────────
_DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_OFF_HHMM = re.compile(r"([+-]\d{2})(\d{2})$")     # trailing basic offset  +0530
_OFF_HH = re.compile(r"[+-]\d{2}$")                # trailing hour-only     +00


def _normalize_offset(s: str) -> str:
    """Rewrite a trailing tz offset to the extended `±HH:MM` form. Python 3.10's
    `datetime.fromisoformat` rejects the hour-only (`+00`) and basic (`+0530`)
    offsets that a Postgres `timestamptz::text` on a UTC server routinely emits;
    3.11+ accepts them. Normalizing here makes the SAME corpus parse identically
    on every interpreter in the CI matrix — otherwise the 3.10 leg silently loses
    the epoch and censors within-day tempo that 3.11+ keeps."""
    m = _OFF_HHMM.search(s)
    if m:
        return s[:m.start()] + m.group(1) + ":" + m.group(2)
    if _OFF_HH.search(s):
        return s + ":00"
    return s


def parse_db_ts(val):
    """(date, epoch|None) from a DB timestamp cell. Accepts epoch numbers, ISO
    strings ('T' OR space separated, with or without a tz offset), and
    datetime/date objects. Naive datetimes are read as UTC so the same corpus
    yields identical deltas on any machine (never the host timezone) — the wall's
    reproducibility rule, matching the file adapters. A DATE-ONLY value carries no
    clock, so it returns `(date, None)` — never a synthesized midnight epoch that
    would fabricate a 0-second tempo delta. Unparseable → (None, None) so the
    caller counts a drop instead of crashing."""
    if isinstance(val, bool):                      # bool is an int subclass — reject
        return None, None
    if isinstance(val, (int, float)):
        try:
            dt = datetime.datetime.fromtimestamp(float(val), tz=datetime.timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None, None
        return dt.date(), dt.timestamp()
    if isinstance(val, datetime.datetime):
        dt = val if val.tzinfo else val.replace(tzinfo=datetime.timezone.utc)
        return dt.date(), dt.timestamp()
    if isinstance(val, datetime.date):
        return val, None
    if not isinstance(val, str):
        return None, None
    s = val.strip()
    if not s:
        return None, None
    if _DATE_ONLY.match(s):                         # pure date — no clock to synthesize
        try:
            return datetime.date.fromisoformat(s), None
        except ValueError:
            return None, None
    s = _normalize_offset(s.replace("Z", "+00:00").replace("z", "+00:00"))
    try:
        dt = datetime.datetime.fromisoformat(s)
        d = dt.date()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return d, dt.timestamp()
    except ValueError:
        pass
    try:                                            # last resort: a leading date,
        return datetime.date.fromisoformat(s[:10]), None   # but never a fake clock
    except ValueError:
        return None, None


def as_text(val) -> str:
    if val is None:
        return ""
    if isinstance(val, bytes):
        return val.decode("utf-8", "replace")
    return val if isinstance(val, str) else str(val)


# ── the shared assembler (mirrors claude_code.py exactly) ─────────────────────
def assemble(raw, corpus_id: str, adapter_id: str, surface):
    """raw: iterable of (date, epoch|None, session_key, role, text, real_ref),
    role ∈ {'operator','machine'}. Returns (events, Quarantine, dropped) applying
    the same wall discipline as the claude-code adapter: per-session chronological
    sort, cross-midnight delta censoring, operator-text injection stripping,
    empty-text turns dropped-and-counted, opaque hashed refs with the real
    locator kept only in the quarantine map."""
    raw = list(raw)
    if not raw:
        return [], Quarantine(), 0
    base = min(r[0] for r in raw)
    by_session: dict = {}
    for rec in raw:
        by_session.setdefault(rec[2], []).append(rec)
    for recs in by_session.values():
        recs.sort(key=lambda r: (r[1] is None, r[1] if r[1] is not None else 0.0))

    events = []
    ref_map: dict = {}
    dropped = 0
    for session, recs in by_session.items():
        sid = _hash(corpus_id, session)
        prev_epoch = None
        prev_day = None
        for d, epoch, _, role, text, real_ref in recs:
            day_offset = (d - base).days
            if role == "operator":
                text, stripped = authored_text(text)
                author, dtype = AuthorClass.OPERATOR, DataType.PROMPT
            else:
                author, dtype, stripped = AuthorClass.MACHINE, DataType.RESPONSE, False
            if not text.strip():
                dropped += 1
                if epoch is not None:               # keep the clock advancing
                    prev_epoch, prev_day = epoch, day_offset
                continue
            # censor cross-day deltas: a midnight-crossing gap would pin the hour
            same_day = (prev_day == day_offset)
            delta = (epoch - prev_epoch) if (epoch is not None and prev_epoch is not None
                                             and same_day) else None
            if epoch is not None:
                prev_epoch, prev_day = epoch, day_offset
            opaque = _hash(sid, real_ref)
            ref_map[opaque] = real_ref
            events.append(Event(
                event_id=opaque, corpus_id=corpus_id, adapter_id=adapter_id,
                source_ref=opaque, thread_id=sid, surface=surface,
                author_class=author, data_type=dtype,
                time=CoarseTime(day_offset=day_offset, delta_prev_s=delta),
                features=_features(text, stripped)))
    return events, Quarantine(base_date_iso=base.isoformat(), ref_map=ref_map), dropped
